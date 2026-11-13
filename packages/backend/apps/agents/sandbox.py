"""
Sandbox provisioning + JWT mint — all that remains on the backend side.

Post-purge, the sandbox agent server owns the entire run lifecycle. This module
exposes:

- Conversation resolution helpers used by the ``/sandbox/acquire`` handoff and
  the surviving status/events/presence/typing views.
- Sandbox lifecycle glue: warm-pool claim, project-scoped provisioning, fresh
  E2B boot, health-check, pause/resume, "mark unhealthy" quarantine.
- ``mint_direct_stream_token`` / ``build_direct_stream_access`` for the single
  JWT the frontend carries through the whole session.

Anything that previously wrote run/billing/HITL state has moved to
``packages/sandbox/agent_server/``.
"""

import asyncio
import logging
import uuid
from datetime import timedelta
from typing import Any

import httpx
import jwt
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from ninja.errors import HttpError

from apps.agents.models import E2bSandbox
from apps.storage.models import AgentRun, Conversation

logger = logging.getLogger(__name__)

_logged_missing_direct_stream_secret = False

AGENT_SERVER_PORT = getattr(settings, "SANDBOX_AGENT_SERVER_PORT", 8000)


def get_agent_server_url(sandbox_host: str) -> str:
    """Build the base URL for the agent server (E2B sandbox or local)."""
    if sandbox_host.startswith("http://") or sandbox_host.startswith("https://"):
        return sandbox_host.rstrip("/")
    return f"https://{sandbox_host}"


# =============================================================================
# CONVERSATION HELPERS
# =============================================================================


async def get_conversation_for_user(
    conversation_id: str, user, for_update: bool = False
) -> Conversation:
    """Fetch conversation and verify ownership or participant access."""
    from apps.storage.models import conversation_can_view

    try:
        qs = Conversation.objects.select_related("user", "current_task")
        if for_update:
            qs = qs.select_for_update(of=("self",))
        conv = await sync_to_async(qs.get)(id=conversation_id)
    except Conversation.DoesNotExist:
        raise HttpError(404, "Conversation not found")
    has_access = await sync_to_async(conversation_can_view)(conv, user)
    if not has_access:
        raise HttpError(403, "Not authorised to access this conversation")
    return conv


async def get_shared_conversation(conversation_id: str) -> Conversation:
    """Fetch conversation and verify it is shared. Raises HttpError on failure."""
    try:
        conv = await sync_to_async(
            Conversation.objects.select_related("current_task").get
        )(id=conversation_id)
    except Conversation.DoesNotExist:
        raise HttpError(404, "Conversation not found")
    if not conv.share_settings or not conv.share_settings.get("shared"):
        raise HttpError(404, "Conversation is not shared")
    return conv


async def latest_run(conversation: Conversation):
    """Return the most recent AgentRun for a conversation, or None."""
    return await sync_to_async(
        lambda: AgentRun.objects.filter(conversation=conversation)
        .order_by("-created_at")
        .first()
    )()


def is_live_run(run: AgentRun | None) -> bool:
    """True when direct-sandbox SSE calls are valid for the run."""
    return bool(run and run.status == AgentRun.Status.RUNNING and run.run_id)


# =============================================================================
# PROJECT-SANDBOX HELPERS
# =============================================================================


async def _get_project_for_conversation(conversation: Conversation):
    """Return the project associated with a conversation, or None."""
    try:
        project = await sync_to_async(
            lambda: conversation.project if conversation.project_id else None,
            thread_sensitive=False,
        )()
        return project
    except Exception:
        return None


async def _get_project_sandbox_records(conversation: Conversation) -> list:
    """If conversation belongs to a project with a sandbox, return those records."""
    project = await _get_project_for_conversation(conversation)
    if project is None:
        return []
    records = await sync_to_async(list, thread_sensitive=False)(
        E2bSandbox.objects.active_for_project(project)[:5]
    )
    return records


def _link_sandbox_to_project(project, sandbox) -> None:
    """Link a sandbox to a project via the OneToOne field."""
    project.sandbox = sandbox
    project.save(update_fields=["sandbox"])


def _provision_project_sandbox_atomic(project):
    """Atomically check/provision a project sandbox using SELECT FOR UPDATE.

    Prevents double provisioning when two users start conversations in the same
    shared project simultaneously. Returns ``(sandbox_record, is_new)``.
    """
    from apps.spaces.models import Project

    with transaction.atomic():
        locked_project = Project.objects.select_for_update().get(pk=project.pk)
        existing = E2bSandbox.objects.active_for_project(locked_project).first()
        if existing is not None:
            return existing, False

        candidate = E2bSandbox.claim_from_pool_for_project(locked_project)
        if candidate is not None:
            return candidate, True

        record = E2bSandbox.objects.create(
            conversation=None,
            sandbox_state=E2bSandbox.SandboxState.CREATING,
        )
        locked_project.sandbox = record
        locked_project.save(update_fields=["sandbox"])
        return record, True


def has_active_project_runs(project) -> bool:
    """Return True if any conversation in the project has an active agent run.

    Used by the sandbox lifecycle manager to keep project sandboxes alive while
    any team member's conversation still has work in progress.
    """
    active_statuses = [
        AgentRun.Status.QUEUED,
        AgentRun.Status.PROVISIONING,
        AgentRun.Status.RUNNING,
    ]
    return AgentRun.objects.filter(
        conversation__project=project,
        status__in=active_statuses,
    ).exists()


def notify_project_sandbox_terminated(project) -> None:
    """Flag all active conversations in a project about sandbox termination.

    When a shared project sandbox is terminated (keep-alive failure), each
    conversation's metadata gains a ``sandbox_terminated`` flag. The status
    endpoint picks this up and clears the flag as it reports once to the user.
    """
    conversations = list(
        project.conversations.filter(is_deleted=False).exclude(
            current_task__isnull=True
        )
    )

    for conv in conversations:
        meta = conv.metadata or {}
        meta["sandbox_terminated"] = True
        conv.metadata = meta
        conv.save(update_fields=["metadata"])

    logger.info(
        "[SANDBOX] Flagged %d conversations for sandbox termination in project %s",
        len(conversations),
        project.id,
    )


async def _upload_project_files_to_sandbox(project, sandbox_record, sandbox) -> None:
    """Upload preloaded ProjectFiles to the sandbox on first creation."""
    from apps.spaces.models import ProjectFile

    project_files = await sync_to_async(list, thread_sensitive=False)(
        ProjectFile.objects.filter(project=project)
    )
    if not project_files:
        return

    for pf in project_files:
        try:
            file_content = await sync_to_async(pf.file.read, thread_sensitive=False)()
            target_path = pf.file_path or f"/home/user/workspace/{pf.filename}"
            sandbox.filesystem.write(target_path, file_content)
            logger.info(
                "[PROJECT] Uploaded file %s to %s in sandbox %s",
                pf.filename,
                target_path,
                sandbox_record.sandbox_id,
            )
        except Exception as e:
            logger.warning(
                "[PROJECT] Failed to upload file %s to sandbox %s: %s",
                pf.filename,
                sandbox_record.sandbox_id,
                e,
            )


# =============================================================================
# SANDBOX LIFECYCLE
# =============================================================================


async def get_or_resume_sandbox(
    conversation: Conversation, user=None
) -> tuple[E2bSandbox, str]:
    """Look up, resume if paused, and return (sandbox_record, host).

    Raises HttpError 404 if no sandbox exists or it is neither running nor paused.
    Raises HttpError 502 if a paused sandbox fails to resume.
    """
    if user is not None:
        local_url = await _get_local_sandbox_url(user)
        if local_url:
            record = await sync_to_async(
                lambda: E2bSandbox.objects.filter(
                    sandbox_id="local", conversation=conversation
                ).first()
            )()
            if record is not None:
                return record, local_url

    records = await _get_project_sandbox_records(conversation)
    if not records:
        records = await sync_to_async(list)(
            E2bSandbox.objects.active_for_conversation(conversation)[:5]
        )
    if not records:
        raise HttpError(404, "No active sandbox for this conversation")

    if len(records) > 1:
        logger.warning(
            "[SANDBOX] Multiple active records for conversation %s; using latest",
            conversation.id,
        )

    for candidate in records:
        if candidate.sandbox_state in (
            E2bSandbox.SandboxState.READY,
            E2bSandbox.SandboxState.PAUSED,
        ):
            try:
                if candidate.sandbox_state == E2bSandbox.SandboxState.PAUSED:
                    sandbox = await sync_to_async(candidate.resume_sandbox)()
                else:
                    sandbox = await sync_to_async(candidate.get_sandbox)()
            except Exception:
                sandbox = None

            if sandbox is None:
                await mark_sandbox_record_unhealthy(
                    candidate, "sandbox_connect_failed", terminate=True
                )
                continue

            host = sandbox.get_host(AGENT_SERVER_PORT)
            if not await wait_for_agent_server_health(host, timeout=5):
                await mark_sandbox_record_unhealthy(
                    candidate, "sandbox_healthcheck_failed", terminate=True
                )
                continue

            return candidate, host

    raise HttpError(502, "No healthy sandbox available for this conversation")


async def get_sandbox_host(conversation: Conversation, user=None) -> str:
    """Return the public hostname for the agent server in this conversation's sandbox."""
    _record, host = await get_or_resume_sandbox(conversation, user=user)
    return host


async def provision_sandbox_for_conversation(
    conversation: Conversation, user
) -> tuple[E2bSandbox, str]:
    """Ensure a healthy sandbox exists for ``conversation`` and return (record, host).

    Session-acquire entrypoint used by ``POST /api/v1/chat/sandbox/acquire``. Unlike
    :func:`get_or_resume_sandbox` (which raises 404 when nothing exists) this
    helper provisions a fresh sandbox when needed. Selection order mirrors the
    run-start path that used to live in the backend:

      1. Local mode (LOCAL_MODE / user-configured local sandbox URL)
      2. Existing project-scoped sandbox (READY or PAUSED) — resume if paused
      3. Existing conversation-scoped sandbox (READY or PAUSED) — resume if paused
      4. Claim a warm pool sandbox
      5. Create a fresh E2B sandbox
    """

    def to_thread(fn):
        return sync_to_async(fn, thread_sensitive=False)

    local_url = await _get_local_sandbox_url(user)
    if local_url:
        if not await wait_for_agent_server_health(local_url, timeout=5):
            raise HttpError(502, f"Local agent server at {local_url} is not reachable")
        sandbox_record = await to_thread(
            lambda: E2bSandbox.objects.filter(
                sandbox_id="local", conversation=conversation
            ).first()
        )()
        if sandbox_record is None:
            sandbox_record = await to_thread(E2bSandbox.objects.create)(
                sandbox_id="local",
                conversation=conversation,
                sandbox_state=E2bSandbox.SandboxState.READY,
            )
        return sandbox_record, local_url

    project = await _get_project_for_conversation(conversation)
    sandbox_record: E2bSandbox | None = None
    sandbox = None
    is_new_project_sandbox = False

    if project is not None:
        # Bounded retry — _provision_project_sandbox_atomic returns existing
        # (READY/PAUSED) project sandbox → pool-claim → fresh create in that
        # order. ERROR-marked records are excluded by ``active_for_project``,
        # so each iteration advances to the next stage automatically. At worst
        # we'll end up in the fresh-create branch, which does a full E2B boot.
        max_project_attempts = 3
        for attempt in range(max_project_attempts):
            sandbox_record, is_new_project_sandbox = await to_thread(
                _provision_project_sandbox_atomic
            )(project)
            if sandbox_record is None:
                break
            sandbox = await _connect_or_boot_async(sandbox_record, user)
            if sandbox is not None:
                break
            await mark_sandbox_record_unhealthy(
                sandbox_record,
                "acquire_project_sandbox_unreachable",
                terminate=True,
                skip_pause=bool(getattr(sandbox_record, "_last_connect_gone", False)),
            )
            sandbox_record = None
            if attempt == max_project_attempts - 1:
                logger.warning(
                    "[SANDBOX] Project %s sandbox provisioning failed after %d attempts",
                    project.id,
                    max_project_attempts,
                )
    else:
        sandbox_record = await to_thread(
            lambda: E2bSandbox.objects.active_for_conversation(conversation).first()
        )()
        if sandbox_record is not None:
            sandbox = await _connect_or_boot_async(sandbox_record, user)
            if sandbox is None:
                await mark_sandbox_record_unhealthy(
                    sandbox_record,
                    "acquire_existing_sandbox_unreachable",
                    terminate=True,
                    skip_pause=bool(
                        getattr(sandbox_record, "_last_connect_gone", False)
                    ),
                )
                sandbox_record = None

        # Bounded retry on pool: if the claimed sandbox is dead on E2B's side
        # (DB drift — common when Celery beat isn't running to rotate pool at
        # 50 min, so pool sandboxes age past E2B's 60 min hard timeout), try
        # the next pool peer instead of paying full boot latency immediately.
        if sandbox_record is None:
            max_pool_attempts = 3
            for attempt in range(max_pool_attempts):
                candidate = await to_thread(E2bSandbox.claim_from_pool)(conversation)
                if candidate is None:
                    break
                dispatch_pool_replenish()
                sandbox = await _connect_or_boot_async(candidate, user)
                if sandbox is not None:
                    sandbox_record = candidate
                    break
                await mark_sandbox_record_unhealthy(
                    candidate,
                    "acquire_pool_sandbox_unreachable",
                    terminate=True,
                    skip_pause=bool(getattr(candidate, "_last_connect_gone", False)),
                )
                if attempt == max_pool_attempts - 1:
                    logger.warning(
                        "[SANDBOX] Pool exhausted after %d dead sandboxes; falling back to fresh boot",
                        max_pool_attempts,
                    )

        if sandbox_record is None:
            sandbox_record = await to_thread(E2bSandbox.objects.create)(
                conversation=conversation,
                sandbox_state=E2bSandbox.SandboxState.CREATING,
            )
            sandbox = await _connect_or_boot_async(sandbox_record, user)

    if sandbox is None or sandbox_record is None:
        if sandbox_record is not None:
            await mark_sandbox_record_unhealthy(
                sandbox_record,
                "acquire_boot_failed",
                terminate=True,
                skip_pause=bool(getattr(sandbox_record, "_last_connect_gone", False)),
            )
        raise HttpError(502, "Failed to provision sandbox")

    sandbox_host = sandbox.get_host(AGENT_SERVER_PORT)
    if not await wait_for_agent_server_health(sandbox_host, timeout=45):
        await mark_sandbox_record_unhealthy(
            sandbox_record, "acquire_healthcheck_timeout", terminate=True
        )
        raise HttpError(502, "Agent server did not become healthy in time")

    if is_new_project_sandbox and project is not None:
        await _upload_project_files_to_sandbox(project, sandbox_record, sandbox)

    return sandbox_record, sandbox_host


async def _connect_or_boot_async(record, user):
    """Async wrapper around sandbox connect/resume/create.

    Uses thread_sensitive=False so these long-running E2B SDK calls don't block
    the main thread's single-threaded executor.
    """
    if record.sandbox_state == E2bSandbox.SandboxState.PAUSED:
        return await sync_to_async(record.resume_sandbox, thread_sensitive=False)(
            user=user
        )
    if record.sandbox_state == E2bSandbox.SandboxState.READY:
        return await sync_to_async(record.get_sandbox, thread_sensitive=False)(
            user=user
        )
    return await sync_to_async(record.create_sandbox, thread_sensitive=False)(user=user)


# =============================================================================
# LOCAL MODE HELPERS
# =============================================================================


async def _get_local_sandbox_url(user) -> str | None:
    """Return the user's local sandbox URL if local mode is enabled, else None."""
    from apps.users.models import UserSettings

    try:
        user_settings = await sync_to_async(
            UserSettings.objects.get, thread_sensitive=False
        )(user=user)
        if user_settings.local_mode and user_settings.local_sandbox_url:
            return user_settings.local_sandbox_url.rstrip("/")
    except UserSettings.DoesNotExist:
        pass
    return None


def dispatch_pool_replenish() -> None:
    """Best-effort async pool replenish trigger."""
    if getattr(settings, "SANDBOX_POOL_SIZE", 0) <= 0:
        return

    try:
        from apps.agents.tasks import replenish_sandbox_pool

        replenish_sandbox_pool.delay()
    except Exception as exc:
        logger.warning(f"[POOL] Could not dispatch replenish from view: {exc}")


async def mark_sandbox_record_unhealthy(
    record: E2bSandbox,
    reason: str,
    terminate: bool = True,
    skip_pause: bool = False,
) -> None:
    """Mark a specific sandbox record as unhealthy, pausing it if possible.

    Pass ``skip_pause=True`` when the caller has already learned the sandbox
    is gone on E2B (e.g. connect just returned 404) — avoids a redundant
    404 + full traceback from a doomed pause call.
    """

    @sync_to_async(thread_sensitive=False)
    def _mark():
        latest = E2bSandbox.objects.filter(pk=record.pk).first()
        if latest is None:
            return

        if terminate and not skip_pause and latest.sandbox_id:
            try:
                latest.pause_sandbox()
                return
            except Exception as exc:
                logger.warning(
                    "[SANDBOX] pause_sandbox failed for %s: %s",
                    latest.sandbox_id,
                    exc,
                )

        update_fields = []
        if latest.sandbox_state != E2bSandbox.SandboxState.ERROR:
            latest.sandbox_state = E2bSandbox.SandboxState.ERROR
            update_fields.append("sandbox_state")
        if latest.delayed_termination_at is not None:
            latest.delayed_termination_at = None
            update_fields.append("delayed_termination_at")
        if update_fields:
            latest.save(update_fields=[*update_fields, "date_updated"])

    logger.warning(
        "[SANDBOX] Marking sandbox %s unhealthy (%s)",
        record.sandbox_id or record.pk,
        reason,
    )
    await _mark()

    @sync_to_async(thread_sensitive=False)
    def _notify_project():
        try:
            project = record.project
        except Exception:
            return
        if project is not None:
            notify_project_sandbox_terminated(project)

    await _notify_project()


async def quarantine_conversation_sandbox(
    conversation: Conversation, reason: str, terminate: bool = True
) -> None:
    """Mark the active sandbox for a conversation as unhealthy and trigger pool replenish."""
    record = await sync_to_async(
        lambda: E2bSandbox.objects.active_for_conversation(conversation).first(),
        thread_sensitive=False,
    )()
    if record is None:
        return
    await mark_sandbox_record_unhealthy(record, reason, terminate=terminate)
    dispatch_pool_replenish()


async def wait_for_agent_server_health(sandbox_host: str, timeout: int = 30) -> bool:
    """Poll the agent server /health endpoint until it responds 200 or timeout."""
    url = f"{get_agent_server_url(sandbox_host)}/health"
    deadline = asyncio.get_event_loop().time() + timeout
    delay = 0.5
    async with httpx.AsyncClient(timeout=5.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url)
                if resp.status_code < 400:
                    return True
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 3.0)
    return False


async def set_conversation_error(conversation, error_msg: str) -> None:
    """Mark the current AgentRun as failed with the given error."""
    if conversation.current_task_id:
        try:
            task = await sync_to_async(AgentRun.objects.get)(
                pk=conversation.current_task_id
            )
            await sync_to_async(task.mark_failed)(error_msg)
        except AgentRun.DoesNotExist:
            pass


def _get_user_conversation_role(conversation, user) -> str | None:
    """Return the user's role in this conversation: 'creator', 'collaborator', 'viewer', or None."""
    if user is None:
        return None
    from apps.storage.models import ConversationParticipant

    try:
        participant = ConversationParticipant.objects.get(
            conversation=conversation, user=user
        )
        return participant.role
    except ConversationParticipant.DoesNotExist:
        if conversation.project_id:
            from apps.spaces.models import ProjectShare

            share = ProjectShare.objects.filter(
                project_id=conversation.project_id, user=user
            ).first()
            if share:
                perm = share.permission_level
                if perm == "admin" or perm == "collaborate":
                    return "collaborator"
                return "viewer"
    if conversation.user_id and conversation.user_id == user.id:
        return "creator"
    return None


def build_local_status_response(
    conversation,
    run=None,
    sandbox_message: str | None = None,
    direct_stream: dict[str, str] | None = None,
    user=None,
) -> dict:
    """Build status response from local DB state."""
    if run:
        status = "queued" if run.status == "pending" else run.status
    elif conversation.on_going:
        status = "running"
    elif conversation.has_error:
        status = "failed"
    else:
        status = "idle"

    response = {
        "conversation_id": str(conversation.id),
        "on_going": conversation.on_going,
        "has_error": conversation.has_error,
        "error": conversation.error,
        "requires_user_input": conversation.requires_user_input,
        "cancellation_requested": conversation.cancellation_requested,
        "status": status,
        "run_id": run.run_id if run else None,
        "task": run.task if run else None,
        "rating": run.rating if run else None,
    }
    if user is not None:
        response["my_role"] = _get_user_conversation_role(conversation, user)
    if sandbox_message:
        response["sandbox_message"] = sandbox_message
    if direct_stream:
        response.update(direct_stream)
    return response


# =============================================================================
# LEASE / JWT / DIRECT STREAM
# =============================================================================


def extract_lease_limits(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Extract lease limit fields from run metadata, applying setting defaults."""
    lease: dict[str, Any] = {}
    lease_from_metadata = metadata.get("lease") if isinstance(metadata, dict) else None

    if isinstance(lease_from_metadata, dict):
        for key in ("max_runtime_seconds", "max_total_tokens"):
            raw = lease_from_metadata.get(key)
            try:
                value = int(raw)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                lease[key] = value

        raw_cost = lease_from_metadata.get("max_cost_usd")
        try:
            cost_value = float(raw_cost)
        except (TypeError, ValueError):
            cost_value = 0.0
        if cost_value > 0:
            lease["max_cost_usd"] = cost_value

    if "max_runtime_seconds" not in lease:
        runtime_default = int(
            getattr(settings, "SANDBOX_STREAM_JWT_MAX_RUNTIME_SECONDS", 0) or 0
        )
        if runtime_default > 0:
            lease["max_runtime_seconds"] = runtime_default

    if "max_total_tokens" not in lease:
        tokens_default = int(
            getattr(settings, "SANDBOX_STREAM_JWT_MAX_TOTAL_TOKENS", 0) or 0
        )
        if tokens_default > 0:
            lease["max_total_tokens"] = tokens_default

    if "max_cost_usd" not in lease:
        try:
            cost_default = float(
                getattr(settings, "SANDBOX_STREAM_JWT_MAX_COST_USD", 0) or 0
            )
        except (TypeError, ValueError):
            cost_default = 0.0
        if cost_default > 0:
            lease["max_cost_usd"] = cost_default

    return lease


def mint_direct_stream_token(
    *,
    conversation: Conversation,
    run: AgentRun | None = None,
    user_id: str,
) -> tuple[str, Any] | None:
    """Mint a JWT token for direct sandbox access.

    When a ``run`` is supplied the token's ``sub`` claim is the run_id. When no
    run exists yet (session-acquire path) ``sub`` falls back to the conversation
    id so the token still passes the sandbox JWT require-list. Scopes are
    identical in both cases and cover the full per-route scope matrix.
    """
    secret = getattr(settings, "SUKUNA_STREAM_JWT_SECRET", "")
    if not secret:
        global _logged_missing_direct_stream_secret
        if not _logged_missing_direct_stream_secret:
            logger.error(
                "[SSE] SUKUNA_STREAM_JWT_SECRET is not configured; direct sandbox "
                "streaming cannot be authenticated. Set the secret in backend settings."
            )
            _logged_missing_direct_stream_secret = True
        return None

    if run is not None and not run.run_id:
        return None

    subject = run.run_id if run is not None else f"conv:{conversation.id}"

    now = timezone.now()
    ttl_seconds = max(
        30,
        int(getattr(settings, "SANDBOX_STREAM_JWT_TTL_SECONDS", 120) or 120),
    )
    expires_at = now + timedelta(seconds=ttl_seconds)
    claims: dict[str, Any] = {
        "iss": getattr(settings, "SANDBOX_STREAM_JWT_ISSUER", "sukuna-backend"),
        "aud": getattr(
            settings, "SANDBOX_STREAM_JWT_AUDIENCE", "sukuna-sandbox-stream"
        ),
        "sub": subject,
        "conversation_id": str(conversation.id),
        "user_id": str(user_id),
        "scope": ["stream:read", "run:admin", "hitl:respond", "mcp:manage", "files:rw"],
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": str(uuid.uuid4()),
    }

    if run is not None:
        lease_claims = extract_lease_limits(
            run.metadata if isinstance(run.metadata, dict) else {}
        )
        if lease_claims:
            claims.update(lease_claims)

    token = jwt.encode(
        claims,
        secret,
        algorithm=getattr(settings, "SANDBOX_STREAM_JWT_ALGORITHM", "HS256"),
    )
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token, expires_at


def build_direct_stream_access(
    *,
    conversation: Conversation,
    run: AgentRun | None,
    sandbox_host: str | None,
    user_id: str,
) -> dict[str, str] | None:
    """Build direct stream access credentials (URL + JWT) for a live run."""
    if not is_live_run(run) or not sandbox_host:
        return None

    token_data = mint_direct_stream_token(
        conversation=conversation,
        run=run,
        user_id=user_id,
    )
    if token_data is None:
        return None

    token, expires_at = token_data
    return {
        "direct_stream_url": f"{get_agent_server_url(sandbox_host)}/runs/{run.run_id}/stream",
        "direct_stream_token": token,
        "direct_stream_expires_at": expires_at.isoformat(),
    }
