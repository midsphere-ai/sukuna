"""Unit tests for agents app models: E2bSandbox + UserCustomMCPConfig."""

import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.db import IntegrityError
from django.utils import timezone

from apps.agents.models import (
    E2bSandbox,
    UserCustomMCPConfig,
)
from apps.storage.models import Conversation
from apps.users.tests.factories import UserFactory

# ---------------------------------------------------------------------------
# UserCustomMCPConfig
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestUserCustomMCPConfig:
    def test_create_stdio_config(self):
        user = UserFactory()
        config = UserCustomMCPConfig.objects.create(
            user=user,
            server_name="my-server",
            server_type=UserCustomMCPConfig.ServerType.STDIO,
            command="npx some-tool",
        )
        assert config.pk is not None
        assert config.server_type == "stdio"
        assert str(config) == f"{user}'s my-server MCP Config"

    def test_create_sse_config(self):
        user = UserFactory()
        config = UserCustomMCPConfig.objects.create(
            user=user,
            server_name="sse-server",
            server_type=UserCustomMCPConfig.ServerType.SSE,
            url="https://example.com/sse",
        )
        assert config.server_type == "sse"
        assert config.url == "https://example.com/sse"

    def test_create_streamable_http_config(self):
        user = UserFactory()
        config = UserCustomMCPConfig.objects.create(
            user=user,
            server_name="http-server",
            server_type=UserCustomMCPConfig.ServerType.STREAMABLE_HTTP,
            url="https://example.com/mcp",
        )
        assert config.server_type == "streamable-http"

    def test_unique_together_user_server_name(self):
        user = UserFactory()
        UserCustomMCPConfig.objects.create(user=user, server_name="dup-name")
        with pytest.raises(IntegrityError):
            UserCustomMCPConfig.objects.create(user=user, server_name="dup-name")

    def test_different_users_same_server_name(self):
        user1 = UserFactory()
        user2 = UserFactory()
        UserCustomMCPConfig.objects.create(user=user1, server_name="shared-name")
        config2 = UserCustomMCPConfig.objects.create(
            user=user2, server_name="shared-name"
        )
        assert config2.pk is not None

    def test_ordering_by_date_created_desc(self):
        user = UserFactory()
        c1 = UserCustomMCPConfig.objects.create(user=user, server_name="first")
        c2 = UserCustomMCPConfig.objects.create(user=user, server_name="second")
        configs = list(UserCustomMCPConfig.objects.filter(user=user))
        assert configs[0].pk == c2.pk
        assert configs[1].pk == c1.pk

    def test_optional_fields_default(self):
        user = UserFactory()
        config = UserCustomMCPConfig.objects.create(user=user, server_name="minimal")
        assert config.command is None
        assert config.arguments == ""
        assert config.env == ""
        assert config.url is None
        assert config.timeout is None
        assert config.sse_read_timeout is None
        assert config.client_session_timeout_seconds is None
        assert config.description == ""

    def test_uuid_primary_key(self):
        user = UserFactory()
        config = UserCustomMCPConfig.objects.create(user=user, server_name="uuid-test")
        assert isinstance(config.pk, uuid.UUID)


# ---------------------------------------------------------------------------
# E2bSandbox — Deprecated properties
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxDeprecatedProperties:
    def _make_sandbox(self, **kwargs):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        defaults = {"conversation": conv}
        defaults.update(kwargs)
        return E2bSandbox.objects.create(**defaults)

    def test_is_running_true_when_ready(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.READY)
        assert sb.is_running is True

    def test_is_running_false_when_not_ready(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.CREATING)
        assert sb.is_running is False

    def test_is_running_setter_true(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.CREATING)
        sb.is_running = True
        assert sb.sandbox_state == E2bSandbox.SandboxState.READY

    def test_is_running_setter_false_from_ready(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.READY)
        sb.is_running = False
        assert sb.sandbox_state == E2bSandbox.SandboxState.TERMINATED

    def test_is_running_setter_false_from_other(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.CREATING)
        sb.is_running = False
        # Should stay CREATING (not READY → TERMINATED path)
        assert sb.sandbox_state == E2bSandbox.SandboxState.CREATING

    def test_is_paused_true(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.PAUSED)
        assert sb.is_paused is True

    def test_is_paused_false(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.READY)
        assert sb.is_paused is False

    def test_is_paused_setter_true(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.READY)
        sb.is_paused = True
        assert sb.sandbox_state == E2bSandbox.SandboxState.PAUSED

    def test_is_paused_setter_false_from_paused(self):
        sb = self._make_sandbox(sandbox_state=E2bSandbox.SandboxState.PAUSED)
        sb.is_paused = False
        assert sb.sandbox_state == E2bSandbox.SandboxState.READY


# ---------------------------------------------------------------------------
# E2bSandbox — str
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxStr:
    def test_str_with_sandbox_id(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_id="sbx-abc",
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        assert str(sb) == "E2bSandbox sbx-abc (ready)"

    def test_str_without_sandbox_id(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.CREATING,
        )
        assert str(sb) == f"E2bSandbox {sb.pk} (creating)"


# ---------------------------------------------------------------------------
# E2bSandbox — _build_sandbox_envs
# ---------------------------------------------------------------------------


class TestBuildSandboxEnvs:
    @patch.dict("os.environ", {}, clear=True)
    @patch("apps.agents.models.settings")
    def test_minimal_envs(self, mock_settings):
        mock_settings.AGENT_SERVER_API_KEY = ""
        mock_settings.SANDBOX_AGENT_SERVER_PORT = 8000
        # getattr fallbacks
        type(mock_settings).__getattr__ = lambda self, name: ""

        envs = E2bSandbox._build_sandbox_envs()
        assert envs["SKIP_DB_DDL"] == "true"
        assert envs["PORT"] == "8000"

    @patch.dict(
        "os.environ",
        {"VAULT_ADDR": "http://vault:8200", "VAULT_TOKEN": "tok"},
        clear=True,
    )
    @patch("apps.agents.models.settings")
    def test_vault_envs(self, mock_settings):
        mock_settings.AGENT_SERVER_API_KEY = "key123"
        mock_settings.SANDBOX_AGENT_SERVER_PORT = 9000
        type(mock_settings).__getattr__ = lambda self, name: ""

        envs = E2bSandbox._build_sandbox_envs()
        assert envs["VAULT_ADDR"] == "http://vault:8200"
        assert envs["VAULT_TOKEN"] == "tok"
        assert envs["API_KEY"] == "key123"
        assert envs["SUKUNA_AGENT_SERVER_API_KEY"] == "key123"
        assert envs["PORT"] == "9000"

    @patch.dict(
        "os.environ", {"AGENT_MODEL": "gpt-4", "AGENT_MAX_STEPS": "50"}, clear=True
    )
    @patch("apps.agents.models.settings")
    def test_optional_passthrough(self, mock_settings):
        mock_settings.AGENT_SERVER_API_KEY = ""
        mock_settings.SANDBOX_AGENT_SERVER_PORT = 8000
        type(mock_settings).__getattr__ = lambda self, name: ""

        envs = E2bSandbox._build_sandbox_envs()
        assert envs["AGENT_MODEL"] == "gpt-4"
        assert envs["AGENT_MAX_STEPS"] == "50"


# ---------------------------------------------------------------------------
# E2bSandbox — _get_mime_type
# ---------------------------------------------------------------------------


class TestGetMimeType:
    def test_known_extension(self):
        assert E2bSandbox._get_mime_type("file.png") == "image/png"

    def test_unknown_extension(self):
        assert E2bSandbox._get_mime_type("file.xyz123") == "application/octet-stream"

    def test_no_extension(self):
        assert E2bSandbox._get_mime_type("Makefile") == "application/octet-stream"


# ---------------------------------------------------------------------------
# E2bSandbox — mark_done
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxMarkDone:
    def test_mark_done_sets_terminated_and_usage(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        now = timezone.now()
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="sbx-done",
        )
        # Override start_time (auto_now_add makes it tricky, use update)
        E2bSandbox.objects.filter(pk=sb.pk).update(
            start_time=now - timedelta(seconds=120)
        )
        sb.refresh_from_db()

        with patch.object(sb, "_record_billing_usage") as mock_billing:
            sb.mark_done()

        sb.refresh_from_db()
        assert sb.sandbox_state == E2bSandbox.SandboxState.TERMINATED
        assert sb.end_time is not None
        assert sb.usage_in_seconds > 0
        mock_billing.assert_called_once()

    def test_mark_done_with_existing_end_time(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        end = timezone.now()
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="sbx-end",
            end_time=end,
        )
        with patch.object(sb, "_record_billing_usage"):
            sb.mark_done()
        sb.refresh_from_db()
        assert sb.end_time == end


# ---------------------------------------------------------------------------
# E2bSandbox — schedule_idle_pause
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxScheduleIdlePause:
    def test_schedule_default_minutes(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        before = timezone.now()
        sb.schedule_idle_pause()
        sb.refresh_from_db()
        assert sb.delayed_termination_at is not None
        assert sb.delayed_termination_at >= before + timedelta(minutes=9)

    def test_schedule_custom_minutes(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        before = timezone.now()
        sb.schedule_idle_pause(minutes=5)
        sb.refresh_from_db()
        assert sb.delayed_termination_at >= before + timedelta(minutes=4)


# ---------------------------------------------------------------------------
# E2bSandbox — update_end_time
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxUpdateEndTime:
    def test_update_end_time(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        end = timezone.now() + timedelta(hours=1)
        with patch.object(sb, "_record_billing_usage") as mock_billing:
            sb.update_end_time(end)
        sb.refresh_from_db()
        assert sb.end_time == end
        mock_billing.assert_called_once()


# ---------------------------------------------------------------------------
# E2bSandbox — download_files raises on no conversation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxDownloadFilesNoConversation:
    def test_raises_when_no_conversation(self):
        sb = E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        mock_sandbox = MagicMock()
        with pytest.raises(ValueError, match="conversation was deleted"):
            sb.download_files(mock_sandbox, ["/some/file.txt"])


# ---------------------------------------------------------------------------
# E2bSandboxManager & QuerySet
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxManager:
    @pytest.fixture(autouse=True)
    def setup_data(self):
        self.user = UserFactory()
        self.conv = Conversation.objects.create(user=self.user)
        self.conv2 = Conversation.objects.create(user=self.user)

    def _create(self, **kwargs):
        defaults = {"conversation": self.conv}
        defaults.update(kwargs)
        return E2bSandbox.objects.create(**defaults)

    def test_active_for_conversation(self):
        ready = self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        self._create(sandbox_state=E2bSandbox.SandboxState.TERMINATED)
        self._create(sandbox_state=E2bSandbox.SandboxState.ERROR)

        result = E2bSandbox.objects.active_for_conversation(self.conv)
        assert list(result) == [ready]

    def test_ready_for_conversation(self):
        ready = self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        self._create(sandbox_state=E2bSandbox.SandboxState.PAUSED)

        result = E2bSandbox.objects.ready_for_conversation(self.conv)
        assert list(result) == [ready]

    def test_pool_ready(self):
        pool = self._create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        self._create(
            conversation=self.conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )

        result = E2bSandbox.objects.pool_ready()
        assert pool in result
        assert result.count() == 1

    def test_pool_stale(self):
        old = self._create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        # Force old start_time
        E2bSandbox.objects.filter(pk=old.pk).update(
            start_time=timezone.now() - timedelta(minutes=60)
        )

        self._create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )

        result = E2bSandbox.objects.pool_stale(max_age_minutes=50)
        assert result.count() == 1

    def test_pool_stale_creating(self):
        stuck = self._create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.CREATING,
        )
        E2bSandbox.objects.filter(pk=stuck.pk).update(
            start_time=timezone.now() - timedelta(minutes=15)
        )

        result = E2bSandbox.objects.pool_stale_creating(max_age_minutes=10)
        assert result.count() == 1

    def test_idle_past_deadline(self):
        past = self._create(
            sandbox_state=E2bSandbox.SandboxState.READY,
            delayed_termination_at=timezone.now() - timedelta(minutes=5),
        )
        self._create(
            sandbox_state=E2bSandbox.SandboxState.READY,
            delayed_termination_at=timezone.now() + timedelta(minutes=30),
        )
        self._create(
            sandbox_state=E2bSandbox.SandboxState.READY,
        )

        result = E2bSandbox.objects.idle_past_deadline()
        assert result.count() == 1
        assert past in result

    def test_for_user(self):
        self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        other_user = UserFactory()
        other_conv = Conversation.objects.create(user=other_user)
        self._create(
            conversation=other_conv, sandbox_state=E2bSandbox.SandboxState.READY
        )

        result = E2bSandbox.objects.for_user(self.user)
        assert result.count() == 1

    def test_active_for_project_none(self):
        result = E2bSandbox.objects.active_for_project(None)
        assert result.count() == 0

    def test_queryset_active(self):
        self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        self._create(sandbox_state=E2bSandbox.SandboxState.PAUSED)
        self._create(sandbox_state=E2bSandbox.SandboxState.TERMINATED)
        self._create(sandbox_state=E2bSandbox.SandboxState.ERROR)

        active = E2bSandbox.objects.get_queryset().active()
        assert active.count() == 2

    def test_queryset_by_state(self):
        self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        self._create(sandbox_state=E2bSandbox.SandboxState.PAUSED)

        result = E2bSandbox.objects.get_queryset().by_state(
            E2bSandbox.SandboxState.PAUSED
        )
        assert result.count() == 1

    def test_queryset_pool(self):
        self._create(conversation=None)
        self._create(conversation=self.conv)

        pool = E2bSandbox.objects.get_queryset().pool()
        assert pool.count() == 1

    def test_queryset_latest_first(self):
        s1 = self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        s2 = self._create(sandbox_state=E2bSandbox.SandboxState.READY)
        result = list(
            E2bSandbox.objects.get_queryset()
            .filter(conversation=self.conv)
            .latest_first()
        )
        assert result[0].pk == s2.pk


# ---------------------------------------------------------------------------
# E2bSandbox — claim_from_pool
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxClaimFromPool:
    def test_claim_assigns_conversation(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        pool_sb = E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="pool-1",
        )

        claimed = E2bSandbox.claim_from_pool(conv)
        assert claimed is not None
        assert claimed.pk == pool_sb.pk
        claimed.refresh_from_db()
        assert claimed.conversation == conv
        assert claimed.delayed_termination_at is None

    def test_claim_returns_none_when_empty(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        result = E2bSandbox.claim_from_pool(conv)
        assert result is None

    def test_claim_skips_non_ready(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.CREATING,
        )
        result = E2bSandbox.claim_from_pool(conv)
        assert result is None

    def test_claim_fifo_oldest_first(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb1 = E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="old",
        )
        E2bSandbox.objects.filter(pk=sb1.pk).update(
            start_time=timezone.now() - timedelta(hours=1)
        )
        E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="new",
        )

        claimed = E2bSandbox.claim_from_pool(conv)
        assert claimed.sandbox_id == "old"


# ---------------------------------------------------------------------------
# E2bSandbox — _record_billing_usage
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxRecordBillingUsage:
    def test_no_conversation_skips(self):
        sb = E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        # Should not raise
        sb._record_billing_usage(100)

    def test_no_subscription_logs_warning(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
        )
        # If no UserSubscription record exists, it logs but doesn't raise
        sb._record_billing_usage(100)


# ---------------------------------------------------------------------------
# E2bSandbox — get_sse_link
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestE2bSandboxGetSseLink:
    def test_returns_sse_url(self):
        user = UserFactory()
        conv = Conversation.objects.create(user=user)
        sb = E2bSandbox.objects.create(
            conversation=conv,
            sandbox_state=E2bSandbox.SandboxState.READY,
            sandbox_id="sbx-sse",
        )
        mock_sandbox = MagicMock()
        mock_sandbox.get_host.return_value = "sbx-sse-14000.e2b.dev"
        mock_sandbox.commands.run = MagicMock()

        url = sb.get_sse_link(mock_sandbox, "some-command", {"KEY": "val"}, 14000)
        assert url == "https://sbx-sse-14000.e2b.dev/sse"
        mock_sandbox.commands.run.assert_called_once()
