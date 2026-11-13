"""
Agent API endpoints — provisioner + auth only.

After the backend purge, the sandbox owns the entire run lifecycle end-to-end.
This module is thin: session handoff (``/sandbox/acquire`` + ``/sandbox/jwt-refresh``),
presence/typing heartbeats, conversation status/events reads from Postgres,
run feedback, desktop-stream URL minting, and the public shared-view read path.

Every run-scoped mutation (start, inject, cancel, branch, HITL respond, MCP
hot-add, file writes) now goes direct from the frontend to the sandbox with the
JWT returned by ``/sandbox/acquire`` — no backend involvement.
"""

import logging
from datetime import timedelta
from typing import Any, Optional

from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from apps.agents.db_events import get_events_for_conversation
from apps.agents.sandbox import (
    build_local_status_response,
    get_agent_server_url,
    get_conversation_for_user,
    get_or_resume_sandbox,
    get_shared_conversation,
    latest_run,
    mint_direct_stream_token,
    provision_sandbox_for_conversation,
)
from apps.storage.models import AgentRun, Conversation
from apps.users.adapters import AsyncTokenAuthentication
from config.errors.handlers import ErrorResponseSchema, register_error_handlers

logger = logging.getLogger(__name__)


agent_api = NinjaAPI(auth=AsyncTokenAuthentication(), urls_namespace="agents_api")
agent_public_api = NinjaAPI(urls_namespace="agents_public_api")

register_error_handlers(agent_api)
register_error_handlers(agent_public_api)


# =============================================================================
# SCHEMAS
# =============================================================================


ErrorResponse = ErrorResponseSchema


class AcquireSandboxRequest(Schema):
    """JSON body for POST /chat/sandbox/acquire.

    ``conversation_id`` is optional — omit it on the home page to let the backend
    mint a fresh conversation for the first message. ``prompt_preview`` is the
    user's draft message used only to generate a conversation title; it is NOT
    sent to the sandbox.
    """

    conversation_id: Optional[str] = None
    project_id: Optional[str] = None
    prompt_preview: Optional[str] = None


class AcquireSandboxResponse(Schema):
    """Response for POST /chat/sandbox/acquire and /chat/sandbox/jwt-refresh."""

    conversation_id: str
    sandbox_host: str
    jwt: str
    expires_at: str


class JwtRefreshRequest(Schema):
    """JSON body for POST /chat/sandbox/jwt-refresh — conversation_id required."""

    conversation_id: str


class AgentStatusResponse(Schema):
    """Response for GET /completions/{id}/status and /shared/{id}/status."""

    conversation_id: str
    on_going: bool = False
    has_error: bool = False
    error: Optional[str] = None
    requires_user_input: bool = False
    cancellation_requested: bool = False
    status: str
    run_id: Optional[str] = None
    task: Optional[str] = None
    sandbox_message: Optional[str] = None
    direct_stream_url: Optional[str] = None
    direct_stream_token: Optional[str] = None
    direct_stream_expires_at: Optional[str] = None
    rating: Optional[int] = None
    my_role: Optional[str] = None


class FeedbackRequest(Schema):
    rating: int


class FeedbackResponse(Schema):
    conversation_id: str
    rating: int


class EventsResponse(Schema):
    events: list
    has_more: bool = False
    status: Optional[str] = None
    oldest_sequence: Optional[int] = None
    newest_sequence: Optional[int] = None
    total_count: int = 0
    next_cursor: Optional[dict] = None
    sandbox_message: Optional[str] = None


class DesktopStreamResponse(Schema):
    available: bool
    stream_url: Optional[str] = None
    expires_at: Optional[str] = None
    reason: Optional[str] = None


class PresenceResponse(Schema):
    status: str
    present_users: list = []


class TypingRequest(Schema):
    action: str  # "start" or "stop"


class TypingResponse(Schema):
    status: str


def _error_response(
    status: int,
    error: str,
    error_code: str,
    detail: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Build a standardised error tuple matching the ErrorResponseSchema envelope."""
    return status, {
        "error": error,
        "error_code": error_code,
        "detail": detail,
        "status": status,
    }


# =============================================================================
# SESSION ACQUIRE — one-call handoff from backend to direct sandbox comms
# =============================================================================


async def _resolve_or_create_conversation_async(
    *,
    user,
    conversation_id: Optional[str],
    project_id: Optional[str],
    prompt_preview: Optional[str],
) -> tuple[Optional[Conversation], Optional[tuple[int, str, str]]]:
    """Async resolve-or-create for the acquire path.

    Returns ``(conv, error)``. The error tuple is ``(status, message, error_code)``
    that the caller should forward to ``_error_response``.
    """
    from apps.spaces.models import Project

    @sync_to_async
    def _inner():
        if conversation_id:
            try:
                conv = Conversation.objects.select_related("user", "project").get(
                    id=conversation_id
                )
            except Conversation.DoesNotExist:
                return None, (404, "Conversation not found", "NOT_FOUND")
            if conv.user_id != user.id:
                return None, (
                    403,
                    "Not authorised to access this conversation",
                    "FORBIDDEN",
                )
            return conv, None

        title = (prompt_preview or "New chat")[:512]
        create_kwargs: dict = {"user": user, "title": title}
        if project_id:
            try:
                project = Project.objects.get(id=project_id, user=user)
                create_kwargs["project"] = project
            except Project.DoesNotExist:
                return None, (404, "Project not found", "NOT_FOUND")
        return Conversation.objects.create(**create_kwargs), None

    return await _inner()


async def _build_acquire_response(
    *, conversation: Conversation, user
) -> tuple[int, dict[str, Any]]:
    """Provision (or connect to) a sandbox and mint a session JWT."""
    logger.info(
        "[ACQUIRE] provisioning sandbox user_id=%s conversation_id=%s project_id=%s",
        user.id,
        conversation.id,
        conversation.project_id,
    )
    try:
        _record, sandbox_host = await provision_sandbox_for_conversation(
            conversation, user
        )
    except HttpError as exc:
        logger.warning(
            "[ACQUIRE] provisioning failed user_id=%s conversation_id=%s status=%s msg=%s",
            user.id,
            conversation.id,
            exc.status_code,
            exc.message,
        )
        return _error_response(exc.status_code, exc.message, "PROVISION_FAILED")
    except Exception:
        logger.exception(
            "[ACQUIRE] provisioning crashed user_id=%s conversation_id=%s",
            user.id,
            conversation.id,
        )
        return _error_response(
            500, "Internal error while provisioning sandbox", "PROVISION_CRASHED"
        )

    token_data = mint_direct_stream_token(
        conversation=conversation,
        run=None,
        user_id=str(user.id),
    )
    if token_data is None:
        logger.error(
            "[ACQUIRE] JWT mint unavailable (SUKUNA_STREAM_JWT_SECRET unset?) user_id=%s conversation_id=%s",
            user.id,
            conversation.id,
        )
        return _error_response(
            503,
            "Direct sandbox streaming is not configured on this server",
            "JWT_UNAVAILABLE",
        )

    token, expires_at = token_data
    normalised_host = get_agent_server_url(sandbox_host)
    logger.info(
        "[ACQUIRE] ready user_id=%s conversation_id=%s sandbox_host=%s expires_at=%s",
        user.id,
        conversation.id,
        normalised_host,
        expires_at.isoformat(),
    )
    return 200, {
        "conversation_id": str(conversation.id),
        "sandbox_host": normalised_host,
        "jwt": token,
        "expires_at": expires_at.isoformat(),
    }


@agent_api.post(
    "/sandbox/acquire",
    response={
        200: AcquireSandboxResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        502: ErrorResponse,
        503: ErrorResponse,
    },
)
async def acquire_sandbox(request, data: AcquireSandboxRequest):
    """One-shot session handoff: resolve conversation, provision sandbox, mint JWT.

    This is the single backend call per chat session after the post-purge cutover.
    The frontend caches the returned ``{sandbox_host, jwt}`` pair and talks direct
    to the sandbox for every run-scoped operation until the JWT expires.
    """
    user = request.auth
    conversation, error = await _resolve_or_create_conversation_async(
        user=user,
        conversation_id=data.conversation_id,
        project_id=data.project_id,
        prompt_preview=data.prompt_preview,
    )
    if error is not None:
        return _error_response(*error)
    return await _build_acquire_response(conversation=conversation, user=user)


@agent_api.post(
    "/sandbox/jwt-refresh",
    response={
        200: AcquireSandboxResponse,
        403: ErrorResponse,
        404: ErrorResponse,
        502: ErrorResponse,
        503: ErrorResponse,
    },
)
async def refresh_sandbox_jwt(request, data: JwtRefreshRequest):
    """Re-mint a session JWT for an existing conversation.

    Functionally identical to ``acquire_sandbox`` today — ``provision_sandbox_for_conversation``
    is idempotent, so an already-healthy sandbox is just returned. Kept as a separate
    endpoint so the frontend's refresh logic is explicit about not wanting to create
    a new conversation when the JWT rolls over.
    """
    user = request.auth
    try:
        conversation = await get_conversation_for_user(data.conversation_id, user)
    except HttpError as exc:
        return _error_response(exc.status_code, exc.message, "NOT_FOUND")
    return await _build_acquire_response(conversation=conversation, user=user)


# =============================================================================
# STATUS + EVENTS (LOCAL POSTGRES READS)
# =============================================================================


@agent_api.get(
    "/completions/{conversation_id}/status",
    response={200: AgentStatusResponse, 404: ErrorResponse, 403: ErrorResponse},
)
async def get_agent_status(request, conversation_id: str):
    """Return run status from local DB only — no sandbox proxy.

    Clients poll this for UI badges while the SSE stream is the source of truth
    for live events. Clearing the one-shot ``sandbox_terminated`` flag stays
    backend-side because the flag itself is written by the backend's sandbox
    reaper.
    """
    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    run = await sync_to_async(lambda: conversation.current_task)()
    if run is None:
        run = await latest_run(conversation)

    sandbox_terminated = False
    conv_meta = await sync_to_async(lambda: conversation.metadata or {})()
    if conv_meta.get("sandbox_terminated"):
        sandbox_terminated = True

        @sync_to_async
        def _clear_flag():
            meta = conversation.metadata or {}
            meta.pop("sandbox_terminated", None)
            conversation.metadata = meta
            conversation.save(update_fields=["metadata"])

        await _clear_flag()

    sandbox_msg = (
        "Sandbox lost, will be reprovisioned on next message"
        if sandbox_terminated
        else None
    )
    return 200, await sync_to_async(build_local_status_response)(
        conversation, run, sandbox_message=sandbox_msg, user=user
    )


@agent_api.get(
    "/completions/{conversation_id}/events",
    response={200: EventsResponse, 404: ErrorResponse, 403: ErrorResponse},
)
async def get_run_events(
    request,
    conversation_id: str,
    before_sequence: int | None = None,
    before_created_at: str | None = None,
    before_run_id: str | None = None,
    limit: int = 50,
):
    """Get persisted events for a conversation — reads ``agent_events`` directly."""
    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    return 200, await get_events_for_conversation(
        str(conversation.id),
        before_sequence=before_sequence,
        before_created_at=before_created_at,
        before_run_id=before_run_id,
        limit=limit,
    )


@agent_api.get(
    "/completions/{conversation_id}/desktop-stream",
    response={200: DesktopStreamResponse, 404: ErrorResponse, 403: ErrorResponse},
)
async def get_desktop_stream(request, conversation_id: str):
    """Return an embeddable authenticated desktop stream URL."""
    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    try:
        sandbox_record, _sandbox_host = await get_or_resume_sandbox(
            conversation, user=user
        )
    except (HttpError, Exception):
        return 200, DesktopStreamResponse(available=False, reason="sandbox_unavailable")

    try:
        sandbox = await sync_to_async(sandbox_record.get_sandbox)(user=user)
        if sandbox is None:
            return 200, DesktopStreamResponse(
                available=False, reason="sandbox_unavailable"
            )

        stream = sandbox.stream
        try:
            stream.start(require_auth=True)
        except Exception as exc:
            if "already running" in str(exc).lower():
                try:
                    stream.stop()
                except Exception:
                    pass
                stream.start(require_auth=True)
            else:
                raise

        auth_key = stream.get_auth_key()
        stream_url = stream.get_url(
            auto_connect=True, view_only=False, resize="scale", auth_key=auth_key
        )
        ttl_seconds = int(
            getattr(settings, "SANDBOX_DESKTOP_STREAM_TTL_SECONDS", 120) or 120
        )
        expires_at = (timezone.now() + timedelta(seconds=ttl_seconds)).isoformat()
        await sync_to_async(sandbox_record.schedule_idle_pause)()
        return 200, DesktopStreamResponse(
            available=True, stream_url=stream_url, expires_at=expires_at, reason=None
        )
    except Exception:
        logger.warning(
            "[DESKTOP_STREAM] Failed to build desktop stream for conversation %s",
            conversation_id,
            exc_info=True,
        )
        return 200, DesktopStreamResponse(available=False, reason="stream_unavailable")


# =============================================================================
# FEEDBACK
# =============================================================================


@agent_api.post(
    "/completions/{conversation_id}/feedback",
    response={200: FeedbackResponse, 400: ErrorResponse, 404: ErrorResponse},
)
async def submit_run_feedback(request, conversation_id: str, data: FeedbackRequest):
    """Submit a 1-5 star rating for the latest terminal run in a conversation."""
    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    if data.rating < 1 or data.rating > 5:
        return _error_response(400, "Rating must be between 1 and 5", "INVALID_RATING")

    run = await latest_run(conversation)
    if run is None:
        return _error_response(404, "No runs found for this conversation", "NO_RUNS")

    if run.status not in AgentRun.TERMINAL_STATUSES:
        return _error_response(
            400,
            "Can only rate completed, failed, or cancelled runs",
            "RUN_NOT_TERMINAL",
        )

    run.rating = data.rating
    await sync_to_async(run.save)(update_fields=["rating", "updated_at"])

    return 200, FeedbackResponse(
        conversation_id=str(conversation.id), rating=data.rating
    )


# =============================================================================
# PRESENCE + TYPING
# =============================================================================


@agent_api.post(
    "/completions/{conversation_id}/presence",
    response={200: PresenceResponse, 403: ErrorResponse, 404: ErrorResponse},
)
async def presence_heartbeat(request, conversation_id: str):
    """Send a presence heartbeat. Updates TTL and returns current viewers."""
    import re

    from apps.agents.presence import get_present_users, heartbeat
    from apps.storage.models import conversation_can_view

    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    can_view = await sync_to_async(conversation_can_view)(conversation, user)
    if not can_view:
        return _error_response(403, "Access denied", "ACCESS_DENIED")

    display_name = await sync_to_async(lambda: user.name or user.email or "Unknown")()
    display_name = re.sub(r"[\[\]<>{}|\\]", "", display_name).strip() or "Unknown"
    avatar = await sync_to_async(lambda: getattr(user, "avatar", "") or "")()

    await sync_to_async(heartbeat)(
        str(conversation.id), str(user.id), display_name, avatar
    )

    present = await sync_to_async(get_present_users)(str(conversation.id))
    present_list = [
        {"user_id": p.user_id, "display_name": p.display_name, "avatar": p.avatar}
        for p in present
    ]

    return 200, {"status": "ok", "present_users": present_list}


@agent_api.post(
    "/completions/{conversation_id}/typing",
    response={200: TypingResponse, 403: ErrorResponse, 404: ErrorResponse},
)
async def typing_indicator(request, conversation_id: str, data: TypingRequest):
    """Broadcast a typing start/stop event."""
    from apps.agents.presence import set_typing
    from apps.storage.models import conversation_can_view

    user = request.auth
    conversation = await get_conversation_for_user(conversation_id, user)

    can_view = await sync_to_async(conversation_can_view)(conversation, user)
    if not can_view:
        return _error_response(403, "Access denied", "ACCESS_DENIED")

    if data.action not in ("start", "stop"):
        return _error_response(
            400, "Action must be 'start' or 'stop'", "INVALID_ACTION"
        )

    await sync_to_async(set_typing)(str(conversation.id), str(user.id), data.action)
    return 200, {"status": "ok"}


# =============================================================================
# PUBLIC (UNAUTHENTICATED) ENDPOINTS FOR SHARED CONVERSATIONS
# =============================================================================


@agent_public_api.get(
    "/shared/{conversation_id}/status",
    response={200: AgentStatusResponse, 404: ErrorResponse},
)
async def get_shared_agent_status(request, conversation_id: str):
    """Get run status for a shared conversation (no auth required)."""
    conversation = await get_shared_conversation(conversation_id)
    run = await sync_to_async(lambda: conversation.current_task)()
    if run is None:
        run = await latest_run(conversation)
    return 200, build_local_status_response(conversation, run)


@agent_public_api.get(
    "/shared/{conversation_id}/events",
    response={200: EventsResponse, 404: ErrorResponse},
)
async def get_shared_run_events(
    request,
    conversation_id: str,
    before_sequence: int | None = None,
    before_created_at: str | None = None,
    before_run_id: str | None = None,
    limit: int = 50,
):
    """Get persisted events for a shared conversation's run (no auth required)."""
    conversation = await get_shared_conversation(conversation_id)
    return 200, await get_events_for_conversation(
        str(conversation.id),
        before_sequence=before_sequence,
        before_created_at=before_created_at,
        before_run_id=before_run_id,
        limit=limit,
    )
