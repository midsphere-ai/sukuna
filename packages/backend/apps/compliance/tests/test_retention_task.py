"""Tests for the apply_retention_policies Celery task."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.compliance.models import AuditLog, RetentionPolicy
from apps.compliance.tasks import apply_retention_policies


@pytest.fixture
def delete_policy():
    policy, _ = RetentionPolicy.objects.get_or_create(
        resource_type="webhook_events",
        defaults={"retention_days": 90, "action": "delete"},
    )
    # Ensure active and expected config
    policy.retention_days = 90
    policy.action = "delete"
    policy.is_active = True
    policy.last_run_at = None
    policy.records_affected_last_run = 0
    policy.save()
    return policy


@pytest.fixture
def anonymize_policy():
    policy, _ = RetentionPolicy.objects.get_or_create(
        resource_type="conversations",
        defaults={"retention_days": 365, "action": "anonymize"},
    )
    policy.retention_days = 365
    policy.action = "anonymize"
    policy.is_active = True
    policy.save()
    return policy


@pytest.fixture
def keep_policy():
    policy, _ = RetentionPolicy.objects.get_or_create(
        resource_type="audit_logs",
        defaults={"retention_days": 730, "action": "keep"},
    )
    policy.retention_days = 730
    policy.action = "keep"
    policy.is_active = True
    policy.save()
    return policy


@pytest.fixture
def inactive_policy():
    policy, _ = RetentionPolicy.objects.get_or_create(
        resource_type="failed_payments",
        defaults={"retention_days": 90, "action": "delete"},
    )
    policy.is_active = False
    policy.save()
    return policy


@pytest.mark.django_db
class TestApplyRetentionPoliciesTask:
    def test_inactive_policies_skipped(self, inactive_policy):
        result = apply_retention_policies()
        # inactive policy should not appear in results
        assert "failed_payments" not in result["results"]

    def test_no_expired_records(self, delete_policy):
        """When no records are older than retention_days, count is 0."""
        from apps.billing.models import WebhookEvent

        # Create a recent webhook event
        WebhookEvent.objects.create(
            event_id="recent-evt-1",
            event_type="test",
            payload={},
        )
        result = apply_retention_policies()
        assert result["results"]["webhook_events"] == 0

    def test_delete_expired_records(self, delete_policy):
        """Delete action removes expired records."""
        from apps.billing.models import WebhookEvent

        # Create an old webhook event
        old_event = WebhookEvent.objects.create(
            event_id="old-evt-1",
            event_type="test",
            payload={},
        )
        # Backdate it
        cutoff = timezone.now() - timedelta(days=91)
        WebhookEvent.objects.filter(pk=old_event.pk).update(created_at=cutoff)

        # Create a recent one that should survive
        WebhookEvent.objects.create(
            event_id="recent-evt-2",
            event_type="test",
            payload={},
        )

        result = apply_retention_policies()
        assert result["results"]["webhook_events"] == 1
        assert WebhookEvent.objects.filter(event_id="old-evt-1").count() == 0
        assert WebhookEvent.objects.filter(event_id="recent-evt-2").count() == 1

    def test_anonymize_conversations(self, anonymize_policy):
        """Anonymize action sets title to 'Deleted' and clears summary."""
        from apps.storage.models import Conversation
        from apps.users.tests.factories import UserFactory

        user = UserFactory()
        convo = Conversation.objects.create(
            title="Secret Chat",
            summary="Contains PII",
            user=user,
        )
        # Backdate it
        cutoff = timezone.now() - timedelta(days=366)
        Conversation.objects.filter(pk=convo.pk).update(date_created=cutoff)

        result = apply_retention_policies()
        assert result["results"]["conversations"] == 1

        convo.refresh_from_db()
        assert convo.title == "Deleted"
        assert convo.summary == ""

    def test_keep_action_does_nothing(self, keep_policy):
        """Keep action leaves records intact regardless of age."""
        # Create an old audit log
        old_log = AuditLog.log(
            action="login",
            resource_type="user",
            resource_id="123",
        )
        # Backdate it
        AuditLog.objects.filter(pk=old_log.pk).update(
            timestamp=timezone.now() - timedelta(days=731)
        )

        initial_count = AuditLog.objects.count()
        result = apply_retention_policies()

        # Records counted but not deleted
        assert result["results"]["audit_logs"] >= 1
        # Count hasn't decreased (keep doesn't delete)
        assert AuditLog.objects.count() >= initial_count

    def test_dry_run_no_side_effects(self, delete_policy):
        """Dry run logs counts but doesn't delete or update policy metadata."""
        from apps.billing.models import WebhookEvent

        old_event = WebhookEvent.objects.create(
            event_id="dry-run-evt",
            event_type="test",
            payload={},
        )
        WebhookEvent.objects.filter(pk=old_event.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        result = apply_retention_policies(dry_run=True)
        assert result["dry_run"] is True
        assert result["results"]["webhook_events"] == 1

        # Record still exists
        assert WebhookEvent.objects.filter(event_id="dry-run-evt").exists()

        # Policy metadata not updated
        delete_policy.refresh_from_db()
        assert delete_policy.last_run_at is None
        assert delete_policy.records_affected_last_run == 0

    def test_updates_policy_metadata(self, delete_policy):
        """After execution, last_run_at and records_affected_last_run are updated."""
        from apps.billing.models import WebhookEvent

        old_event = WebhookEvent.objects.create(
            event_id="meta-evt",
            event_type="test",
            payload={},
        )
        WebhookEvent.objects.filter(pk=old_event.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        apply_retention_policies()

        delete_policy.refresh_from_db()
        assert delete_policy.last_run_at is not None
        assert delete_policy.records_affected_last_run == 1

    def test_creates_audit_log_entry(self, delete_policy):
        """Each execution creates an AuditLog entry with results."""
        initial_count = AuditLog.objects.filter(
            resource_type="retention_policy"
        ).count()

        apply_retention_policies()

        new_count = AuditLog.objects.filter(resource_type="retention_policy").count()
        assert new_count == initial_count + 1

        log = AuditLog.objects.filter(resource_type="retention_policy").first()
        assert "results" in log.metadata
        assert log.metadata["dry_run"] is False


@pytest.mark.django_db
class TestCeleryBeatSchedule:
    def test_retention_task_in_beat_schedule(self):
        from django.conf import settings

        schedule = settings.CELERY_BEAT_SCHEDULE
        assert "apply-retention-policies" in schedule
        entry = schedule["apply-retention-policies"]
        assert entry["task"] == "apps.compliance.tasks.apply_retention_policies"


@pytest.mark.django_db
class TestRetentionPolicyEdgeCases:
    """Additional edge-case and integration tests for retention policies."""

    def test_all_policies_inactive_returns_empty(self):
        """When every policy is inactive, results dict is empty."""
        RetentionPolicy.objects.update(is_active=False)
        result = apply_retention_policies()
        assert result["results"] == {}

    def test_multiple_policies_execute_together(self):
        """Multiple active policies all execute in a single run."""
        from apps.billing.models import WebhookEvent
        from apps.storage.models import Conversation
        from apps.users.tests.factories import UserFactory

        # Ensure policies exist and are active
        del_policy, _ = RetentionPolicy.objects.get_or_create(
            resource_type="webhook_events",
            defaults={"retention_days": 90, "action": "delete"},
        )
        del_policy.retention_days = 90
        del_policy.action = "delete"
        del_policy.is_active = True
        del_policy.save()

        anon_policy, _ = RetentionPolicy.objects.get_or_create(
            resource_type="conversations",
            defaults={"retention_days": 365, "action": "anonymize"},
        )
        anon_policy.retention_days = 365
        anon_policy.action = "anonymize"
        anon_policy.is_active = True
        anon_policy.save()

        # Create expired records for both
        evt = WebhookEvent.objects.create(
            event_id="multi-evt", event_type="test", payload={}
        )
        WebhookEvent.objects.filter(pk=evt.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        user = UserFactory()
        convo = Conversation.objects.create(title="Multi", summary="Test", user=user)
        Conversation.objects.filter(pk=convo.pk).update(
            date_created=timezone.now() - timedelta(days=366)
        )

        result = apply_retention_policies()

        assert result["results"]["webhook_events"] >= 1
        assert result["results"]["conversations"] >= 1
        assert not WebhookEvent.objects.filter(event_id="multi-evt").exists()
        convo.refresh_from_db()
        assert convo.title == "Deleted"

    def test_batch_delete_multiple_records(self):
        """Delete action removes all expired records in one batch."""
        from apps.billing.models import WebhookEvent

        policy, _ = RetentionPolicy.objects.get_or_create(
            resource_type="webhook_events",
            defaults={"retention_days": 90, "action": "delete"},
        )
        policy.retention_days = 90
        policy.action = "delete"
        policy.is_active = True
        policy.save()

        # Create 5 old events
        for i in range(5):
            evt = WebhookEvent.objects.create(
                event_id=f"batch-{i}", event_type="test", payload={}
            )
            WebhookEvent.objects.filter(pk=evt.pk).update(
                created_at=timezone.now() - timedelta(days=91)
            )

        result = apply_retention_policies()
        assert result["results"]["webhook_events"] >= 5
        assert WebhookEvent.objects.filter(event_id__startswith="batch-").count() == 0

    def test_anonymize_preserves_recent_conversations(self):
        """Anonymization only affects expired conversations, recent ones are untouched."""
        from apps.storage.models import Conversation
        from apps.users.tests.factories import UserFactory

        policy, _ = RetentionPolicy.objects.get_or_create(
            resource_type="conversations",
            defaults={"retention_days": 365, "action": "anonymize"},
        )
        policy.retention_days = 365
        policy.action = "anonymize"
        policy.is_active = True
        policy.save()

        user = UserFactory()
        recent = Conversation.objects.create(
            title="Recent Chat", summary="Keep me", user=user
        )
        old = Conversation.objects.create(
            title="Old Chat", summary="Anonymize me", user=user
        )
        Conversation.objects.filter(pk=old.pk).update(
            date_created=timezone.now() - timedelta(days=400)
        )

        apply_retention_policies()

        recent.refresh_from_db()
        assert recent.title == "Recent Chat"
        assert recent.summary == "Keep me"

        old.refresh_from_db()
        assert old.title == "Deleted"
        assert old.summary == ""

    def test_unknown_resource_type_returns_zero(self):
        """A policy with an unmapped resource_type produces zero affected records."""
        policy = RetentionPolicy.objects.create(
            resource_type="unknown_type", retention_days=30, action="delete"
        )
        result = apply_retention_policies()
        assert result["results"]["unknown_type"] == 0

    def test_dry_run_does_not_update_any_policy_metadata(self):
        """Dry run must not update last_run_at on any policy."""
        from apps.billing.models import WebhookEvent

        policy, _ = RetentionPolicy.objects.get_or_create(
            resource_type="webhook_events",
            defaults={"retention_days": 90, "action": "delete"},
        )
        policy.retention_days = 90
        policy.action = "delete"
        policy.is_active = True
        policy.last_run_at = None
        policy.records_affected_last_run = 0
        policy.save()

        evt = WebhookEvent.objects.create(
            event_id="dryrun-meta-evt", event_type="test", payload={}
        )
        WebhookEvent.objects.filter(pk=evt.pk).update(
            created_at=timezone.now() - timedelta(days=91)
        )

        apply_retention_policies(dry_run=True)

        policy.refresh_from_db()
        assert policy.last_run_at is None
        assert policy.records_affected_last_run == 0
        # Record still exists
        assert WebhookEvent.objects.filter(event_id="dryrun-meta-evt").exists()
