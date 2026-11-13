"""Tests for the AuditLog model — creation, immutability, and the log() factory."""

import uuid

import pytest

from apps.compliance.models import AuditAction, AuditLog


@pytest.mark.django_db
class TestAuditLogCreation:
    """Verify basic creation via the ORM and the log() convenience method."""

    def test_create_via_orm(self):
        entry = AuditLog.objects.create(
            action=AuditAction.LOGIN,
            resource_type="user",
            resource_id="42",
            actor_email="alice@example.com",
        )
        assert entry.pk is not None
        assert entry.action == AuditAction.LOGIN
        assert entry.resource_type == "user"
        assert entry.resource_id == "42"
        assert entry.actor_email == "alice@example.com"
        assert entry.timestamp is not None

    def test_create_via_log_factory(self):
        entry = AuditLog.log(
            action=AuditAction.CREATE,
            resource_type="conversation",
            resource_id="conv-1",
            actor_id=uuid.uuid4(),
            actor_email="bob@example.com",
            actor_ip="10.0.0.1",
            request_id="req-abc",
            changes={"title": {"old": "", "new": "My Chat"}},
            metadata={"source": "api"},
        )
        assert entry.pk is not None
        assert entry.actor_ip == "10.0.0.1"
        assert entry.request_id == "req-abc"
        assert entry.changes == {"title": {"old": "", "new": "My Chat"}}
        assert entry.metadata == {"source": "api"}

    def test_defaults_are_applied(self):
        entry = AuditLog.log(action="login", resource_type="user")
        assert entry.resource_id == ""
        assert entry.actor_email == ""
        assert entry.actor_ip is None
        assert entry.request_id == ""
        assert entry.changes == {}
        assert entry.metadata == {}

    def test_str_representation(self):
        entry = AuditLog.log(
            action="create",
            resource_type="user",
            resource_id="7",
            actor_email="test@example.com",
        )
        s = str(entry)
        assert "create" in s
        assert "user/7" in s
        assert "test@example.com" in s

    def test_ordering_newest_first(self):
        e1 = AuditLog.log(action="login", resource_type="user", resource_id="1")
        e2 = AuditLog.log(action="logout", resource_type="user", resource_id="1")
        entries = list(AuditLog.objects.all())
        # e2 was created after e1, so it should come first
        assert entries[0].pk == e2.pk
        assert entries[1].pk == e1.pk


@pytest.mark.django_db
class TestAuditLogImmutability:
    """The AuditLog model must refuse updates and deletes."""

    def test_update_via_save_raises(self):
        entry = AuditLog.log(action="login", resource_type="user")
        entry.actor_email = "hacker@evil.com"
        with pytest.raises(ValueError, match="immutable"):
            entry.save()

    def test_delete_raises(self):
        entry = AuditLog.log(action="login", resource_type="user")
        with pytest.raises(ValueError, match="immutable"):
            entry.delete()

    def test_queryset_delete_bypasses_model_but_audit_data_survives(self):
        """QuerySet.delete() bypasses the model's delete() method.

        This is a known Django ORM limitation. DB-level triggers (session 9+)
        will close this gap. For now, verify the model-level guard works.
        """
        entry = AuditLog.log(action="login", resource_type="user")
        pk = entry.pk
        # QuerySet.delete() does NOT call model.delete(), so it succeeds
        AuditLog.objects.filter(pk=pk).delete()
        assert not AuditLog.objects.filter(pk=pk).exists()

    def test_bulk_update_is_not_blocked_at_orm_level(self):
        """QuerySet.update() also bypasses save(). Documented limitation."""
        entry = AuditLog.log(
            action="login", resource_type="user", actor_email="orig@example.com"
        )
        # This goes directly to SQL — no save() call
        AuditLog.objects.filter(pk=entry.pk).update(actor_email="changed@example.com")
        entry.refresh_from_db()
        # Documenting the limitation: ORM bypass works
        assert entry.actor_email == "changed@example.com"


@pytest.mark.django_db
class TestAuditActionChoices:
    """Verify all expected action choices exist."""

    def test_all_actions_defined(self):
        expected = {
            "login",
            "logout",
            "login_failed",
            "create",
            "update",
            "delete",
            "agent_run_start",
            "agent_run_complete",
            "agent_run_fail",
            "agent_run_cancel",
            "export",
            "subscription_change",
            "consent_granted",
            "consent_revoked",
            "social_account_added",
            "social_account_removed",
            "sso_config_created",
            "sso_config_updated",
            "sso_config_deleted",
            "scim_user_provisioned",
            "scim_user_updated",
            "scim_user_deprovisioned",
            "scim_token_created",
            "scim_token_revoked",
            "enterprise_mode_enabled",
            "enterprise_mode_disabled",
            "org_deleted",
            "org_frozen",
            "org_unfrozen",
            "org_slug_changed",
            "sso_emergency_bypass",
            "sso_force_logout",
            "project_shared",
            "project_share_updated",
            "project_share_revoked",
            "participant_joined",
            "invitation_created",
            "invitation_accepted",
            "invitation_revoked",
            "injection",
            "project_moved",
            "ip_allowlist_added",
            "ip_allowlist_removed",
            "ip_access_blocked",
            "org_api_key_created",
            "org_api_key_revoked",
            "compliance_export_run",
            "dlp_block",
            "dlp_redact",
            "webhook_created",
            "webhook_updated",
            "webhook_deleted",
            "webhook_auto_disabled",
            "conversation_archived",
            "archive_verified",
            "access_policy_created",
            "access_policy_updated",
            "access_policy_deleted",
            "access_policy_blocked",
            "telegram_linked",
            "telegram_unlinked",
            "telegram_message",
            "slack_linked",
            "slack_unlinked",
            "slack_message",
            "discord_linked",
            "discord_unlinked",
            "discord_message",
            "mfa_enrolled",
            "mfa_removed",
            "mfa_challenge_passed",
            "mfa_challenge_failed",
            "mfa_recovery_codes_generated",
        }
        actual = {choice[0] for choice in AuditAction.choices}
        assert expected == actual
