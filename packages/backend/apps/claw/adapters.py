"""
Messaging platform abstraction layer for Claw mode.

Provides a shared interface for Telegram, Slack, and Discord integrations
so that routing, formatting, rate limiting, and command handling logic
is not duplicated across platforms.
"""

import logging
from abc import ABC, abstractmethod

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# =============================================================================
# ABSTRACT BASE CLASS
# =============================================================================


class MessagingPlatformAdapter(ABC):
    """Abstract base class for messaging platform integrations.

    Each concrete adapter handles the platform-specific details of sending
    messages, files, and formatting tool calls / errors. The shared routing,
    rate limiting, streaming, and command handling live outside the adapter
    and call into it through this interface.
    """

    platform_name: str = ""
    max_message_length: int = 4096

    @abstractmethod
    async def send_message(self, chat_id: str, text: str) -> None:
        """Send a text message to a chat/channel/DM.

        Long messages should be automatically chunked by the adapter.
        """

    @abstractmethod
    async def send_file(self, chat_id: str, file: bytes, filename: str) -> None:
        """Send a file to a chat/channel/DM."""

    def chunk_text(self, text: str, max_length: int | None = None) -> list[str]:
        """Split text into chunks of max_length, preferring semantic breaks."""
        limit = max_length or self.max_message_length
        if len(text) <= limit:
            return [text]

        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            # Prefer newline, then space, then hard cut
            split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = text.rfind(" ", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    def format_tool_call(self, tool_name: str, summary: str) -> str:
        """Format a tool call notification for this platform."""
        return f"[Tool: {tool_name}] {summary}"

    def format_error(self, error: str) -> str:
        """Format an error message for this platform."""
        return f"Error: {error}"


# =============================================================================
# TELEGRAM ADAPTER
# =============================================================================


class TelegramAdapter(MessagingPlatformAdapter):
    """Telegram-specific messaging adapter."""

    platform_name = "telegram"
    max_message_length = 4096

    async def send_message(self, chat_id: str, text: str) -> None:
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        chunks = self.chunk_text(text)
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={
                            "chat_id": int(chat_id),
                            "text": chunk,
                            "parse_mode": "Markdown",
                        },
                        timeout=10.0,
                    )
                except httpx.HTTPError:
                    try:
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": int(chat_id), "text": chunk},
                            timeout=10.0,
                        )
                    except httpx.HTTPError as e:
                        logger.error("Failed to send Telegram message: %s", e)

    async def send_file(self, chat_id: str, file: bytes, filename: str) -> None:
        token = getattr(settings, "TELEGRAM_BOT_TOKEN", None)
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not configured")
            return

        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendDocument",
                    data={"chat_id": int(chat_id)},
                    files={"document": (filename, file)},
                    timeout=30.0,
                )
            except httpx.HTTPError as e:
                logger.error("Failed to send Telegram file: %s", e)

    def format_tool_call(self, tool_name: str, summary: str) -> str:
        return f"🔧 *{tool_name}*\n{summary}"

    def format_error(self, error: str) -> str:
        return f"❌ *Error*: {error}"


# =============================================================================
# SLACK ADAPTER
# =============================================================================


class SlackAdapter(MessagingPlatformAdapter):
    """Slack-specific messaging adapter."""

    platform_name = "slack"
    max_message_length = 4000  # Slack block text limit

    async def send_message(self, chat_id: str, text: str) -> None:
        token = getattr(settings, "SLACK_BOT_TOKEN", None)
        if not token:
            logger.error("SLACK_BOT_TOKEN not configured")
            return

        chunks = self.chunk_text(text)
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                try:
                    await client.post(
                        "https://slack.com/api/chat.postMessage",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"channel": chat_id, "text": chunk},
                        timeout=10.0,
                    )
                except httpx.HTTPError as e:
                    logger.error("Failed to send Slack message: %s", e)

    async def send_file(self, chat_id: str, file: bytes, filename: str) -> None:
        token = getattr(settings, "SLACK_BOT_TOKEN", None)
        if not token:
            logger.error("SLACK_BOT_TOKEN not configured")
            return

        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    "https://slack.com/api/files.upload",
                    headers={"Authorization": f"Bearer {token}"},
                    data={"channels": chat_id, "filename": filename},
                    files={"file": (filename, file)},
                    timeout=30.0,
                )
            except httpx.HTTPError as e:
                logger.error("Failed to send Slack file: %s", e)

    def format_tool_call(self, tool_name: str, summary: str) -> str:
        return f":wrench: *{tool_name}*\n{summary}"

    def format_error(self, error: str) -> str:
        return f":x: *Error*: {error}"


# =============================================================================
# DISCORD ADAPTER
# =============================================================================


class DiscordAdapter(MessagingPlatformAdapter):
    """Discord-specific messaging adapter."""

    platform_name = "discord"
    max_message_length = 2000  # Discord message limit

    async def send_message(self, chat_id: str, text: str) -> None:
        token = getattr(settings, "DISCORD_BOT_TOKEN", None)
        if not token:
            logger.error("DISCORD_BOT_TOKEN not configured")
            return

        chunks = self.chunk_text(text)
        async with httpx.AsyncClient() as client:
            for chunk in chunks:
                try:
                    await client.post(
                        f"https://discord.com/api/v10/channels/{chat_id}/messages",
                        headers={"Authorization": f"Bot {token}"},
                        json={"content": chunk},
                        timeout=10.0,
                    )
                except httpx.HTTPError as e:
                    logger.error("Failed to send Discord message: %s", e)

    async def send_file(self, chat_id: str, file: bytes, filename: str) -> None:
        token = getattr(settings, "DISCORD_BOT_TOKEN", None)
        if not token:
            logger.error("DISCORD_BOT_TOKEN not configured")
            return

        async with httpx.AsyncClient() as client:
            try:
                await client.post(
                    f"https://discord.com/api/v10/channels/{chat_id}/messages",
                    headers={"Authorization": f"Bot {token}"},
                    files={"file": (filename, file)},
                    timeout=30.0,
                )
            except httpx.HTTPError as e:
                logger.error("Failed to send Discord file: %s", e)

    def format_tool_call(self, tool_name: str, summary: str) -> str:
        return f"**🔧 {tool_name}**\n{summary}"

    def format_error(self, error: str) -> str:
        return f"**❌ Error**: {error}"


# =============================================================================
# ADAPTER REGISTRY
# =============================================================================

_ADAPTERS: dict[str, type[MessagingPlatformAdapter]] = {
    "telegram": TelegramAdapter,
    "slack": SlackAdapter,
    "discord": DiscordAdapter,
}


def get_adapter(platform: str) -> MessagingPlatformAdapter:
    """Get an adapter instance for the given platform name.

    Raises:
        ValueError: If the platform is not supported.
    """
    cls = _ADAPTERS.get(platform)
    if cls is None:
        raise ValueError(
            f"Unsupported platform: {platform}. Supported: {list(_ADAPTERS.keys())}"
        )
    return cls()


# =============================================================================
# SHARED USER RESOLUTION
# =============================================================================


def resolve_user(platform: str, platform_user_id: str):
    """Look up a Jatayu AI User by platform-specific link.

    Args:
        platform: One of "telegram", "slack", "discord".
        platform_user_id: The platform-specific user identifier.

    Returns:
        The linked User object, or None if not found / inactive.
    """
    from apps.users.models import DiscordLink, SlackLink, TelegramLink

    try:
        if platform == "telegram":
            link = TelegramLink.objects.select_related("user").get(
                telegram_chat_id=int(platform_user_id), is_active=True
            )
            return link.user
        elif platform == "slack":
            link = SlackLink.objects.select_related("user").get(
                slack_user_id=platform_user_id, is_active=True
            )
            return link.user
        elif platform == "discord":
            link = DiscordLink.objects.select_related("user").get(
                discord_user_id=platform_user_id, is_active=True
            )
            return link.user
    except (
        TelegramLink.DoesNotExist,
        SlackLink.DoesNotExist,
        DiscordLink.DoesNotExist,
        ValueError,
    ):
        return None
    return None


# =============================================================================
# SHARED RATE LIMITING
# =============================================================================

RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60  # seconds


def rate_limit_check(user_id, platform: str) -> bool:
    """Check if a user has exceeded the messaging rate limit on a platform.

    Returns True if the user is rate-limited (should be rejected).
    """
    key = f"claw_rate:{platform}:{user_id}"
    count = cache.get(key, 0)
    if count >= RATE_LIMIT_MAX:
        return True
    cache.set(key, count + 1, timeout=RATE_LIMIT_WINDOW)
    return False


# =============================================================================
# SHARED RESPONSE STREAMING
# =============================================================================


# =============================================================================
# SHARED COMMAND ROUTING
# =============================================================================


class CommandRouter:
    """Platform-agnostic command router for messaging bot commands.

    Maps commands like /link, /unlink, /status, /new, /history to
    platform-agnostic handlers. Each handler receives the adapter,
    chat_id, and platform_user_id, and returns a response string.
    """

    def __init__(self, adapter: MessagingPlatformAdapter):
        self.adapter = adapter
        self._handlers: dict[str, object] = {
            "/link": self._cmd_link,
            "/unlink": self._cmd_unlink,
            "/status": self._cmd_status,
            "/new": self._cmd_new,
            "/history": self._cmd_history,
        }

    async def route(
        self, command: str, chat_id: str, platform_user_id: str, username: str = ""
    ) -> None:
        """Dispatch a command to its handler and send the response."""
        handler = self._handlers.get(command)
        if handler:
            response = await handler(chat_id, platform_user_id, username)
        else:
            commands = "\n".join(f"  {cmd}" for cmd in sorted(self._handlers.keys()))
            response = f"Unknown command. Available commands:\n{commands}"
        await self.adapter.send_message(chat_id, response)

    @property
    def supported_commands(self) -> list[str]:
        return list(self._handlers.keys())

    async def _cmd_link(
        self, chat_id: str, platform_user_id: str, username: str
    ) -> str:
        """Generate a linking token and instruct the user to authenticate."""
        import secrets as _secrets

        from asgiref.sync import sync_to_async

        platform = self.adapter.platform_name
        user = await sync_to_async(resolve_user)(platform, platform_user_id)
        if user is not None:
            return (
                f"Your {platform.title()} account is already linked to Jatayu AI. "
                "Send any message to interact with your persistent agent.\n\n"
                "Commands: /status /new /history /unlink"
            )

        token = _secrets.token_urlsafe(32)
        cache.set(
            f"{platform}_link:{token}",
            {
                "platform_user_id": platform_user_id,
                "chat_id": chat_id,
                "username": username,
            },
            timeout=600,
        )
        base_url = getattr(settings, "FRONTEND_URL", "https://app.midsphere.com")
        link_url = f"{base_url}/link-{platform}?token={token}"
        return (
            f"Welcome to Jatayu AI Claw Mode!\n\n"
            f"To link your {platform.title()} account, please authenticate here:\n{link_url}\n\n"
            f"This link expires in 10 minutes."
        )

    async def _cmd_unlink(
        self, chat_id: str, platform_user_id: str, username: str
    ) -> str:
        """Deactivate the platform link."""
        from asgiref.sync import sync_to_async

        from apps.compliance.models import AuditAction, AuditLog
        from apps.users.models import DiscordLink, SlackLink, TelegramLink

        platform = self.adapter.platform_name

        @sync_to_async
        def _do_unlink():
            link_models = {
                "telegram": (TelegramLink, "telegram_chat_id"),
                "slack": (SlackLink, "slack_user_id"),
                "discord": (DiscordLink, "discord_user_id"),
            }
            model_cls, id_field = link_models[platform]
            try:
                link = model_cls.objects.select_related("user").get(
                    **{id_field: platform_user_id, "is_active": True}
                )
            except model_cls.DoesNotExist:
                return False

            link.is_active = False
            link.save(update_fields=["is_active"])

            action = getattr(AuditAction, f"{platform.upper()}_UNLINKED", None)
            if action:
                AuditLog.log(
                    action=action,
                    resource_type=f"{platform}_link",
                    resource_id=str(link.pk),
                    actor_id=link.user.pk,
                    actor_email=link.user.email,
                    metadata={"chat_id": chat_id, "platform_user_id": platform_user_id},
                )
            return True

        unlinked = await _do_unlink()
        if unlinked:
            return f"Your {platform.title()} account has been unlinked from Jatayu AI. Use /link to re-link."
        return (
            f"No active {platform.title()} link found. Use /link to link your account."
        )

    async def _cmd_status(
        self, chat_id: str, platform_user_id: str, username: str
    ) -> str:
        """Return sandbox status and credit balance."""
        from asgiref.sync import sync_to_async

        platform = self.adapter.platform_name

        @sync_to_async
        def _get_status():
            user = resolve_user(platform, platform_user_id)
            if user is None:
                return None

            result = {"user": user.get_full_name()}
            # Post-purge: per-user persistent sandbox state moved to the sandbox
            # agent server; status endpoints on the adapter just report what
            # Django can still see directly.
            result["sandbox_active"] = False
            result["sandbox_state"] = "none"

            from apps.billing.models import CreditWallet

            try:
                wallet = CreditWallet.objects.get(user=user)
                result["credits"] = wallet.total_available
            except CreditWallet.DoesNotExist:
                result["credits"] = 0

            return result

        status = await _get_status()
        if not status:
            return f"No active {platform.title()} link. Use /link to link your account."

        return (
            f"Jatayu AI Status\n"
            f"User: {status['user']}\n"
            f"Sandbox: {'Active' if status['sandbox_active'] else 'Inactive'} ({status['sandbox_state']})\n"
            f"Credits: {status['credits']}"
        )

    async def _cmd_new(self, chat_id: str, platform_user_id: str, username: str) -> str:
        """Start a fresh conversation in the persistent sandbox."""
        from asgiref.sync import sync_to_async

        platform = self.adapter.platform_name

        @sync_to_async
        def _create_conversation():
            user = resolve_user(platform, platform_user_id)
            if user is None:
                return None

            from apps.storage.models import Conversation

            conv = Conversation.objects.create(
                user=user,
                title=f"{platform.title()} conversation",
                metadata={"claw_mode": True, platform: True},
            )
            return str(conv.id)

        conv_id = await _create_conversation()
        if not conv_id:
            return f"No active {platform.title()} link. Use /link to link your account."

        cache.set(f"{platform}_conv:{chat_id}", conv_id, timeout=None)
        return "New conversation started. Send your first message!"

    async def _cmd_history(
        self, chat_id: str, platform_user_id: str, username: str
    ) -> str:
        """List last 10 claw conversations with titles."""
        from asgiref.sync import sync_to_async

        platform = self.adapter.platform_name

        @sync_to_async
        def _get_history():
            user = resolve_user(platform, platform_user_id)
            if user is None:
                return None

            from apps.storage.models import Conversation

            convs = Conversation.objects.filter(
                user=user,
                metadata__claw_mode=True,
                is_deleted=False,
            ).order_by("-date_created")[:10]
            return [
                {
                    "id": str(c.id),
                    "title": c.title or "Untitled",
                    "date": c.date_created.strftime("%Y-%m-%d %H:%M"),
                }
                for c in convs
            ]

        history = await _get_history()
        if history is None:
            return f"No active {platform.title()} link. Use /link to link your account."
        if not history:
            return "No conversations yet. Use /new to start one."

        lines = ["Recent Conversations\n"]
        for i, conv in enumerate(history, 1):
            lines.append(
                f"{i}. {conv['title']}\n   {conv['date']} | {conv['id'][:8]}..."
            )
        return "\n".join(lines)
