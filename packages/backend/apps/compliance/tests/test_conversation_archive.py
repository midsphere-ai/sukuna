"""Tests for conversation archival — immutable, tamper-evident session records (US-049)."""

from datetime import timedelta
from uuid import uuid4

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.compliance.models import AuditLog, ConversationArchive
from apps.compliance.tasks import (
    _build_conversation_snapshot,
    archive_idle_conversations,
)
from apps.storage.models import AgentRun, Conversation, ConversationParticipant
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrgArchivalPolicy,
)

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def org():
    return Organization.objects.create(
        name="Test Org", slug=f"test-org-{uuid4().hex[:8]}"
    )


@pytest.fixture
def owner(org):
    user = UserFactory(is_superuser=True)
    OrganizationMembership.objects.create(organization=org, user=user, role="owner")
    return user


@pytest.fixture
def regular_user(org):
    user = UserFactory()
    OrganizationMembership.objects.create(organization=org, user=user, role="member")
    return user


@pytest.fixture
def archival_policy(org):
    return OrgArchivalPolicy.objects.create(
        organization=org,
        is_active=True,
        archive_all_conversations=True,
        retention_years=7,
    )


@pytest.fixture
def inactive_policy(org):
    return OrgArchivalPolicy.objects.create(
        organization=org,
        is_active=False,
        archive_all_conversations=True,
    )


@pytest.fixture
def project(org, owner):
    from apps.spaces.models import Project

    return Project.objects.create(title="Test Project", user=owner, organization=org)


@pytest.fixture
def conversation(owner, project):
    return Conversation.objects.create(
        title="Test conversation",
        user=owner,
        project=project,
        summary="A test conversation.",
    )


@pytest.fixture
def completed_run(conversation, owner):
    """An agent run that finished > 1 hour ago."""
    run = AgentRun.objects.create(
        conversation=conversation,
        user=owner,
        task="Test task",
        status="completed",
        model="test-model",
    )
    # Backdate finished_at to > 1 hour ago
    AgentRun.objects.filter(pk=run.pk).update(
        finished_at=timezone.now() - timedelta(hours=2),
    )
    return AgentRun.objects.get(pk=run.pk)


def _authed_request(rf, method, path, user, **kwargs):
    factory_method = getattr(rf, method)
    request = factory_method(path, **kwargs)
    request.auth = user
    request.request_id = "test-req-id"
    return request


# ── Model Tests ────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestConversationArchiveModel:
    def test_create_archive(self, org, conversation):
        content = {"title": "test", "messages": []}
        content_hash = ConversationArchive.compute_hash(content)

        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=content_hash,
            content=content,
            version=1,
        )

        assert archive.pk is not None
        assert archive.content_hash == content_hash
        assert archive.version == 1
        assert archive.archived_by == "auto"

    def test_immutability_no_update(self, org, conversation):
        content = {"title": "test"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        archive.archived_by = "changed"
        with pytest.raises(ValueError, match="immutable"):
            archive.save()

    def test_immutability_no_delete(self, org, conversation):
        content = {"title": "test"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        with pytest.raises(ValueError, match="immutable"):
            archive.delete()

    def test_compute_hash_deterministic(self):
        content = {"b": 2, "a": 1}
        hash1 = ConversationArchive.compute_hash(content)
        hash2 = ConversationArchive.compute_hash(content)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_compute_hash_different_content(self):
        h1 = ConversationArchive.compute_hash({"a": 1})
        h2 = ConversationArchive.compute_hash({"a": 2})
        assert h1 != h2

    def test_verify_valid(self, org, conversation):
        content = {"title": "verified"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )
        assert archive.verify() is True

    def test_verify_tampered(self, org, conversation):
        content = {"title": "original"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )
        # Tamper with content directly in DB (bypassing save guard)
        ConversationArchive.objects.filter(pk=archive.pk).update(
            content={"title": "tampered"},
        )
        archive.refresh_from_db()
        assert archive.verify() is False

    def test_conversation_set_null_on_delete(self, org, conversation):
        content = {"title": "test"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )
        conversation.delete()

        archive.refresh_from_db()
        assert archive.conversation_id is None
        assert archive.content["title"] == "test"  # Content preserved

    def test_versioning(self, org, conversation):
        content_v1 = {"title": "v1"}
        content_v2 = {"title": "v2"}

        ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content_v1),
            content=content_v1,
            version=1,
        )
        archive_v2 = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content_v2),
            content=content_v2,
            version=2,
        )

        archives = ConversationArchive.objects.filter(
            conversation=conversation
        ).order_by("version")
        assert archives.count() == 2
        assert archives.first().version == 1
        assert archives.last().version == 2
        assert archive_v2.content["title"] == "v2"


# ── GDPR Anonymization Tests ──────────────────────────────────────────────


@pytest.mark.django_db
class TestGDPRAnonymization:
    def test_anonymize_for_gdpr(self, org, conversation):
        content = {
            "title": "Secret Meeting",
            "user_email": "john@example.com",
            "participants": [
                {"email": "john@example.com", "username": "john", "role": "creator"},
                {
                    "email": "jane@example.com",
                    "username": "jane",
                    "role": "collaborator",
                },
            ],
            "agent_runs": [
                {"user_email": "john@example.com", "task": "run test"},
            ],
        }
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="john@example.com",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        archive.anonymize_for_gdpr()
        archive.refresh_from_db()

        # Content anonymized
        assert archive.content["user_email"] == "[Deleted User]"
        assert archive.content["title"] == "[Deleted User]"
        for p in archive.content["participants"]:
            assert p["email"] == "[Deleted User]"
            assert p["username"] == "[Deleted User]"
        for run in archive.content["agent_runs"]:
            assert run["user_email"] == "[Deleted User]"

        # archived_by anonymized (was user email, not 'auto')
        assert archive.archived_by == "[Deleted User]"

        # Hash updated to match new content
        assert archive.verify() is True

    def test_anonymize_preserves_auto_archived_by(self, org, conversation):
        content = {"title": "test", "user_email": "user@test.com"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        archive.anonymize_for_gdpr()
        archive.refresh_from_db()
        assert archive.archived_by == "auto"

    def test_anonymize_archive_record_preserved(self, org, conversation):
        content = {"title": "test"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )
        archive_id = archive.pk

        archive.anonymize_for_gdpr()

        # Record still exists
        assert ConversationArchive.objects.filter(pk=archive_id).exists()


# ── Snapshot Builder Tests ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestBuildConversationSnapshot:
    def test_basic_snapshot(self, conversation, owner):
        snapshot = _build_conversation_snapshot(conversation)

        assert snapshot["conversation_id"] == str(conversation.pk)
        assert snapshot["title"] == "Test conversation"
        assert snapshot["summary"] == "A test conversation."
        assert snapshot["user_email"] == owner.email
        assert isinstance(snapshot["participants"], list)
        assert isinstance(snapshot["agent_runs"], list)

    def test_snapshot_with_runs(self, conversation, completed_run):
        snapshot = _build_conversation_snapshot(conversation)

        assert len(snapshot["agent_runs"]) == 1
        run_data = snapshot["agent_runs"][0]
        assert run_data["id"] == str(completed_run.pk)
        assert run_data["status"] == "completed"
        assert run_data["task"] == "Test task"

    def test_snapshot_with_participants(self, conversation, owner):
        # Use get_or_create in case a signal already created the participant
        ConversationParticipant.objects.get_or_create(
            conversation=conversation,
            user=owner,
            defaults={"role": "creator"},
        )
        snapshot = _build_conversation_snapshot(conversation)
        assert len(snapshot["participants"]) >= 1
        assert any(p["role"] == "creator" for p in snapshot["participants"])

    def test_snapshot_null_user(self, project):
        conv = Conversation.objects.create(
            title="No user conv",
            user=None,
            project=project,
        )
        snapshot = _build_conversation_snapshot(conv)
        assert snapshot["user_email"] == ""


# ── Celery Task Tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestArchiveIdleConversationsTask:
    def test_no_active_policies(self):
        result = archive_idle_conversations()
        assert result["status"] == "no_active_policies"
        assert result["archived"] == 0

    def test_archives_idle_conversation(
        self, archival_policy, conversation, completed_run
    ):
        result = archive_idle_conversations()

        assert result["archived"] == 1
        assert (
            ConversationArchive.objects.filter(conversation=conversation).count() == 1
        )

        archive = ConversationArchive.objects.get(conversation=conversation)
        assert archive.archived_by == "auto"
        assert archive.version == 1
        assert archive.verify() is True

    def test_skips_active_conversation(self, archival_policy, conversation, owner):
        # Create a running agent run
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="Running task",
            status="running",
        )

        result = archive_idle_conversations()
        assert result["archived"] == 0

    def test_skips_recently_finished(self, archival_policy, conversation, owner):
        # Create a run that just finished
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="Just done",
            status="completed",
            finished_at=timezone.now() - timedelta(minutes=30),
        )

        result = archive_idle_conversations()
        assert result["archived"] == 0

    def test_inactive_policy_skipped(
        self, inactive_policy, conversation, completed_run
    ):
        result = archive_idle_conversations()
        assert result["status"] == "no_active_policies"

    def test_no_duplicate_archive(self, archival_policy, conversation, completed_run):
        """Second run doesn't create duplicate if content unchanged."""
        archive_idle_conversations()
        assert (
            ConversationArchive.objects.filter(conversation=conversation).count() == 1
        )

        # Run again — should skip since hash matches
        archive_idle_conversations()
        assert (
            ConversationArchive.objects.filter(conversation=conversation).count() == 1
        )

    def test_new_version_on_content_change(
        self, archival_policy, conversation, completed_run, owner
    ):
        """If conversation changes after archival, create new version."""
        archive_idle_conversations()
        assert (
            ConversationArchive.objects.filter(conversation=conversation).count() == 1
        )

        # Add a new completed run (older than 1h)
        run2 = AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="New task",
            status="completed",
        )
        AgentRun.objects.filter(pk=run2.pk).update(
            finished_at=timezone.now() - timedelta(hours=2),
        )

        archive_idle_conversations()
        archives = ConversationArchive.objects.filter(
            conversation=conversation
        ).order_by("version")
        assert archives.count() == 2
        assert archives.first().version == 1
        assert archives.last().version == 2

    def test_creates_audit_log(self, archival_policy, conversation, completed_run):
        archive_idle_conversations()

        log = AuditLog.objects.filter(
            action="conversation_archived",
            resource_type="conversation_archive",
        ).first()
        assert log is not None
        assert log.metadata["total_archived"] == 1

    def test_skips_deleted_conversations(
        self, archival_policy, conversation, completed_run
    ):
        conversation.is_deleted = True
        conversation.save()

        result = archive_idle_conversations()
        assert result["archived"] == 0

    def test_beat_schedule_entry(self):
        from django.conf import settings

        schedule = settings.CELERY_BEAT_SCHEDULE
        assert "archive-idle-conversations" in schedule
        entry = schedule["archive-idle-conversations"]
        assert entry["task"] == "apps.compliance.tasks.archive_idle_conversations"


# ── API Tests ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestArchiveAPI:
    def test_list_archives(self, rf, owner, org, conversation):
        content = {"title": "test"}
        ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import list_archives

        request = _authed_request(rf, "get", "/api/v1/compliance/archives", owner)
        status, data = list_archives(request)
        assert status == 200
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["conversation_id"] == str(conversation.pk)

    def test_list_archives_filter_by_org(self, rf, owner, org, conversation):
        content = {"title": "test"}
        ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import list_archives

        request = _authed_request(rf, "get", "/api/v1/compliance/archives", owner)
        status, data = list_archives(request, organization_id=str(org.pk))
        assert status == 200
        assert data["total"] == 1

        status, data = list_archives(request, organization_id=str(uuid4()))
        assert status == 200
        assert data["total"] == 0

    def test_list_archives_filter_by_conversation(self, rf, owner, org, conversation):
        content = {"title": "test"}
        ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import list_archives

        request = _authed_request(rf, "get", "/api/v1/compliance/archives", owner)
        status, data = list_archives(request, conversation_id=str(conversation.pk))
        assert status == 200
        assert data["total"] == 1

    def test_list_archives_pagination(self, rf, owner, org, conversation):
        for i in range(3):
            content = {"title": f"test-{i}"}
            ConversationArchive.objects.create(
                conversation=conversation,
                organization=org,
                archived_by="auto",
                content_hash=ConversationArchive.compute_hash(content),
                content=content,
                version=i + 1,
            )

        from apps.compliance.api import list_archives

        request = _authed_request(rf, "get", "/api/v1/compliance/archives", owner)
        status, data = list_archives(request, page=1, page_size=2)
        assert status == 200
        assert data["total"] == 3
        assert len(data["results"]) == 2
        assert data["total_pages"] == 2

    def test_list_archives_requires_admin(self, rf, regular_user):
        from apps.compliance.api import list_archives

        request = _authed_request(
            rf, "get", "/api/v1/compliance/archives", regular_user
        )
        status, data = list_archives(request)
        assert status == 403

    def test_verify_archive_valid(self, rf, owner, org, conversation):
        content = {"title": "verified"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import verify_archive

        request = _authed_request(
            rf, "get", f"/api/v1/compliance/archives/{archive.pk}/verify", owner
        )
        status, data = verify_archive(request, archive_id=archive.pk)
        assert status == 200
        assert data["verified"] is True
        assert data["stored_hash"] == data["computed_hash"]

    def test_verify_archive_tampered(self, rf, owner, org, conversation):
        content = {"title": "original"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )
        # Tamper
        ConversationArchive.objects.filter(pk=archive.pk).update(
            content={"title": "tampered"},
        )

        from apps.compliance.api import verify_archive

        request = _authed_request(
            rf, "get", f"/api/v1/compliance/archives/{archive.pk}/verify", owner
        )
        status, data = verify_archive(request, archive_id=archive.pk)
        assert status == 200
        assert data["verified"] is False
        assert data["stored_hash"] != data["computed_hash"]

    def test_verify_archive_not_found(self, rf, owner):
        from apps.compliance.api import verify_archive

        fake_id = uuid4()
        request = _authed_request(
            rf, "get", f"/api/v1/compliance/archives/{fake_id}/verify", owner
        )
        status, data = verify_archive(request, archive_id=fake_id)
        assert status == 404

    def test_verify_creates_audit_log(self, rf, owner, org, conversation):
        content = {"title": "verified"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import verify_archive

        request = _authed_request(
            rf, "get", f"/api/v1/compliance/archives/{archive.pk}/verify", owner
        )
        verify_archive(request, archive_id=archive.pk)

        log = AuditLog.objects.filter(
            action="archive_verified",
            resource_id=str(archive.pk),
        ).first()
        assert log is not None
        assert log.metadata["verified"] is True

    def test_verify_requires_admin(self, rf, regular_user, org, conversation):
        content = {"title": "test"}
        archive = ConversationArchive.objects.create(
            conversation=conversation,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        from apps.compliance.api import verify_archive

        request = _authed_request(
            rf, "get", f"/api/v1/compliance/archives/{archive.pk}/verify", regular_user
        )
        status, data = verify_archive(request, archive_id=archive.pk)
        assert status == 403


# ── OrgArchivalPolicy Tests ───────────────────────────────────────────────


@pytest.mark.django_db
class TestOrgArchivalPolicy:
    def test_create_policy(self, org):
        policy = OrgArchivalPolicy.objects.create(
            organization=org,
            is_active=True,
            archive_all_conversations=True,
            retention_years=7,
        )
        assert policy.pk is not None
        assert policy.retention_years == 7

    def test_one_to_one_constraint(self, org, archival_policy):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            OrgArchivalPolicy.objects.create(
                organization=org,
                is_active=True,
            )

    def test_defaults(self, org):
        policy = OrgArchivalPolicy.objects.create(organization=org)
        assert policy.is_active is False
        assert policy.archive_all_conversations is True
        assert policy.retention_years == 7

    def test_str_representation(self, org):
        policy = OrgArchivalPolicy.objects.create(
            organization=org,
            is_active=True,
            retention_years=5,
        )
        assert "active" in str(policy)
        assert "5y" in str(policy)
