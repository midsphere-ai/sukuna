"""Tests for GDPR compliance services — user data export and account deletion."""

import pytest

from apps.billing.models import (
    CreditWallet,
    Payment,
    SubscriptionPlan,
    UserSubscription,
)
from apps.compliance.models import AuditAction, AuditLog
from apps.compliance.services import delete_user_account, export_user_data
from apps.spaces.models import Project
from apps.storage.models import (
    AgentRun,
    Conversation,
    StoredFile,
    SystemWideMemory,
)
from apps.users.models import DeveloperAPIKey, User, UserSettings
from apps.users.tests.factories import UserFactory

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_user_with_data():
    """Create a user with associated data across all FK relationships."""
    user = UserFactory()

    # Settings (auto-created by post_save signal; mutate cached instance)
    s = user.settings
    s.theme = "dark"
    s.custom_instructions = "Be concise."
    s.data_share_analytics = False
    s.save()

    # API key
    raw_key = DeveloperAPIKey.generate_key()
    DeveloperAPIKey.objects.create(
        name="test-key",
        key_hash=DeveloperAPIKey.hash_key(raw_key),
        key_prefix=raw_key[:8],
        user=user,
        scopes=["read", "write"],
    )

    # Project
    project = Project.objects.create(
        title="My Project",
        description="Test project",
        user=user,
    )

    # Conversation with an agent run
    conv = Conversation.objects.create(user=user, title="Test chat")
    AgentRun.objects.create(
        conversation=conv,
        user=user,
        task="Hello world",
        status="completed",
    )

    # File
    StoredFile.objects.create(
        owner=user,
        name="test.txt",
        size=1024,
        mime_type="text/plain",
    )

    # System memory
    SystemWideMemory.objects.create(user=user, memory_summary="User likes python")

    # Billing — signal auto-provisions CreditWallet on subscription create
    plan, _ = SubscriptionPlan.objects.get_or_create(
        tier="premium",
        defaults={
            "name": "Pro",
            "price": 20,
            "features": {"weekly_tasks": 100},
            "monthly_credits": 1000,
        },
    )
    sub = UserSubscription.objects.create(user=user, plan=plan, status="active")
    Payment.objects.create(user=user, subscription=sub, amount=20)
    # Wallet is auto-created by billing signal; update with test values
    wallet = CreditWallet.objects.get(user=user)
    wallet.free_credits = 150
    wallet.save()

    return user


# ── Export Tests ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestExportUserData:
    def test_export_returns_all_sections(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert data["user_id"] == str(user.id)
        assert "exported_at" in data
        assert "profile" in data
        assert "settings" in data
        assert "api_keys" in data
        assert "projects" in data
        assert "conversations" in data
        assert "agent_runs" in data
        assert "files" in data
        assert "marketplace_addons" in data
        assert "installed_skills" in data
        assert "system_memory" in data
        assert "mcp_configs" in data
        assert "provider_configs" in data
        assert "scheduled_tasks" in data
        assert "billing" in data
        assert "audit_log" in data

    def test_export_profile_fields(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        profile = data["profile"]
        assert profile["email"] == user.email
        assert profile["name"] == user.name
        assert "date_joined" in profile
        assert "is_active" in profile

    def test_export_settings(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        settings = data["settings"]
        assert settings["theme"] == "dark"
        assert settings["custom_instructions"] == "Be concise."
        assert settings["data_share_analytics"] is False

    def test_export_settings_none_when_missing(self):
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        user.refresh_from_db()
        data = export_user_data(user)
        assert data["settings"] is None

    def test_export_api_keys_no_secrets(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert len(data["api_keys"]) == 1
        key = data["api_keys"][0]
        assert key["name"] == "test-key"
        assert key["scopes"] == ["read", "write"]
        assert "key_hash" not in key
        assert "key" not in key

    def test_export_conversations_and_runs(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert len(data["conversations"]) == 1
        assert data["conversations"][0]["title"] == "Test chat"
        assert len(data["agent_runs"]) == 1
        assert data["agent_runs"][0]["task"] == "Hello world"

    def test_export_files(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert len(data["files"]) == 1
        assert data["files"][0]["name"] == "test.txt"
        assert data["files"][0]["size"] == 1024

    def test_export_projects(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert len(data["projects"]) == 1
        assert data["projects"][0]["title"] == "My Project"

    def test_export_system_memory(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        assert len(data["system_memory"]) == 1
        assert data["system_memory"][0]["memory_summary"] == "User likes python"

    def test_export_billing(self):
        user = _make_user_with_data()
        data = export_user_data(user)

        billing = data["billing"]
        assert billing["subscription"]["plan"] == "Pro"
        assert billing["subscription"]["status"] == "active"
        assert len(billing["payments"]) == 1
        assert billing["payments"][0]["amount"] == "20.00"
        assert billing["credit_wallet"]["monthly_credits"] == 1000  # from plan
        assert billing["credit_wallet"]["free_credits"] == 150  # manually set

    def test_export_empty_user(self):
        """A fresh user with no data should still export successfully."""
        user = UserFactory()
        UserSettings.objects.filter(user=user).delete()
        user.refresh_from_db()
        data = export_user_data(user)

        assert data["user_id"] == str(user.id)
        assert data["settings"] is None
        assert data["api_keys"] == []
        assert data["conversations"] == []
        assert data["files"] == []
        assert data["billing"]["subscription"] is None

    def test_export_audit_log_includes_user_actions(self):
        user = _make_user_with_data()
        # Create an audit entry for this user
        AuditLog.log(
            action=AuditAction.LOGIN,
            resource_type="user",
            resource_id=str(user.id),
            actor_id=user.id,
            actor_email=user.email,
        )

        data = export_user_data(user)
        audit_entries = [e for e in data["audit_log"] if e["action"] == "login"]
        assert len(audit_entries) >= 1


# ── Delete Tests ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteUserAccount:
    def test_delete_removes_user(self):
        user = _make_user_with_data()
        user_id = user.id

        result = delete_user_account(user)

        assert result["deleted"] is True
        assert not User.objects.filter(id=user_id).exists()

    def test_delete_cascades_conversations(self):
        user = _make_user_with_data()
        conv_ids = list(user.speaking_to.values_list("id", flat=True))
        assert len(conv_ids) > 0

        delete_user_account(user)

        assert Conversation.objects.filter(id__in=conv_ids).count() == 0

    def test_delete_cascades_projects(self):
        user = _make_user_with_data()
        project_ids = list(user.projects.values_list("id", flat=True))

        delete_user_account(user)

        assert Project.objects.filter(id__in=project_ids).count() == 0

    def test_delete_cascades_files(self):
        user = _make_user_with_data()
        file_ids = list(user.stored_files.values_list("id", flat=True))

        delete_user_account(user)

        assert StoredFile.objects.filter(id__in=file_ids).count() == 0

    def test_delete_cascades_api_keys(self):
        user = _make_user_with_data()
        key_ids = list(user.developer_api_keys.values_list("id", flat=True))

        delete_user_account(user)

        assert DeveloperAPIKey.objects.filter(id__in=key_ids).count() == 0

    def test_delete_cascades_settings(self):
        user = _make_user_with_data()

        delete_user_account(user)

        assert UserSettings.objects.filter(user_id=user.id).count() == 0

    def test_delete_cascades_billing(self):
        user = _make_user_with_data()

        delete_user_account(user)

        assert UserSubscription.objects.filter(user_id=user.id).count() == 0
        assert CreditWallet.objects.filter(user_id=user.id).count() == 0

    def test_delete_sets_null_on_agent_runs(self):
        """AgentRun.user is SET_NULL — completed runs should survive with user=NULL."""
        user = _make_user_with_data()
        run_ids = list(AgentRun.objects.filter(user=user).values_list("id", flat=True))
        # Runs are also CASCADE deleted via conversation FK, but let's make
        # an orphan run to test SET_NULL behavior
        other_user = UserFactory()
        other_conv = Conversation.objects.create(user=other_user, title="Other")
        orphan_run = AgentRun.objects.create(
            conversation=other_conv, user=user, task="orphan", status="completed"
        )

        delete_user_account(user)

        orphan_run.refresh_from_db()
        assert orphan_run.user is None

    def test_delete_sets_null_on_payments(self):
        """Payment.user is CASCADE, so payments should be deleted."""
        user = _make_user_with_data()
        payment_count = Payment.objects.filter(user=user).count()
        assert payment_count > 0

        delete_user_account(user)

        assert Payment.objects.filter(user_id=user.id).count() == 0

    def test_delete_cancels_active_runs(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user, title="Active chat")
        run = AgentRun.objects.create(
            conversation=conv, user=user, task="running task", status="running"
        )

        result = delete_user_account(user)

        assert result["agent_runs_cancelled"] == 1

    def test_delete_creates_audit_record(self):
        user = _make_user_with_data()
        user_id = user.id
        user_email = user.email
        AuditLog.objects.all().delete()

        delete_user_account(user, actor_ip="192.168.1.1", request_id="req-del-1")

        # The service creates an audit log (with IP + request_id), plus the
        # signal handler also fires one (without IP). Filter for the service entry.
        entry = AuditLog.objects.filter(
            action=AuditAction.DELETE,
            resource_type="user",
            resource_id=str(user_id),
            request_id="req-del-1",
        ).first()
        assert entry is not None
        assert entry.actor_email == user_email
        assert entry.actor_ip == "192.168.1.1"
        assert entry.request_id == "req-del-1"

    def test_delete_audit_includes_reason(self):
        user = UserFactory()
        AuditLog.objects.all().delete()

        delete_user_account(user, reason="User requested data removal")

        # Filter for the service-created entry (has metadata with reason)
        entry = AuditLog.objects.filter(
            action=AuditAction.DELETE,
            resource_type="user",
            metadata__reason="User requested data removal",
        ).first()
        assert entry is not None
        assert entry.metadata["reason"] == "User requested data removal"

    def test_delete_summary_counts(self):
        user = _make_user_with_data()

        result = delete_user_account(user)

        assert result["conversations_deleted"] == 1
        assert result["projects_deleted"] == 1
        assert result["files_deleted"] == 1
        assert result["api_keys_deleted"] == 1

    def test_delete_is_atomic(self):
        """If deletion fails partway, nothing should be committed."""
        user = _make_user_with_data()
        user_id = user.id

        # Monkey-patch to simulate a failure during user.delete()
        original_delete = User.delete

        def failing_delete(self, *args, **kwargs):
            raise RuntimeError("Simulated DB failure")

        User.delete = failing_delete
        try:
            with pytest.raises(RuntimeError, match="Simulated DB failure"):
                delete_user_account(user)
        finally:
            User.delete = original_delete

        # User and all related data should still exist
        assert User.objects.filter(id=user_id).exists()
        assert Conversation.objects.filter(user_id=user_id).exists()

    def test_delete_empty_user(self):
        """Deleting a user with no data should work without errors."""
        user = UserFactory()
        result = delete_user_account(user)
        assert result["deleted"] is True
        assert not User.objects.filter(id=user.id).exists()
