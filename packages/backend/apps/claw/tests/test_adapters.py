"""Tests for messaging platform abstraction layer — adapters, routing, rate limiting, commands."""

from unittest.mock import AsyncMock, patch

import pytest
from asgiref.sync import sync_to_async
from cryptography.fernet import Fernet
from django.core.cache import cache

from apps.claw.adapters import (
    RATE_LIMIT_MAX,
    CommandRouter,
    DiscordAdapter,
    MessagingPlatformAdapter,
    SlackAdapter,
    TelegramAdapter,
    get_adapter,
    rate_limit_check,
    resolve_user,
)
from apps.users.models import DiscordLink, SlackLink, TelegramLink
from apps.users.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return UserFactory()


# ===========================================================================
# ADAPTER ABC INTERFACE
# ===========================================================================


class TestMessagingPlatformAdapterABC:
    """Verify ABC contract and shared methods."""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            MessagingPlatformAdapter()

    def test_chunk_text_short(self):
        adapter = TelegramAdapter()
        result = adapter.chunk_text("hello")
        assert result == ["hello"]

    def test_chunk_text_splits_at_newline(self):
        adapter = TelegramAdapter()
        text = "a" * 4000 + "\n" + "b" * 100
        chunks = adapter.chunk_text(text, 4096)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 4000
        assert chunks[1] == "b" * 100

    def test_chunk_text_splits_at_space(self):
        adapter = TelegramAdapter()
        text = "word " * 1000  # ~5000 chars
        chunks = adapter.chunk_text(text, 100)
        assert all(len(c) <= 100 for c in chunks)

    def test_chunk_text_hard_cut(self):
        adapter = TelegramAdapter()
        text = "x" * 200
        chunks = adapter.chunk_text(text, 50)
        assert len(chunks) == 4
        assert all(len(c) == 50 for c in chunks)

    def test_format_tool_call_default(self):
        adapter = TelegramAdapter()
        result = adapter.format_tool_call("web_search", "Searching for info")
        assert "web_search" in result
        assert "Searching for info" in result

    def test_format_error_default(self):
        adapter = TelegramAdapter()
        result = adapter.format_error("Something went wrong")
        assert "Something went wrong" in result


# ===========================================================================
# CONCRETE ADAPTERS
# ===========================================================================


class TestTelegramAdapter:
    def test_platform_name(self):
        adapter = TelegramAdapter()
        assert adapter.platform_name == "telegram"
        assert adapter.max_message_length == 4096

    @pytest.mark.asyncio
    async def test_send_message_no_token(self, settings):
        settings.TELEGRAM_BOT_TOKEN = ""
        adapter = TelegramAdapter()
        # Should not raise — just logs error
        await adapter.send_message("123", "hello")

    @pytest.mark.asyncio
    async def test_send_message_with_token(self, settings):
        settings.TELEGRAM_BOT_TOKEN = "test-token"
        adapter = TelegramAdapter()
        with patch("apps.claw.adapters.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock()
            await adapter.send_message("123456", "hello world")
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "sendMessage" in call_args[0][0]
            assert call_args[1]["json"]["chat_id"] == 123456
            assert call_args[1]["json"]["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_send_file_no_token(self, settings):
        settings.TELEGRAM_BOT_TOKEN = ""
        adapter = TelegramAdapter()
        await adapter.send_file("123", b"data", "test.txt")

    def test_format_tool_call(self):
        adapter = TelegramAdapter()
        result = adapter.format_tool_call("shell", "Running ls -la")
        assert "shell" in result

    def test_format_error(self):
        adapter = TelegramAdapter()
        result = adapter.format_error("Timeout")
        assert "Timeout" in result


class TestSlackAdapter:
    def test_platform_name(self):
        adapter = SlackAdapter()
        assert adapter.platform_name == "slack"
        assert adapter.max_message_length == 4000

    @pytest.mark.asyncio
    async def test_send_message_no_token(self, settings):
        settings.SLACK_BOT_TOKEN = ""
        adapter = SlackAdapter()
        await adapter.send_message("C123", "hello")

    @pytest.mark.asyncio
    async def test_send_message_with_token(self, settings):
        settings.SLACK_BOT_TOKEN = "xoxb-test-token"
        adapter = SlackAdapter()
        with patch("apps.claw.adapters.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock()
            await adapter.send_message("C123", "hello slack")
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "chat.postMessage" in call_args[0][0]
            assert call_args[1]["json"]["channel"] == "C123"

    @pytest.mark.asyncio
    async def test_send_file_no_token(self, settings):
        settings.SLACK_BOT_TOKEN = ""
        adapter = SlackAdapter()
        await adapter.send_file("C123", b"data", "test.txt")

    def test_format_tool_call(self):
        adapter = SlackAdapter()
        result = adapter.format_tool_call("web_search", "Searching")
        assert ":wrench:" in result

    def test_format_error(self):
        adapter = SlackAdapter()
        result = adapter.format_error("Error occurred")
        assert ":x:" in result


class TestDiscordAdapter:
    def test_platform_name(self):
        adapter = DiscordAdapter()
        assert adapter.platform_name == "discord"
        assert adapter.max_message_length == 2000

    @pytest.mark.asyncio
    async def test_send_message_no_token(self, settings):
        settings.DISCORD_BOT_TOKEN = ""
        adapter = DiscordAdapter()
        await adapter.send_message("987654", "hello")

    @pytest.mark.asyncio
    async def test_send_message_with_token(self, settings):
        settings.DISCORD_BOT_TOKEN = "discord-test-token"
        adapter = DiscordAdapter()
        with patch("apps.claw.adapters.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock()
            await adapter.send_message("987654", "hello discord")
            mock_client.post.assert_called_once()
            call_args = mock_client.post.call_args
            assert "channels/987654/messages" in call_args[0][0]
            assert call_args[1]["json"]["content"] == "hello discord"

    @pytest.mark.asyncio
    async def test_send_file_no_token(self, settings):
        settings.DISCORD_BOT_TOKEN = ""
        adapter = DiscordAdapter()
        await adapter.send_file("987654", b"data", "test.txt")

    def test_format_tool_call(self):
        adapter = DiscordAdapter()
        result = adapter.format_tool_call("browser", "Opening page")
        assert "browser" in result

    def test_format_error(self):
        adapter = DiscordAdapter()
        result = adapter.format_error("Not found")
        assert "Not found" in result


# ===========================================================================
# ADAPTER REGISTRY
# ===========================================================================


class TestAdapterRegistry:
    def test_get_telegram(self):
        adapter = get_adapter("telegram")
        assert isinstance(adapter, TelegramAdapter)

    def test_get_slack(self):
        adapter = get_adapter("slack")
        assert isinstance(adapter, SlackAdapter)

    def test_get_discord(self):
        adapter = get_adapter("discord")
        assert isinstance(adapter, DiscordAdapter)

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_adapter("whatsapp")


# ===========================================================================
# SHARED USER RESOLUTION
# ===========================================================================


@pytest.mark.django_db
class TestResolveUser:
    def test_resolve_telegram_user(self, user):
        TelegramLink.objects.create(user=user, telegram_chat_id=111222, is_active=True)
        result = resolve_user("telegram", "111222")
        assert result == user

    def test_resolve_slack_user(self, user):
        SlackLink.objects.create(user=user, slack_user_id="U123ABC", is_active=True)
        result = resolve_user("slack", "U123ABC")
        assert result == user

    def test_resolve_discord_user(self, user):
        DiscordLink.objects.create(
            user=user, discord_user_id="99887766", is_active=True
        )
        result = resolve_user("discord", "99887766")
        assert result == user

    def test_resolve_inactive_returns_none(self, user):
        TelegramLink.objects.create(user=user, telegram_chat_id=111222, is_active=False)
        result = resolve_user("telegram", "111222")
        assert result is None

    def test_resolve_nonexistent_returns_none(self):
        result = resolve_user("telegram", "999999")
        assert result is None

    def test_resolve_unknown_platform_returns_none(self, user):
        result = resolve_user("whatsapp", "123")
        assert result is None

    def test_resolve_invalid_telegram_id_returns_none(self, user):
        result = resolve_user("telegram", "not_a_number")
        assert result is None


# ===========================================================================
# SHARED RATE LIMITING
# ===========================================================================


class TestRateLimiting:
    def test_first_message_not_limited(self):
        assert rate_limit_check(1, "telegram") is False

    def test_under_limit_not_limited(self):
        for _ in range(RATE_LIMIT_MAX - 1):
            rate_limit_check(1, "telegram")
        assert rate_limit_check(1, "telegram") is False

    def test_at_limit_is_limited(self):
        for _ in range(RATE_LIMIT_MAX):
            rate_limit_check(1, "telegram")
        assert rate_limit_check(1, "telegram") is True

    def test_different_platforms_separate_limits(self):
        for _ in range(RATE_LIMIT_MAX):
            rate_limit_check(1, "telegram")
        # Same user, different platform — not rate-limited
        assert rate_limit_check(1, "slack") is False

    def test_different_users_separate_limits(self):
        for _ in range(RATE_LIMIT_MAX):
            rate_limit_check(1, "telegram")
        # Different user, same platform — not rate-limited
        assert rate_limit_check(2, "telegram") is False


# ===========================================================================
# COMMAND ROUTER
# ===========================================================================


@pytest.mark.django_db(transaction=True)
class TestCommandRouter:
    @pytest.fixture
    def telegram_router(self):
        adapter = TelegramAdapter()
        adapter.send_message = AsyncMock()
        return CommandRouter(adapter)

    @pytest.fixture
    def slack_router(self):
        adapter = SlackAdapter()
        adapter.send_message = AsyncMock()
        return CommandRouter(adapter)

    def test_supported_commands(self, telegram_router):
        cmds = telegram_router.supported_commands
        assert "/link" in cmds
        assert "/unlink" in cmds
        assert "/status" in cmds
        assert "/new" in cmds
        assert "/history" in cmds

    @pytest.mark.asyncio
    async def test_unknown_command(self, telegram_router):
        await telegram_router.route("/foo", "123", "uid_1")
        telegram_router.adapter.send_message.assert_called_once()
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "Unknown command" in msg

    @pytest.mark.asyncio
    async def test_link_command_no_existing_link(self, telegram_router, settings):
        settings.FRONTEND_URL = "https://test.midsphere.com"
        await telegram_router.route("/link", "123", "999888")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "authenticate" in msg.lower() or "link" in msg.lower()
        assert "test.midsphere.com" in msg

    @pytest.mark.asyncio
    async def test_link_command_already_linked(self, telegram_router, user):
        await sync_to_async(TelegramLink.objects.create)(
            user=user, telegram_chat_id=999888, is_active=True
        )
        await telegram_router.route("/link", "123", "999888")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "already linked" in msg.lower()

    @pytest.mark.asyncio
    async def test_unlink_command_active_link(self, telegram_router, user):
        await sync_to_async(TelegramLink.objects.create)(
            user=user, telegram_chat_id=555666, is_active=True
        )
        await telegram_router.route("/unlink", "123", "555666")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "unlinked" in msg.lower()
        # Verify the link is now inactive
        link = await sync_to_async(TelegramLink.objects.get)(telegram_chat_id=555666)
        assert link.is_active is False

    @pytest.mark.asyncio
    async def test_unlink_command_no_link(self, telegram_router):
        await telegram_router.route("/unlink", "123", "999000")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "no active" in msg.lower()

    @pytest.mark.asyncio
    async def test_status_command_not_linked(self, telegram_router):
        await telegram_router.route("/status", "123", "999000")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "no active" in msg.lower() or "link" in msg.lower()

    @pytest.mark.asyncio
    async def test_new_command_creates_conversation(self, telegram_router, user):
        await sync_to_async(TelegramLink.objects.create)(
            user=user, telegram_chat_id=111222, is_active=True
        )
        await telegram_router.route("/new", "chat123", "111222")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "new conversation" in msg.lower()
        # Verify conv cached
        conv_id = cache.get("telegram_conv:chat123")
        assert conv_id is not None

    @pytest.mark.asyncio
    async def test_new_command_not_linked(self, telegram_router):
        await telegram_router.route("/new", "chat123", "999000")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "no active" in msg.lower()

    @pytest.mark.asyncio
    async def test_history_command_no_conversations(self, telegram_router, user):
        await sync_to_async(TelegramLink.objects.create)(
            user=user, telegram_chat_id=111222, is_active=True
        )
        await telegram_router.route("/history", "chat123", "111222")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "no conversations" in msg.lower()

    @pytest.mark.asyncio
    async def test_history_command_with_conversations(self, telegram_router, user):
        from apps.storage.models import Conversation

        await sync_to_async(TelegramLink.objects.create)(
            user=user, telegram_chat_id=111222, is_active=True
        )
        await sync_to_async(Conversation.objects.create)(
            user=user,
            title="Test conversation",
            metadata={"claw_mode": True},
        )
        await telegram_router.route("/history", "chat123", "111222")
        msg = telegram_router.adapter.send_message.call_args[0][1]
        assert "Test conversation" in msg

    @pytest.mark.asyncio
    async def test_slack_router_link_command(self, slack_router, settings):
        settings.FRONTEND_URL = "https://test.midsphere.com"
        await slack_router.route("/link", "C_CHANNEL", "U999")
        msg = slack_router.adapter.send_message.call_args[0][1]
        assert "Slack" in msg
        assert "link-slack" in msg

    @pytest.mark.asyncio
    async def test_cross_platform_unlink(self, user):
        """Test unlink across different platforms."""
        # Slack unlink
        await sync_to_async(SlackLink.objects.create)(
            user=user, slack_user_id="U_TEST", is_active=True
        )
        adapter = SlackAdapter()
        adapter.send_message = AsyncMock()
        router = CommandRouter(adapter)
        await router.route("/unlink", "C123", "U_TEST")
        msg = adapter.send_message.call_args[0][1]
        assert "unlinked" in msg.lower()
        link = await sync_to_async(SlackLink.objects.get)(slack_user_id="U_TEST")
        assert link.is_active is False

        # Discord unlink
        await sync_to_async(DiscordLink.objects.create)(
            user=user, discord_user_id="D_TEST", is_active=True
        )
        adapter = DiscordAdapter()
        adapter.send_message = AsyncMock()
        router = CommandRouter(adapter)
        await router.route("/unlink", "987", "D_TEST")
        msg = adapter.send_message.call_args[0][1]
        assert "unlinked" in msg.lower()
        link = await sync_to_async(DiscordLink.objects.get)(discord_user_id="D_TEST")
        assert link.is_active is False
