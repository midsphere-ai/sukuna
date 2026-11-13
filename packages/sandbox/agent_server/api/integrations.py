"""Messaging integration webhooks — Telegram, Slack, and the Claw JSON API.

These endpoints used to live in the Django backend (``apps/agents/telegram_bot.py``,
``apps/agents/slack_bot.py``, ``apps/agents/claw_api.py``).  Under the new
architecture they run inline on the sandbox: external services post to the
per-user sandbox hostname and the run starts here without a proxy hop.

Auth:
- Telegram / Slack webhooks validate the platform signature (see
  ``TelegramSignatureAuth`` / ``SlackSignatureAuth`` in ``agent_server.auth``).
- Claw JSON endpoints validate the caller's bearer token or static API key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from functools import partial
from typing import Any

import httpx
from asgiref.sync import sync_to_async
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from ninja import Schema

from agent_server.auth import (
    BearerTokenAuth,
    SlackSignatureAuth,
    StaticAPIKeyAuth,
    TelegramSignatureAuth,
)
from agent_server.config import (
    AGENT_INSTRUCTIONS,
    AGENT_MAX_STEPS,
    AGENT_MODEL,
    EXTERNAL_MCP_CONFIGS,
)
from agent_server.engine.billing import (
    InsufficientCreditsError,
    create_hold,
)
from agent_server.infra import (
    RunNotifyChannel,
    _active_conversations,
    _run_agents,
    _run_channels,
    _run_tasks,
    integrations_router,
    registry,
)
from agent_server.infra.dlp import DLPBlockError, apply_dlp_scan
from agent_server.models import (
    DjangoAgentRun,
    DjangoConversation,
    DjangoSlackLink,
    DjangoTelegramLink,
    SandboxRun,
)

log = logging.getLogger("agent_server")

TELEGRAM_MAX_MESSAGE_LENGTH = 4096
SLACK_MAX_MESSAGE_LENGTH = 3000
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60  # seconds

_webhook_auth_telegram = [TelegramSignatureAuth()]
_webhook_auth_slack = [SlackSignatureAuth()]
_bearer_auth = [BearerTokenAuth(), StaticAPIKeyAuth()]


# ── Helpers shared by Telegram + Slack ───────────────────────────────────────


def _chunk_text(text: str, max_length: int) -> list[str]:
    """Split text into chunks of ``max_length``, preferring line/word breaks."""
    if len(text) <= max_length:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = text.rfind(" ", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _rate_limited(platform: str, key: str) -> bool:
    """Return True if the caller has exceeded the per-minute quota."""
    cache_key = f"msgrate:{platform}:{key}"
    count = cache.get(cache_key, 0)
    if count >= RATE_LIMIT_MAX:
        return True
    cache.set(cache_key, count + 1, timeout=RATE_LIMIT_WINDOW)
    return False


# ── Telegram send (outbound) ─────────────────────────────────────────────────


async def _send_telegram_message(chat_id: int, text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        log.error("TELEGRAM_BOT_TOKEN not configured")
        return
    async with httpx.AsyncClient() as client:
        for chunk in _chunk_text(text, TELEGRAM_MAX_MESSAGE_LENGTH):
            try:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"},
                    timeout=10.0,
                )
            except httpx.HTTPError:
                # Retry without Markdown on parse failures.
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": chat_id, "text": chunk},
                        timeout=10.0,
                    )
                except httpx.HTTPError as exc:
                    log.error("Failed to send Telegram message: %s", exc)


# ── Slack send (outbound) ────────────────────────────────────────────────────


async def _send_slack_message(
    channel: str,
    text: str,
    thread_ts: str | None = None,
    token: str | None = None,
) -> None:
    token = token or os.environ.get("SLACK_BOT_TOKEN", "")
    if not token:
        log.error("SLACK_BOT_TOKEN not configured")
        return
    async with httpx.AsyncClient() as client:
        for chunk in _chunk_text(text, SLACK_MAX_MESSAGE_LENGTH):
            payload: dict[str, Any] = {"channel": channel, "text": chunk}
            if thread_ts:
                payload["thread_ts"] = thread_ts
            try:
                await client.post(
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                    timeout=10.0,
                )
            except httpx.HTTPError as exc:
                log.error("Failed to send Slack message: %s", exc)


# ── Shared run-launch helper (DLP + SandboxRun + CreditHold + bg task) ───────


async def _launch_messaging_run(
    *,
    user_id: int,
    task: str,
    conversation_id: str | None,
    model: str | None,
    platform: str,
    conversation_metadata_seed: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Start an agent run on behalf of a resolved messaging-platform user.

    Returns ``(result, error_message)``.  ``result`` carries ``status``,
    ``run_id``, and ``conversation_id`` on success; ``error_message`` is a
    user-facing string when the run was rejected (e.g. DLP block, insufficient
    credits).  DB-side failures that are not user-actionable are logged and
    returned as a generic "temporary failure" message.
    """
    from agent_server.api.runs import _get_memory_store, _on_run_task_done
    from agent_server.engine.run import _run_agent

    # Resolve or create a claw-mode conversation scoped to this user.
    conv_info, conv_error = await _resolve_or_create_messaging_conv(
        user_id=user_id,
        task=task,
        conversation_id=conversation_id,
        platform=platform,
        metadata_seed=conversation_metadata_seed,
    )
    if conv_info is None:
        return None, conv_error
    resolved_conversation_id = conv_info["conversation_id"]

    # DLP scan: redact in place or block.
    try:
        scanned_task = await sync_to_async(apply_dlp_scan)(
            task,
            conversation_id=resolved_conversation_id,
            actor_id=user_id,
            actor_ip=None,
            request_id="",
        )
    except DLPBlockError as exc:
        return None, f"Your message was blocked by the DLP policy: {exc}"
    task = scanned_task

    # If the conversation already has an active run, inject instead of creating
    # a parallel one (matches HTTP start_run behaviour).
    active_run_id = _active_conversations.get(resolved_conversation_id)
    if active_run_id is not None:
        agent = _run_agents.get(active_run_id)
        if agent is not None:
            agent.inject_message(task)
            log.info(
                "[%s] Injected into active run %s (conversation %s)",
                platform,
                active_run_id,
                resolved_conversation_id,
            )
            return (
                {
                    "status": "message_injected",
                    "run_id": active_run_id,
                    "conversation_id": resolved_conversation_id,
                },
                None,
            )
        _active_conversations.pop(resolved_conversation_id, None)

    run_id = str(uuid.uuid4())
    resolved_model = model or AGENT_MODEL
    run_metadata = {
        "platform": platform,
        "claw_mode": True,
    }
    external_mcp_configs = list(EXTERNAL_MCP_CONFIGS)
    native_tools = registry.all_tools()

    await sync_to_async(SandboxRun.objects.create)(
        id=run_id,
        task=task,
        model=resolved_model,
        mcp_servers=[c.model_dump() for c in external_mcp_configs],
        metadata=run_metadata,
        user_id=str(user_id),
        session_id=None,
        conversation_id=resolved_conversation_id,
    )

    agent_run_pk = uuid.uuid4()
    now = timezone.now()
    try:
        await sync_to_async(DjangoAgentRun.objects.create)(
            id=agent_run_pk,
            run_id=run_id,
            conversation_id=resolved_conversation_id,
            user_id=user_id,
            task=task,
            status="running",
            model=resolved_model,
            metadata=run_metadata,
            created_at=now,
            started_at=now,
            updated_at=now,
        )
        try:
            await sync_to_async(create_hold)(user_id=user_id, agent_run_pk=agent_run_pk)
        except InsufficientCreditsError as exc:
            await sync_to_async(DjangoAgentRun.objects.filter(id=agent_run_pk).delete)()
            await sync_to_async(SandboxRun.objects.filter(id=run_id).delete)()
            return None, (
                f"Insufficient credits: need {exc.needed}, have {exc.available}. "
                "Purchase more credits or upgrade your plan."
            )
    except Exception:
        log.exception("[%s] failed to create AgentRun/CreditHold; aborting run %s", platform, run_id)
        await sync_to_async(SandboxRun.objects.filter(id=run_id).delete)()
        return None, "Temporary failure starting run. Please try again."

    channel = RunNotifyChannel()
    _run_channels[run_id] = channel
    memory_store = _get_memory_store()

    bg_task = asyncio.create_task(
        _run_agent(
            run_id=run_id,
            conversation_id=resolved_conversation_id,
            task=task,
            model=resolved_model,
            native_tools=native_tools,
            external_mcp_configs=external_mcp_configs or None,
            base_instructions=AGENT_INSTRUCTIONS,
            max_steps=AGENT_MAX_STEPS,
            user_id=str(user_id),
            session_id=None,
            channel=channel,
            memory_store=memory_store,
        ),
        name=f"run-{run_id}",
    )
    bg_task.add_done_callback(partial(_on_run_task_done, run_id))
    _run_tasks[run_id] = bg_task

    log.info(
        "[%s] Started run %s user=%d conversation=%s task=%r",
        platform,
        run_id,
        user_id,
        resolved_conversation_id,
        task[:80],
    )
    return (
        {
            "status": "running",
            "run_id": run_id,
            "conversation_id": resolved_conversation_id,
        },
        None,
    )


async def _resolve_or_create_messaging_conv(
    *,
    user_id: int,
    task: str,
    conversation_id: str | None,
    platform: str,
    metadata_seed: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetch an existing claw conversation or create one.  Returns (info, error)."""

    def _work() -> tuple[dict[str, Any] | None, str | None]:
        if conversation_id:
            conv = DjangoConversation.objects.filter(id=conversation_id, user_id=user_id, is_deleted=False).first()
            if conv is None:
                return None, "Conversation not found."
            conv_meta = conv.metadata or {}
            if not conv_meta.get("claw_mode"):
                return None, "Conversation is not a claw conversation."
            return {"conversation_id": str(conv.id)}, None

        base_meta = {"claw_mode": True, platform: True}
        if metadata_seed:
            base_meta.update(metadata_seed)
        title = (task or "").strip().splitlines()[0][:512] or f"{platform.title()} chat"
        now = timezone.now()
        conv = DjangoConversation.objects.create(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            metadata=base_meta,
            date_created=now,
            date_updated=now,
        )
        return {"conversation_id": str(conv.id)}, None

    return await sync_to_async(_work)()


# ════════════════════════════════════════════════════════════════════════════
#   TELEGRAM
# ════════════════════════════════════════════════════════════════════════════


@integrations_router.post("/integrations/telegram/webhook", auth=_webhook_auth_telegram)
async def telegram_webhook(request) -> HttpResponse:
    """Receive a Telegram update.  Signature validated by ``TelegramSignatureAuth``."""
    try:
        update = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = message.get("text", "")
    username = (message.get("from") or {}).get("username")
    if not chat_id or not text:
        return HttpResponse(status=200)

    if _rate_limited("telegram", str(chat_id)):
        await _send_telegram_message(
            chat_id,
            "Rate limit exceeded. Maximum 10 messages per minute.",
        )
        return HttpResponse(status=200)

    if text.startswith("/"):
        command = text.split()[0].split("@")[0].lower()
        await _telegram_dispatch_command(command, chat_id, username)
    else:
        await _telegram_handle_message(chat_id, text)
    return HttpResponse(status=200)


async def _telegram_dispatch_command(command: str, chat_id: int, username: str | None) -> None:
    handlers = {
        "/start": _telegram_cmd_start,
        "/stop": _telegram_cmd_stop,
        "/status": _telegram_cmd_status,
        "/new": _telegram_cmd_new,
    }
    handler = handlers.get(command)
    if handler:
        await handler(chat_id, username)
    else:
        await _send_telegram_message(
            chat_id,
            "Unknown command. Available: /start /stop /status /new",
        )


async def _telegram_cmd_start(chat_id: int, username: str | None) -> None:
    def _check() -> tuple[str, str | None]:
        try:
            link = DjangoTelegramLink.objects.get(telegram_chat_id=chat_id)
        except DjangoTelegramLink.DoesNotExist:
            import secrets

            token = secrets.token_urlsafe(32)
            cache.set(
                f"telegram_link:{token}",
                {"chat_id": chat_id, "username": username or ""},
                timeout=600,
            )
            return "pending", token
        if link.is_active:
            return "linked", None
        link.is_active = True
        link.save(update_fields=["is_active"])
        return "reactivated", None

    status, token = await sync_to_async(_check)()
    if status == "linked":
        await _send_telegram_message(
            chat_id,
            "Your Telegram account is already linked. Send any message to interact with your agent.",
        )
    elif status == "reactivated":
        await _send_telegram_message(chat_id, "Telegram account reactivated. Send a message to begin.")
    else:
        base_url = os.environ.get("FRONTEND_URL", "https://app.midsphere.com")
        link_url = f"{base_url}/link-telegram?token={token}"
        await _send_telegram_message(
            chat_id,
            f"Link your Telegram account here (expires in 10 minutes):\n{link_url}",
        )


async def _telegram_cmd_stop(chat_id: int, username: str | None) -> None:
    def _stop() -> bool:
        try:
            link = DjangoTelegramLink.objects.get(telegram_chat_id=chat_id, is_active=True)
        except DjangoTelegramLink.DoesNotExist:
            return False
        link.is_active = False
        link.save(update_fields=["is_active"])
        return True

    if await sync_to_async(_stop)():
        await _send_telegram_message(chat_id, "Telegram account unlinked. Use /start to re-link.")
    else:
        await _send_telegram_message(chat_id, "No active Telegram link found.")


async def _telegram_cmd_status(chat_id: int, username: str | None) -> None:
    def _status() -> dict[str, Any] | None:
        try:
            link = DjangoTelegramLink.objects.get(telegram_chat_id=chat_id, is_active=True)
        except DjangoTelegramLink.DoesNotExist:
            return None
        # Credit wallet lives in a shadow table; best-effort lookup.
        from agent_server.models import DjangoCreditWallet

        wallet = DjangoCreditWallet.objects.filter(user_id=link.user_id).first()
        total = 0
        if wallet:
            total = int(
                (wallet.monthly_credits_remaining or 0)
                + (wallet.addon_credits or 0)
                + (wallet.free_credits or 0)
                + (wallet.daily_credits_remaining or 0)
            )
        return {"user_id": link.user_id, "credits": total}

    result = await sync_to_async(_status)()
    if result is None:
        await _send_telegram_message(chat_id, "No active Telegram link. Use /start to link.")
        return
    await _send_telegram_message(
        chat_id,
        f"*Jatayu AI Status*\nUser ID: {result['user_id']}\nCredits: {result['credits']}",
    )


async def _telegram_cmd_new(chat_id: int, username: str | None) -> None:
    def _resolve() -> int | None:
        try:
            link = DjangoTelegramLink.objects.get(telegram_chat_id=chat_id, is_active=True)
        except DjangoTelegramLink.DoesNotExist:
            return None
        return link.user_id

    user_id = await sync_to_async(_resolve)()
    if user_id is None:
        await _send_telegram_message(chat_id, "No active Telegram link. Use /start to link.")
        return

    def _create() -> str:
        now = timezone.now()
        conv = DjangoConversation.objects.create(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title="Telegram conversation",
            metadata={"claw_mode": True, "telegram": True},
            date_created=now,
            date_updated=now,
        )
        return str(conv.id)

    conv_id = await sync_to_async(_create)()
    cache.set(f"telegram_conv:{chat_id}", conv_id, timeout=None)
    await _send_telegram_message(chat_id, "New conversation started. Send your first message!")


async def _telegram_handle_message(chat_id: int, text: str) -> None:
    def _resolve() -> int | None:
        try:
            link = DjangoTelegramLink.objects.get(telegram_chat_id=chat_id, is_active=True)
        except DjangoTelegramLink.DoesNotExist:
            return None
        return link.user_id

    user_id = await sync_to_async(_resolve)()
    if user_id is None:
        await _send_telegram_message(
            chat_id,
            "Your Telegram account is not linked. Use /start to link it first.",
        )
        return

    conv_id = cache.get(f"telegram_conv:{chat_id}")
    result, error = await _launch_messaging_run(
        user_id=user_id,
        task=text,
        conversation_id=conv_id,
        model=None,
        platform="telegram",
        conversation_metadata_seed={"telegram": True},
    )
    if result is None:
        await _send_telegram_message(chat_id, error or "Failed to start run.")
        return
    cache.set(f"telegram_conv:{chat_id}", result["conversation_id"], timeout=None)
    await _send_telegram_message(chat_id, "Processing your message...")


# ════════════════════════════════════════════════════════════════════════════
#   SLACK
# ════════════════════════════════════════════════════════════════════════════


def _strip_slack_mention(text: str) -> str:
    import re

    return re.sub(r"<@[A-Z0-9]+>\s*", "", text).strip()


@integrations_router.post("/integrations/slack/events", auth=_webhook_auth_slack)
async def slack_events_webhook(request) -> HttpResponse:
    """Slack Events API webhook.  Signature validated by ``SlackSignatureAuth``.

    Handles the URL-verification challenge and the main ``event_callback``
    envelope (``message`` DMs and ``app_mention`` channel mentions).
    """
    try:
        payload = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, ValueError):
        return HttpResponse(status=400)

    if payload.get("type") == "url_verification":
        return JsonResponse({"challenge": payload.get("challenge", "")})

    if payload.get("type") != "event_callback":
        return HttpResponse(status=200)

    event = payload.get("event") or {}
    # Ignore bot-originating messages to prevent echo loops.
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return HttpResponse(status=200)

    slack_user_id = event.get("user", "")
    channel = event.get("channel", "")
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    event_type = event.get("type")

    if not slack_user_id or not channel:
        return HttpResponse(status=200)

    if _rate_limited("slack", slack_user_id):
        await _send_slack_message(
            channel,
            "Rate limit exceeded. Maximum 10 messages per minute.",
            thread_ts=thread_ts,
        )
        return HttpResponse(status=200)

    if event_type == "message" and event.get("channel_type") == "im":
        await _slack_handle_message(channel, slack_user_id, text, thread_ts=None)
    elif event_type == "app_mention":
        await _slack_handle_message(
            channel,
            slack_user_id,
            _strip_slack_mention(text),
            thread_ts=thread_ts,
        )
    return HttpResponse(status=200)


@integrations_router.post("/integrations/slack/command", auth=_webhook_auth_slack)
async def slack_slash_webhook(request) -> JsonResponse:
    """Slack slash-command webhook (form-encoded body).

    Supports: ``/midsphere link|unlink|status|new``.
    """
    # Slash commands are form-encoded.
    post = getattr(request, "POST", None) or {}
    user_id = post.get("user_id", "")
    user_name = post.get("user_name", "")
    channel_id = post.get("channel_id", "")
    text = post.get("text", "").strip().lower()
    team_id = post.get("team_id", "")

    if not user_id:
        return JsonResponse({"response_type": "ephemeral", "text": "Missing user_id."}, status=400)

    if _rate_limited("slack", user_id):
        return JsonResponse(
            {
                "response_type": "ephemeral",
                "text": "Rate limit exceeded. Maximum 10 messages per minute.",
            }
        )

    subcommand = text.split()[0] if text else ""
    command = f"/{subcommand}" if subcommand else ""

    handlers = {
        "/link": _slack_cmd_link,
        "/unlink": _slack_cmd_unlink,
        "/status": _slack_cmd_status,
        "/new": _slack_cmd_new,
    }
    handler = handlers.get(command)
    if handler is None:
        return JsonResponse(
            {
                "response_type": "ephemeral",
                "text": (
                    "Available commands:\n"
                    "`/midsphere link` — link your Slack account\n"
                    "`/midsphere unlink` — unlink\n"
                    "`/midsphere status` — credit/sandbox status\n"
                    "`/midsphere new` — start a new conversation"
                ),
            }
        )
    response = await handler(channel_id, user_id, user_name, team_id)
    return JsonResponse({"response_type": "ephemeral", "text": response})


async def _slack_cmd_link(channel_id: str, user_id: str, username: str, team_id: str) -> str:
    def _check() -> str | None:
        return (
            DjangoSlackLink.objects.filter(slack_user_id=user_id, is_active=True)
            .values_list("user_id", flat=True)
            .first()
        )

    existing = await sync_to_async(_check)()
    if existing:
        return "Your Slack account is already linked to Jatayu AI. Send a DM to the bot to begin."

    import secrets

    token = secrets.token_urlsafe(32)
    cache.set(
        f"slack_link:{token}",
        {
            "platform_user_id": user_id,
            "chat_id": channel_id,
            "username": username,
            "team_id": team_id,
        },
        timeout=600,
    )
    base_url = os.environ.get("FRONTEND_URL", "https://app.midsphere.com")
    return f"Link your Slack account here (expires in 10 minutes):\n{base_url}/link-slack?token={token}"


async def _slack_cmd_unlink(channel_id: str, user_id: str, username: str, team_id: str) -> str:
    def _unlink() -> bool:
        try:
            link = DjangoSlackLink.objects.get(slack_user_id=user_id, is_active=True)
        except DjangoSlackLink.DoesNotExist:
            return False
        link.is_active = False
        link.save(update_fields=["is_active"])
        return True

    if await sync_to_async(_unlink)():
        return "Slack account unlinked. Use `/midsphere link` to re-link."
    return "No active Slack link found."


async def _slack_cmd_status(channel_id: str, user_id: str, username: str, team_id: str) -> str:
    def _status() -> dict[str, Any] | None:
        try:
            link = DjangoSlackLink.objects.get(slack_user_id=user_id, is_active=True)
        except DjangoSlackLink.DoesNotExist:
            return None
        from agent_server.models import DjangoCreditWallet

        wallet = DjangoCreditWallet.objects.filter(user_id=link.user_id).first()
        total = 0
        if wallet:
            total = int(
                (wallet.monthly_credits_remaining or 0)
                + (wallet.addon_credits or 0)
                + (wallet.free_credits or 0)
                + (wallet.daily_credits_remaining or 0)
            )
        return {"user_id": link.user_id, "credits": total}

    result = await sync_to_async(_status)()
    if result is None:
        return "No active Slack link. Use `/midsphere link` to link your account."
    return f"*Jatayu AI Status*\nUser ID: {result['user_id']}\nCredits: {result['credits']}"


async def _slack_cmd_new(channel_id: str, user_id: str, username: str, team_id: str) -> str:
    def _resolve_and_create() -> str | None:
        try:
            link = DjangoSlackLink.objects.get(slack_user_id=user_id, is_active=True)
        except DjangoSlackLink.DoesNotExist:
            return None
        now = timezone.now()
        conv = DjangoConversation.objects.create(
            id=str(uuid.uuid4()),
            user_id=link.user_id,
            title="Slack conversation",
            metadata={"claw_mode": True, "slack": True},
            date_created=now,
            date_updated=now,
        )
        return str(conv.id)

    conv_id = await sync_to_async(_resolve_and_create)()
    if conv_id is None:
        return "No active Slack link. Use `/midsphere link` to link your account."
    cache.set(f"slack_conv:{user_id}", conv_id, timeout=None)
    return "New conversation started. Send a DM to the bot with your first message!"


async def _slack_handle_message(channel: str, slack_user_id: str, text: str, *, thread_ts: str | None) -> None:
    def _resolve() -> int | None:
        try:
            link = DjangoSlackLink.objects.get(slack_user_id=slack_user_id, is_active=True)
        except DjangoSlackLink.DoesNotExist:
            return None
        return link.user_id

    user_id = await sync_to_async(_resolve)()
    if user_id is None:
        await _send_slack_message(
            channel,
            "Your Slack account is not linked. Use `/midsphere link` to link first.",
            thread_ts=thread_ts,
        )
        return

    conv_id = cache.get(f"slack_conv:{slack_user_id}")
    result, error = await _launch_messaging_run(
        user_id=user_id,
        task=text,
        conversation_id=conv_id,
        model=None,
        platform="slack",
        conversation_metadata_seed={"slack": True},
    )
    if result is None:
        await _send_slack_message(channel, error or "Failed to start run.", thread_ts=thread_ts)
        return
    cache.set(f"slack_conv:{slack_user_id}", result["conversation_id"], timeout=None)
    await _send_slack_message(channel, "Processing your message...", thread_ts=thread_ts)


# ════════════════════════════════════════════════════════════════════════════
#   CLAW JSON API  (bearer/API-key authenticated)
# ════════════════════════════════════════════════════════════════════════════


class ClawMessageRequest(Schema):
    prompt: str
    conversation_id: str | None = None
    model: str | None = None
    platform: str | None = None
    platform_user_id: str | None = None


class ClawMessageResponse(Schema):
    conversation_id: str
    run_id: str | None = None
    status: str
    message: str | None = None


class ClawConversationOut(Schema):
    id: str
    title: str
    created_at: str
    updated_at: str


def _resolve_auth_user_id(request) -> int | None:
    auth = getattr(request, "auth", None)
    if auth is None or auth == "api_key_user":
        return None
    user_id = getattr(auth, "id", None)
    return int(user_id) if user_id else None


@integrations_router.post(
    "/integrations/claw/message",
    auth=_bearer_auth,
    response={200: ClawMessageResponse, 400: dict, 402: dict, 404: dict},
)
async def claw_message(request, data: ClawMessageRequest):
    """Create/continue a claw conversation by posting a prompt."""
    user_id = _resolve_auth_user_id(request)
    if user_id is None:
        return 400, {"error": "User context required. Use bearer token auth."}

    result, error = await _launch_messaging_run(
        user_id=user_id,
        task=data.prompt,
        conversation_id=data.conversation_id,
        model=data.model,
        platform=(data.platform or "claw"),
        conversation_metadata_seed=({data.platform: True} if data.platform else None),
    )
    if result is None:
        # Map obvious credit / dlp errors to structured responses.
        lower = (error or "").lower()
        if "insufficient credits" in lower:
            return 402, {"error": error}
        if "not found" in lower:
            return 404, {"error": error}
        return 400, {"error": error or "Failed to start run."}

    return 200, ClawMessageResponse(
        conversation_id=result["conversation_id"],
        run_id=result["run_id"],
        status=result["status"],
        message="Agent run queued" if result["status"] == "running" else "Injected into active run",
    )


@integrations_router.get(
    "/integrations/claw/conversations",
    auth=_bearer_auth,
    response={200: list[ClawConversationOut]},
)
async def claw_conversations(request):
    """List the authenticated user's claw conversations (most recent 50)."""
    user_id = _resolve_auth_user_id(request)
    if user_id is None:
        return []

    def _list() -> list[ClawConversationOut]:
        qs = DjangoConversation.objects.filter(
            user_id=user_id,
            metadata__claw_mode=True,
            is_deleted=False,
        ).order_by("-date_created")[:50]
        return [
            ClawConversationOut(
                id=str(c.id),
                title=c.title or "",
                created_at=c.date_created.isoformat(),
                updated_at=c.date_updated.isoformat() if c.date_updated else c.date_created.isoformat(),
            )
            for c in qs
        ]

    return await sync_to_async(_list)()
