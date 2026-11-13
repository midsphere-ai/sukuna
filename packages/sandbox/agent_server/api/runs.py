"""Run management and SSE streaming endpoints.

POST /runs          -> start_run()     -- Start a new agent run
GET  /runs          -> list_runs()     -- List runs with pagination
GET  /runs/{id}     -> get_run()       -- Get run + all events
DELETE /runs/{id}   -> cancel_run()    -- Cancel an active run
POST /runs/{id}/branch -> branch_run() -- Branch conversation at message
POST /runs/{id}/inject -> inject_msg() -- Inject message into live run
POST /uploads       -> upload_file()   -- Upload a file to workspace
GET  /runs/{id}/stream        -> Authenticated SSE
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from functools import partial
from pathlib import Path as FilePath
from typing import Any

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.db.models import Max
from django.http import StreamingHttpResponse
from django.utils import timezone
from exo.memory.backends.postgres import PostgresMemoryStore
from ninja import Body, Schema
from ninja.errors import HttpError
from pydantic import Field

from agent_server.auth import require_scope
from agent_server.config import (
    AGENT_INSTRUCTIONS,
    AGENT_MAX_STEPS,
    AGENT_MODEL,
    EXTERNAL_MCP_CONFIGS,
    RUN_STREAM_KEEPALIVE_SECONDS,
    MCPServerConfig,
    _load_exo_md,
    _seed_agents_md,
)
from agent_server.engine.billing import (
    InsufficientCreditsError,
    create_hold,
)
from agent_server.infra import (
    _USER_SKILLS_DIR,
    RunNotifyChannel,
    _active_conversations,
    _generate_conversation_title_and_icon,
    _get_auth_user_id,
    _run_agents,
    _run_channels,
    _run_tasks,
    populate_skill_registry,
    registry,
    runs_router,
    streaming_router,
)
from agent_server.infra.dlp import DLPBlockError, apply_dlp_scan
from agent_server.infra.toolkit import (
    apply_agent_policy_to_metadata,
    resolve_toolkit_for_run,
)
from agent_server.models import (
    DjangoAgentRun,
    SandboxEvent,
    SandboxRun,
)

log = logging.getLogger("agent_server")

_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}


# ── Request / response schemas (Django Ninja uses Schema, not BaseModel) ──────


class StartRunRequest(Schema):
    task: str = Field(..., min_length=1)
    model: str | None = None
    instructions: str | None = None
    max_steps: int | None = None
    mcp_servers: list[MCPServerConfig] | None = None
    metadata: dict[str, Any] | None = None
    user_id: str | None = None
    session_id: str | None = None
    # Explicitly set conversation scope — all runs sharing the same
    # conversation_id see the same memory history.
    conversation_id: str | None = None
    # When set, the new run continues from the parent's memory context
    # (conversation branching).  The parent run must exist.
    parent_run_id: str | None = None


class BranchRequest(Schema):
    from_message_id: str


class InjectMessageRequest(Schema):
    message: str


# Django Ninja may build operation/query models while this module is still
# being imported. Force these body schemas to resolve postponed annotations
# now so Ninja never sees an incomplete forward ref.
StartRunRequest.model_rebuild(_types_namespace=globals())
BranchRequest.model_rebuild(_types_namespace=globals())
InjectMessageRequest.model_rebuild(_types_namespace=globals())


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_memory_store() -> PostgresMemoryStore:
    """Return the module-level memory store, raising if not initialized."""
    # Import at access time to get the current value of the mutable module-level
    # reference (it is set to a PostgresMemoryStore instance by init_server).
    import agent_server.infra as _core

    if _core._memory_store is None:
        raise HttpError(503, "Memory store not initialized — server is still starting up")
    return _core._memory_store


# ── DB query helpers ──────────────────────────────────────────────────────────


async def _fetch_events_after(
    run_id: str,
    after_seq: int,
    limit: int = 100,
) -> list[SandboxEvent]:
    """Fetch events with sequence > after_seq using keyset pagination (O(1))."""
    qs = SandboxEvent.objects.filter(run_id=run_id, sequence__gt=after_seq).order_by("sequence")[:limit]
    return await sync_to_async(list)(qs)


async def _get_run_status(run_id: str) -> str | None:
    """Return current SandboxRun.status, or None if the run no longer exists."""
    return await sync_to_async(lambda: SandboxRun.objects.filter(id=run_id).values_list("status", flat=True).first())()


async def _next_event_sequence(run_id: str) -> int:
    """Return the next monotonically increasing event sequence for a run."""
    max_seq = await sync_to_async(
        lambda: SandboxEvent.objects.filter(run_id=run_id).aggregate(max_seq=Max("sequence")).get("max_seq")
    )()
    return int(max_seq if max_seq is not None else -1) + 1


async def _mark_run_task_crashed(run_id: str, exc: BaseException) -> None:
    """Best-effort terminalization when a run task exits with an unhandled exception."""
    current_status = await _get_run_status(run_id)
    if current_status is None or current_status in _TERMINAL_RUN_STATUSES:
        return

    conversation_id = await sync_to_async(
        lambda: SandboxRun.objects.filter(id=run_id).values_list("conversation_id", flat=True).first()
    )()

    error_code = "run_task_crashed"
    error_message = f"Run task crashed unexpectedly: {exc.__class__.__name__}"
    now = timezone.now()
    await sync_to_async(SandboxRun.objects.filter(id=run_id).update)(
        status="failed",
        error=error_code,
        updated_at=now,
    )

    seq = await _next_event_sequence(run_id)
    payload = {
        "type": "run_failed",
        "run_id": run_id,
        "error": error_message,
        "error_code": error_code,
        "sequence": seq,
    }
    # Best-effort insert — if the main _emit loop already wrote this sequence
    # (race between cancel/crash and the agent loop), skip silently.  The run
    # is already marked failed in the DB; a missing event row is harmless.
    try:
        await sync_to_async(SandboxEvent.objects.create)(
            run_id=run_id,
            sequence=seq,
            event_type="run_failed",
            data=payload,
            data_raw=json.dumps(payload),
        )
    except IntegrityError:
        log.debug("Run %s: crash event seq=%d collided (harmless), skipping", run_id, seq)

    channel = _run_channels.get(run_id)
    if channel is not None:
        channel.notify(seq)
        channel.close()

    _run_agents.pop(run_id, None)
    if conversation_id and _active_conversations.get(conversation_id) == run_id:
        _active_conversations.pop(conversation_id, None)


def _on_run_task_done(run_id: str, task: asyncio.Task[None]) -> None:
    """Log task crashes and convert non-terminal runs into explicit run_failed events."""
    _run_tasks.pop(run_id, None)
    if task.cancelled():
        return

    exc = task.exception()
    if exc is None:
        return

    log.error(
        "Run %s: background task crashed with unhandled exception",
        run_id,
        exc_info=exc,
    )
    with suppress(RuntimeError):
        asyncio.create_task(
            _mark_run_task_crashed(run_id, exc),
            name=f"run-crash-{run_id}",
        )


def _extract_client_ip(request) -> str | None:
    """Best-effort client IP from the request (X-Forwarded-For first, then REMOTE_ADDR)."""
    meta = getattr(request, "META", None) or {}
    fwd = meta.get("HTTP_X_FORWARDED_FOR", "")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return meta.get("REMOTE_ADDR") or None


def _canonicalize_conversation_id(conversation_id: str | None) -> str | None:
    """Return a UUID-shaped conversation id for backend-owned tables.

    Local tools such as ``dev-run.sh`` historically passed human-readable ids
    like ``run-1776522553``. The backend-owned shadow models use UUID fields,
    so non-UUID ids must be normalized before any shared-DB ORM access.
    """
    if not conversation_id:
        return conversation_id
    try:
        return str(uuid.UUID(str(conversation_id)))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"sukuna-conversation:{conversation_id}"))


async def _scan_task_for_dlp(task: str, *, conversation_id: str, request) -> str:
    """Run the DLP scan on the task, returning redacted text or raising HttpError(400)."""
    actor_id = _get_auth_user_id(request)
    actor_ip = _extract_client_ip(request)
    request_id = getattr(request, "request_id", "") or ""
    try:
        return await sync_to_async(apply_dlp_scan)(
            task,
            conversation_id=conversation_id,
            actor_id=actor_id,
            actor_ip=actor_ip,
            request_id=request_id,
        )
    except DLPBlockError as exc:
        raise HttpError(400, str(exc)) from None


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 6 — RUN MANAGEMENT ENDPOINTS                                      ║
# ║                                                                            ║
# ║  POST /runs          → start_run()     — Start a new agent run            ║
# ║  GET  /runs          → list_runs()     — List runs with pagination         ║
# ║  GET  /runs/{id}     → get_run()       — Get run + all events              ║
# ║  DELETE /runs/{id}   → cancel_run()    — Cancel an active run              ║
# ║  POST /runs/{id}/branch → branch_run() — Branch conversation at message   ║
# ║  POST /runs/{id}/inject → inject_msg() — Inject message into live run     ║
# ║  POST /uploads       → upload_file()   — Upload a file to workspace       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@runs_router.post("/runs", response={201: dict})
@require_scope(["run:admin"])
async def start_run(request, body: StartRunRequest = Body(...)) -> tuple[int, dict[str, str]]:
    """Start a new agent run; returns run_id immediately.

    Pass ``parent_run_id`` to branch from an existing run: the new run shares
    the parent's conversation/memory context so the agent sees prior history.
    """
    # Import _run_agent here to avoid circular imports at module level.
    from agent_server.engine.run import _run_agent

    request_started_at = time.perf_counter()
    run_id = str(uuid.uuid4())

    model = body.model or AGENT_MODEL
    base_instructions = body.instructions or AGENT_INSTRUCTIONS
    max_steps = body.max_steps or AGENT_MAX_STEPS
    # External MCP servers: merge vault-configured (EXTERNAL_MCP_CONFIGS) with
    # per-request servers (body.mcp_servers).  Vault servers are available on
    # every run; per-request servers are one-off additions from the caller.
    external_mcp_configs = list(EXTERNAL_MCP_CONFIGS) + list(body.mcp_servers or [])

    # Extract user customisation preferences from metadata
    user_prefs = (body.metadata or {}).get("user_preferences") or {}
    provider_overrides: dict[str, dict] | None = user_prefs.get("provider_overrides") or None
    tool_toggles: dict[str, bool] = {}
    if user_prefs:
        tool_toggles = user_prefs.get("tool_toggles") or {}

    project_custom_instructions = (body.metadata or {}).get("custom_instructions", "").strip()

    # ── Project-scoped run metadata ─────────────────────────────────────────
    _meta_dict = body.metadata or {}
    project_id = _meta_dict.get("project_id")
    project_title = (_meta_dict.get("project_title") or "").strip()
    project_files = _meta_dict.get("project_files") or []
    if not isinstance(project_files, list):
        project_files = []
    is_project_run = bool(project_id)

    # Derive conversation_id for memory scoping (priority: parent > explicit > new).
    if body.parent_run_id is not None:
        parent = await sync_to_async(SandboxRun.objects.filter(id=body.parent_run_id).first)()
        if parent is None:
            raise HttpError(404, f"Parent run {body.parent_run_id} not found")
        # Use the parent's stored conversation_id so the whole branch tree
        # shares one memory scope regardless of nesting depth.
        conversation_id = parent.conversation_id or body.parent_run_id
        # Branch runs may be started without re-sending the project_* keys
        # (the frontend only sends them on the first /runs call in a
        # conversation).  Fall back to the parent run's stored metadata so
        # the branch inherits the project context.
        _parent_meta = parent.metadata if isinstance(parent.metadata, dict) else {}
        if not project_id and _parent_meta.get("project_id"):
            project_id = _parent_meta.get("project_id")
            is_project_run = True
        if not project_title and _parent_meta.get("project_title"):
            project_title = str(_parent_meta.get("project_title") or "").strip()
        if not project_files and isinstance(_parent_meta.get("project_files"), list):
            project_files = _parent_meta.get("project_files") or []
        if not project_custom_instructions and _parent_meta.get("custom_instructions"):
            project_custom_instructions = str(_parent_meta.get("custom_instructions") or "").strip()
    elif body.conversation_id:
        conversation_id = _canonicalize_conversation_id(body.conversation_id)
    else:
        conversation_id = run_id

    # ── DLP scan (before anything downstream sees the raw prompt) ───────────
    # Returns the (possibly redacted) task; raises HttpError(400) on block.
    scanned_task = await _scan_task_for_dlp(
        body.task,
        conversation_id=conversation_id,
        request=request,
    )
    if scanned_task != body.task:
        body.task = scanned_task

    # If this conversation already has a running agent, inject the user's
    # message into that run instead of spawning a parallel one.
    active_run_id = _active_conversations.get(conversation_id)
    if active_run_id is not None:
        agent = _run_agents.get(active_run_id)
        if agent is not None:
            agent.inject_message(body.task)
            log.info(
                "Injected message into active run %s (conversation %s): %r",
                active_run_id,
                conversation_id,
                body.task[:80],
            )
            return 200, {
                "run_id": active_run_id,
                "status": "message_injected",
                "conversation_id": conversation_id,
            }
        # Agent reference gone (race) — fall through and create a new run.
        _active_conversations.pop(conversation_id, None)

    # ── Resolve the run's toolkit from shared Postgres ───────────────────────
    # If the caller (frontend direct-to-sandbox) didn't pre-resolve installed
    # skills, materialize them here from the user's + project's shadow ORM
    # rows.  Mirrors the resolution the backend used to do in
    # ``apps/agents/sandbox.py:start_run_directly`` pre-purge.
    if (body.metadata or {}).get("installed_skills") is None:
        _jwt_user_id = _get_auth_user_id(request)
        _resolver_user_id = _jwt_user_id or body.user_id
        if _resolver_user_id:
            try:
                _meta = body.metadata if isinstance(body.metadata, dict) else {}
                _resolved = await resolve_toolkit_for_run(
                    user_id=int(_resolver_user_id),
                    project_id=project_id,
                    selected_skill_slugs=list(_meta.get("skill_ids") or []),
                    user_addon_ids=list(_meta.get("addons") or []),
                )
                body.metadata = {
                    **(_meta),
                    "installed_skills": _resolved["installed_skills"],
                    "project_mcp_configs": _resolved["project_mcp_configs"],
                    "addon_credit_tiers": _resolved["addon_credit_tiers"],
                    "addons": _resolved["addon_ids"],
                }
                body.metadata = await apply_agent_policy_to_metadata(body.metadata, project_id=project_id)
            except Exception:
                log.exception(
                    "Run %s: toolkit resolver failed (continuing with empty toolkit)",
                    run_id,
                )

    # ── Provision installed marketplace skills ──────────────────────────────
    # Write skill.md files from metadata into the user skills directory so
    # the SkillRegistry picks them up.
    _installed_skills = (body.metadata or {}).get("installed_skills") or []
    if _installed_skills:
        _user_skills_root = FilePath(_USER_SKILLS_DIR)
        _provisioned = 0
        for _sk in _installed_skills:
            _slug = _sk.get("slug", "")
            _content = _sk.get("skill_md_content", "")
            if not _slug or not _content:
                continue
            _skill_dir = _user_skills_root / _slug
            _skill_file = _skill_dir / "skill.md"
            if not _skill_file.exists():
                _skill_dir.mkdir(parents=True, exist_ok=True)
                _skill_file.write_text(_content, encoding="utf-8")
                _provisioned += 1
        if _provisioned:
            log.info("Provisioned %d marketplace skills into %s", _provisioned, _USER_SKILLS_DIR)
            # Reload the skill registry to pick up new skills
            populate_skill_registry()

    # ── EXO.md project context (first message of a new conversation only) ────
    run_metadata = dict(body.metadata or {})
    is_branch = body.parent_run_id is not None
    is_new_conversation = (body.metadata or {}).get("is_new_conversation") or (conversation_id == run_id)
    exo_md_content: str | None = None
    if not is_branch and is_new_conversation:
        exo_md_content, exo_md_truncated = _load_exo_md()
        if exo_md_content:
            run_metadata["exo_md"] = {
                "loaded": True,
                "size": len(exo_md_content.encode("utf-8")),
                "truncated": exo_md_truncated,
            }
            log.info(
                "Run %s: loaded EXO.md (%d bytes, truncated=%s)",
                run_id,
                run_metadata["exo_md"]["size"],
                exo_md_truncated,
            )

    # ── Seed AGENTS.md for project-scoped runs (idempotent, race-safe) ──────
    if is_project_run:
        _seeded = _seed_agents_md(
            project_title=project_title,
            project_custom_instructions=project_custom_instructions,
            project_files=project_files,
        )
        run_metadata["agents_md_seeded"] = _seeded

    should_generate_title = not is_branch and is_new_conversation

    # Resolve native tools from registry, filtered by user toggle preferences.
    native_tools = registry.get_tools_for_toggles(tool_toggles) if tool_toggles else registry.all_tools()

    await sync_to_async(SandboxRun.objects.create)(
        id=run_id,
        task=body.task,
        model=model,
        mcp_servers=[c.model_dump() for c in external_mcp_configs],
        metadata=run_metadata,
        user_id=body.user_id,
        session_id=body.session_id,
        parent_run_id=body.parent_run_id,
        conversation_id=conversation_id,
    )

    # Create the backend-visible DjangoAgentRun row and its credit hold.
    # Both are in the shared Postgres; no backend RPC involved.
    agent_run_pk: uuid.UUID | None = None
    try:
        jwt_user_id = _get_auth_user_id(request)
        owner_id = jwt_user_id or body.user_id
        if owner_id:
            now = timezone.now()
            agent_run_pk = uuid.uuid4()
            await sync_to_async(DjangoAgentRun.objects.create)(
                id=agent_run_pk,
                run_id=run_id,
                conversation_id=conversation_id,
                user_id=int(owner_id),
                task=body.task,
                status="running",
                model=model,
                metadata=run_metadata,
                created_at=now,
                started_at=now,
                updated_at=now,
            )
            try:
                await sync_to_async(create_hold)(
                    user_id=int(owner_id),
                    agent_run_pk=agent_run_pk,
                )
            except InsufficientCreditsError as exc:
                # Roll back the AgentRun + SandboxRun rows before refusing.
                await sync_to_async(DjangoAgentRun.objects.filter(id=agent_run_pk).delete)()
                await sync_to_async(SandboxRun.objects.filter(id=run_id).delete)()
                raise HttpError(402, f"Insufficient credits: need {exc.needed}, have {exc.available}") from None
    except HttpError:
        raise
    except Exception:
        log.exception("Run %s: failed to create AgentRun / CreditHold (continuing)", run_id)

    channel = RunNotifyChannel()
    _run_channels[run_id] = channel

    memory_store = _get_memory_store()

    bg_task = asyncio.create_task(
        _run_agent(
            run_id=run_id,
            conversation_id=conversation_id,
            task=body.task,
            model=model,
            native_tools=native_tools,
            external_mcp_configs=external_mcp_configs or None,
            base_instructions=base_instructions,
            max_steps=max_steps,
            user_id=body.user_id,
            session_id=body.session_id,
            channel=channel,
            memory_store=memory_store,
            tool_toggles=tool_toggles or None,
            provider_overrides=provider_overrides,
            user_prefs=user_prefs or None,
            project_custom_instructions=project_custom_instructions or None,
            exo_md_content=exo_md_content,
            project_id=project_id,
            project_title=project_title,
            project_files=project_files,
        ),
        name=f"run-{run_id}",
    )
    bg_task.add_done_callback(partial(_on_run_task_done, run_id))
    _run_tasks[run_id] = bg_task

    # Generate title for brand-new conversations (fire-and-forget).
    # Spawn this only after run/channel/task registration so any title-model
    # latency cannot interfere with live run bookkeeping.
    if should_generate_title:
        log.info("Run %s: spawning title generation for new conversation %s", run_id, conversation_id)
        asyncio.create_task(
            _generate_conversation_title_and_icon(conversation_id, body.task),
            name=f"title-gen-{conversation_id}",
        )

    log.info(
        "Started run %s model=%s conversation=%s native_tools=%d external_mcp=%d request=%.3fs task=%r",
        run_id,
        model,
        conversation_id,
        len(native_tools),
        len(external_mcp_configs),
        time.perf_counter() - request_started_at,
        body.task[:80],
    )
    return 201, {"run_id": run_id, "status": "running", "conversation_id": conversation_id}


@runs_router.get("/runs")
@require_scope(["stream:read"])
async def list_runs(
    request,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List agent runs with optional status filter and pagination."""
    qs = SandboxRun.objects.all()
    # Scope to authenticated user (bearer token only — API key = proxy = no filter)
    auth_user_id = _get_auth_user_id(request)
    if auth_user_id:
        qs = qs.filter(user_id=auth_user_id)
    if status is not None:
        qs = qs.filter(status=status)

    total = await sync_to_async(qs.count)()

    runs_qs = qs.order_by("-created_at")[offset : offset + limit]
    runs = await sync_to_async(list)(runs_qs)

    return {
        "runs": [
            {
                "run_id": r.id,
                "task": r.task,
                "status": r.status,
                "model": r.model,
                "user_id": r.user_id,
                "session_id": r.session_id,
                "parent_run_id": r.parent_run_id,
                "conversation_id": r.conversation_id or r.parent_run_id or r.id,
                "created_at": r.created_at.isoformat(),
                "updated_at": r.updated_at.isoformat(),
            }
            for r in runs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@runs_router.get("/runs/{run_id}")
@require_scope(["stream:read"])
async def get_run(request, run_id: str) -> dict[str, Any]:
    """Return the run record and all persisted events."""
    qs = SandboxRun.objects.filter(id=run_id)
    auth_user_id = _get_auth_user_id(request)
    if auth_user_id:
        qs = qs.filter(user_id=auth_user_id)
    agent_run = await sync_to_async(qs.first)()
    if agent_run is None:
        raise HttpError(404, f"Run {run_id} not found")

    events = await sync_to_async(list)(SandboxEvent.objects.filter(run_id=run_id).order_by("sequence"))

    return {
        "run_id": run_id,
        "task": agent_run.task,
        "status": agent_run.status,
        "model": agent_run.model,
        "user_id": agent_run.user_id,
        "session_id": agent_run.session_id,
        "parent_run_id": agent_run.parent_run_id,
        "conversation_id": agent_run.conversation_id or agent_run.parent_run_id or run_id,
        "error": agent_run.error,
        "created_at": agent_run.created_at.isoformat(),
        "updated_at": agent_run.updated_at.isoformat(),
        "events": [
            {
                "sequence": e.sequence,
                "type": e.event_type,
                "data": e.data,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


@runs_router.delete("/runs/{run_id}")
@require_scope(["run:admin"])
async def cancel_run(request, run_id: str) -> dict[str, str]:
    """Cancel a running agent task.

    Returns 204-equivalent response on success.  If the run has no active
    asyncio task (e.g. server was restarted), marks it cancelled in the DB
    so it doesn't remain stuck forever.
    """
    task = _run_tasks.get(run_id)
    if task is None:
        qs = SandboxRun.objects.filter(id=run_id)
        auth_user_id = _get_auth_user_id(request)
        if auth_user_id:
            qs = qs.filter(user_id=auth_user_id)
        agent_run = await sync_to_async(qs.first)()
        if agent_run is None:
            raise HttpError(404, f"Run {run_id} not found")
        if agent_run.status in ("completed", "failed", "cancelled"):
            raise HttpError(409, f"Run {run_id} is already {agent_run.status}")
        # Run is "running" in DB but has no active task (server restarted).
        await sync_to_async(SandboxRun.objects.filter(id=run_id).update)(status="cancelled", updated_at=timezone.now())
        log.warning("Marked orphaned run %s as cancelled", run_id)
        return {"status": "cancelled", "run_id": run_id}
    task.cancel()
    log.info("Cancellation requested: run=%s", run_id)
    return {"status": "cancelling", "run_id": run_id}


@runs_router.post("/runs/{run_id}/branch", response={201: dict})
@require_scope(["run:admin"])
async def branch_run(request, run_id: str, body: BranchRequest = Body(...)) -> tuple[int, dict[str, str]]:
    """Branch the conversation at a specific message.

    Creates a new conversation_id that inherits all messages up to and
    including ``from_message_id``.  The branch is fully independent —
    subsequent runs on the branch do not affect the original conversation.

    Returns the new ``branch_conversation_id`` to pass as ``conversation_id``
    on future ``POST /runs`` calls.
    """
    memory_store = _get_memory_store()

    agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
    if agent_run is None:
        raise HttpError(404, f"Run {run_id} not found")

    # Create a temporary agent seeded with the run's conversation context.
    # branch() reads self.conversation_id and self._memory_persistence.
    # The agent name MUST match the name used when messages were stored.
    # In orchestrator mode the planner stores messages under "planner";
    # in non-orchestrator mode the agent stores under "agent".
    from exo import Agent as _Agent

    agent_name = "planner"  # orchestrator mode is always active
    temp_agent = _Agent(
        name=agent_name,
        model=agent_run.model or AGENT_MODEL,
        memory=memory_store,
    )
    temp_agent.conversation_id = agent_run.conversation_id

    try:
        branch_conv_id = await temp_agent.branch(from_message_id=body.from_message_id)
    except Exception as exc:
        raise HttpError(400, str(exc))

    log.info("Branched run %s at message %s → %s", run_id, body.from_message_id, branch_conv_id)
    return 201, {"branch_conversation_id": branch_conv_id}


@runs_router.post("/runs/{run_id}/inject")
@require_scope(["run:admin"])
async def inject_message(request, run_id: str, body: InjectMessageRequest = Body(...)) -> dict[str, str]:
    """Inject a user message into a running agent.

    The message is queued and picked up before the agent's next LLM call.
    A ``message_injected`` SSE event is emitted so streaming clients see it.
    """
    agent = _run_agents.get(run_id)
    if agent is None:
        agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
        if agent_run is None:
            raise HttpError(404, f"Run {run_id} not found")
        raise HttpError(409, f"Run {run_id} is not active — injection requires a live run")

    agent.inject_message(body.message)
    log.info("Injected message into run %s: %r", run_id, body.message[:80])
    return {"status": "message_injected", "run_id": run_id}


# ── File Uploads ─────────────────────────────────────────────────────────────

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/tmp/workspace/uploads")


@runs_router.post("/uploads")
@require_scope(["files:rw"])
async def upload_file(request) -> dict[str, Any]:
    """Accept a file upload and save to UPLOAD_DIR.

    Reads the file from the Django request.FILES multipart data.
    """
    if not request.FILES:
        raise HttpError(400, "No file uploaded")

    file = list(request.FILES.values())[0]
    upload_path = FilePath(UPLOAD_DIR)
    upload_path.mkdir(parents=True, exist_ok=True)
    # Sanitise filename: reject traversal and sensitive names
    filename = FilePath(file.name).name  # strip any directory components
    if not filename or filename in (".", "..") or "\x00" in filename or "/" in filename or "\\" in filename:
        raise HttpError(403, "Path blocked: invalid filename")
    upload_root = upload_path.resolve()
    dest = (upload_path / filename).resolve()
    if not dest.is_relative_to(upload_root):
        raise HttpError(403, "Path blocked: directory traversal not allowed")
    content = file.read()
    with open(dest, "wb") as f:
        f.write(content)
    return {"filename": filename, "path": str(dest), "size": len(content)}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 7 — SSE STREAMING + MESSAGES ENDPOINTS                            ║
# ║                                                                            ║
# ║  GET /runs/{id}/stream   → Single SSE endpoint (DB cursor + notify)        ║
# ║  GET /runs/{id}/messages → Materialized messages for history loading       ║
# ║                                                                            ║
# ║  One streaming path handles finished, live, and reconnecting clients.      ║
# ║  DB is the single source of truth — no in-memory replay buffer.            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@streaming_router.get("/runs/{run_id}/stream")
@require_scope(["stream:read"])
async def stream_run(request, run_id: str) -> StreamingHttpResponse:
    """Unified SSE stream — works for finished, live, and reconnecting clients.

    Single code path:
    1. Drain DB backlog (events after ``?after=<seq>`` or Last-Event-ID)
    2. If run still live, tail via RunNotifyChannel waiter
    3. On channel close (run terminal), do final drain and return
    4. Keepalive comments on timeout to prevent proxy disconnects

    Uses keyset pagination (WHERE seq > N) — O(1) regardless of event count.
    """
    # Parse resume position from query param or header
    after_raw = request.GET.get("after") or request.headers.get("Last-Event-ID") or request.GET.get("last_event_id")
    after_seq: int = -1
    if after_raw:
        try:
            after_seq = int(after_raw)
        except (ValueError, TypeError):
            pass

    # Verify run exists
    agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
    if agent_run is None:
        raise HttpError(404, f"Run {run_id} not found")

    remote_addr = request.META.get("REMOTE_ADDR", "-")
    log.info("Run %s: SSE client connected after=%d remote=%s", run_id, after_seq, remote_addr)

    async def _generate() -> AsyncIterator[str]:
        started_at = time.perf_counter()
        events_sent = 0
        keepalives_sent = 0
        close_reason = "unknown"
        current_seq = after_seq
        warned_missing_channel = False
        run_status: str | None = "running"

        try:
            yield ": connected\n\n"

            while True:
                # Fetch next batch from DB (keyset pagination)
                events = await _fetch_events_after(run_id, current_seq, limit=100)
                for evt in events:
                    yield f"id: {evt.sequence}\nevent: {evt.event_type}\ndata: {evt.data_for_sse}\n\n"
                    events_sent += 1
                    current_seq = evt.sequence

                run_status = await _get_run_status(run_id)
                run_terminal = run_status in _TERMINAL_RUN_STATUSES or run_status is None
                channel = _run_channels.get(run_id)
                channel_live = channel is not None and not channel.is_closed

                # Run is terminal (or missing) — final drain and close the stream.
                if run_terminal:
                    final = await _fetch_events_after(run_id, current_seq, limit=10000)
                    for evt in final:
                        yield f"id: {evt.sequence}\nevent: {evt.event_type}\ndata: {evt.data_for_sse}\n\n"
                        events_sent += 1
                        current_seq = evt.sequence
                    close_reason = f"terminal:{run_status or 'missing'}"
                    return

                keepalive_payload = json.dumps(
                    {
                        "t": int(time.time() * 1000),
                        "seq": current_seq,
                        "status": run_status,
                    }
                )

                # Preferred path: in-process notifier is available.
                if channel_live and not events:
                    # Caught up — wait for notification or keepalive timeout.
                    waiter = channel.create_waiter()
                    try:
                        await asyncio.wait_for(waiter.wait(), timeout=RUN_STREAM_KEEPALIVE_SECONDS)
                    except TimeoutError:
                        keepalives_sent += 1
                        yield f": keepalive {keepalive_payload}\n\n"
                    finally:
                        waiter.clear()
                        channel.remove_waiter(waiter)
                    continue

                # Fallback path: no live notify channel but run is still non-terminal.
                # This can happen if process-local state was lost (e.g. restart, worker
                # mismatch). Keep tailing from DB so clients don't get disconnected.
                if not channel_live and not warned_missing_channel:
                    warned_missing_channel = True
                    log.warning(
                        "Run %s: stream fallback to DB polling (status=%s, channel_live=%s)",
                        run_id,
                        run_status,
                        channel_live,
                    )

                if not events:
                    await asyncio.sleep(RUN_STREAM_KEEPALIVE_SECONDS)
                    keepalives_sent += 1
                    yield f": keepalive {keepalive_payload}\n\n"
        except asyncio.CancelledError:
            close_reason = "client_cancelled"
            raise
        except Exception:
            close_reason = "stream_exception"
            log.exception(
                "Run %s: stream generator failed (after=%d current_seq=%d)",
                run_id,
                after_seq,
                current_seq,
            )
            diag_payload = {
                "run_id": run_id,
                "message": "stream_generator_failed",
            }
            yield f"event: error\ndata: {json.dumps(diag_payload)}\n\n"
        finally:
            elapsed = time.perf_counter() - started_at
            log.info(
                "Run %s: SSE stream closed reason=%s remote=%s elapsed=%.3fs events=%d keepalives=%d last_seq=%d status=%s",
                run_id,
                close_reason,
                remote_addr,
                elapsed,
                events_sent,
                keepalives_sent,
                current_seq,
                run_status,
            )

    response = StreamingHttpResponse(
        _generate(),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["X-Run-Id"] = run_id
    return response


@runs_router.get("/runs/{run_id}/messages")
@require_scope(["stream:read"])
async def get_messages(request, run_id: str) -> dict:
    """Return materialized messages for history loading (no client-side replay).

    Supports keyset pagination via ``?before=<msg_seq>&limit=N``.
    Returns newest messages first (reversed to chronological order).
    """
    from agent_server.models import SandboxMessage  # noqa: C0415

    limit_raw = request.GET.get("limit", "50")
    before_raw = request.GET.get("before")
    try:
        limit = min(int(limit_raw), 200)
    except (ValueError, TypeError):
        limit = 50

    qs = SandboxMessage.objects.filter(run_id=run_id)
    if before_raw:
        try:
            qs = qs.filter(sequence__lt=int(before_raw))
        except (ValueError, TypeError):
            pass

    msgs = await sync_to_async(list)(qs.order_by("-sequence")[:limit])
    msgs.reverse()
    has_more = len(msgs) == limit

    return {
        "messages": [m.content for m in msgs],
        "has_more": has_more,
        "oldest_sequence": msgs[0].sequence if msgs else None,
        "newest_sequence": msgs[-1].sequence if msgs else None,
    }
