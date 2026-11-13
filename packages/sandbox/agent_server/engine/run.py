"""Agent execution engine — the core _run_agent() function."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import AsyncExitStack, suppress
from pathlib import Path as FilePath
from typing import TYPE_CHECKING, Any

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from django.utils import timezone
from exo import FunctionTool, run
from exo.context.config import ContextConfig
from exo.context.context import Context as ExoContext
from exo.guardrail.types import GuardrailError as _GuardrailError
from exo.hooks import HookPoint
from exo.human import HumanInputHandler
from exo.memory.backends.postgres import PostgresMemoryStore
from exo.models.provider import get_provider
from exo.rail import RailAbortError as _RailAbortError
from exo.types import SystemMessage, UserMessage

from agent_server.config import (
    _STATUS_SUPPRESS,
    AGENT_KM_ENABLED,
    AGENT_PROVIDER_TIMEOUT_SECONDS,
    AGENT_RALPH_ENABLED,
    AGENT_RUN_TIMEOUT,
    EXECUTOR_MAX_STEPS,
    HITL_TIMEOUT,
    LLM_EVENT_TIMEOUT_RETRIES,
    LLM_EVENT_TIMEOUT_SECONDS,
    LLM_PREFLIGHT_BACKOFF_SECONDS,
    LLM_PREFLIGHT_ENABLED,
    LLM_PREFLIGHT_MAX_RETRIES,
    LLM_PREFLIGHT_TIMEOUT_SECONDS,
    SANDBOX_WORKSPACE_ROOT,
    SUKUNA_SANDBOX_ID,
    USAGE_FLUSH_EVENTS,
    USAGE_FLUSH_SECONDS,
    MCPServerConfig,
    _load_exo_md,
)
from agent_server.engine.billing import (
    bill_tool_call as _bill_tool_call,
)
from agent_server.engine.billing import (
    classify_tool_call as _billing_classify,
)
from agent_server.engine.billing import (
    clear_hold_cache as _billing_clear_hold_cache,
)
from agent_server.engine.context import ContextEngineConfig
from agent_server.engine.harness import RalphResult
from agent_server.engine.hooks import (
    billing_estimate_fallback_hook,
    budget_monitor_hook,
    context_persistence_hook,
    make_context_engine_hook,
)
from agent_server.engine.prompts import build_executor_instructions
from agent_server.engine.verbose import log_event as _verbose_event
from agent_server.engine.verbose import log_harness as _verbose_harness
from agent_server.infra import (
    LeaseEnforcer,
    LeaseViolation,
    RunNotifyChannel,
    UsageTotals,
    _active_conversations,
    _check_prd_completion_detailed,
    _hitl_pending,
    _merge_prd_passes,
    _read_progress_patterns,
    _run_agents,
    _run_channels,
    _run_mcp_config_paths,
    _run_mcp_servers,
    _run_tasks,
    attach_guardrails,
    build_cli_tool_catalog,
    cleanup_run_usage,
    parse_lease_limits,
    persist_context_event,
    register_run_usage_totals,
    skill_registry,
    skill_tool_resolver,
    sync_attachment,
    sync_run_cancelled,
    sync_run_completed,
    sync_run_failed,
    sync_run_started,
    sync_run_usage,
    unregister_run_usage_totals,
    update_usage_totals,
)
from agent_server.models import (
    DjangoConversation,
    SandboxEvent,
    SandboxRun,
)
from agent_server.models import (
    HitlRequest as HitlRequestModel,
)
from agent_server.prompts import RALPH_WORKFLOW_ADDENDUM

if TYPE_CHECKING:
    pass

log = logging.getLogger("agent_server")


class UpstreamModelError(RuntimeError):
    """Raised when the upstream LLM endpoint is unavailable or stalls."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _exc_text(exc: BaseException | None) -> str:
    if exc is None:
        return "unknown error"
    text = str(exc).strip()
    return text or exc.__class__.__name__


def _is_retryable_upstream_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError, ConnectionError, OSError)):
        return True
    msg = _exc_text(exc).lower()
    retry_markers = (
        "timed out",
        "timeout",
        "connect",
        "connection",
        "refused",
        "reset",
        "service unavailable",
        "bad gateway",
        "gateway timeout",
        "temporarily unavailable",
        "server disconnected",
        "remote protocol error",
        "503",
        "502",
    )
    return any(marker in msg for marker in retry_markers)


async def _run_llm_preflight(
    *,
    provider: Any,
    run_id: str,
    model: str,
) -> None:
    """Quick upstream model probe before entering the full orchestration flow."""
    if not LLM_PREFLIGHT_ENABLED:
        return

    attempts = max(1, LLM_PREFLIGHT_MAX_RETRIES + 1)
    last_error: BaseException | None = None
    probe_messages = [
        SystemMessage(content="Reply with exactly: ok"),
        UserMessage(content="ping"),
    ]

    for attempt in range(1, attempts + 1):
        try:
            await asyncio.wait_for(
                provider.complete(
                    probe_messages,
                    temperature=0,
                    max_tokens=4,
                ),
                timeout=LLM_PREFLIGHT_TIMEOUT_SECONDS,
            )
            if attempt > 1:
                log.info(
                    "Run %s: LLM preflight recovered on attempt %d/%d (model=%s)",
                    run_id,
                    attempt,
                    attempts,
                    model,
                )
            return
        except Exception as exc:
            last_error = exc
            can_retry = attempt < attempts and _is_retryable_upstream_error(exc)
            log.warning(
                "Run %s: LLM preflight failed attempt %d/%d (model=%s): %s",
                run_id,
                attempt,
                attempts,
                model,
                _exc_text(exc),
            )
            if not can_retry:
                break
            delay = LLM_PREFLIGHT_BACKOFF_SECONDS * (2 ** (attempt - 1))
            if delay > 0:
                await asyncio.sleep(delay)

    raise UpstreamModelError(
        code="llm_unavailable",
        message=f"Upstream model is unavailable: {_exc_text(last_error)}",
    ) from last_error


class HTTPHumanInputHandler(HumanInputHandler):
    """Suspends the agent and waits for an HTTP response from the user.

    When the agent calls human_input(), this handler:
    1. Creates a HitlRequest record in the DB
    2. Publishes a hitl_request SSE event
    3. Blocks on an asyncio.Future until the user responds via POST /hitl/{id}
    4. Returns the user's response text to the agent
    """

    def __init__(self, run_id: str, conversation_id: str, emit_fn) -> None:
        self._run_id = run_id
        self._conversation_id = conversation_id
        self._emit_fn = emit_fn

    async def get_input(self, prompt: str, choices: list[str] | None = None) -> str:
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[str] = loop.create_future()

        _hitl_pending.setdefault(self._run_id, {})[request_id] = future

        # Persist the HITL request to the database.
        await sync_to_async(HitlRequestModel.objects.create)(
            id=request_id,
            run_id=self._run_id,
            prompt=prompt,
            choices=choices,
        )

        # Set the conversation flag so the frontend can show the "needs input" badge
        # when the user is looking at a different conversation.
        try:
            await sync_to_async(DjangoConversation.objects.filter(id=self._conversation_id).update)(
                requires_user_input=True
            )
        except Exception:
            log.debug("Failed to set requires_user_input on conversation %s", self._conversation_id, exc_info=True)

        await self._emit_fn({"type": "hitl_request", "request_id": request_id, "prompt": prompt, "choices": choices})

        log.info("HITL blocking: run=%s request=%s", self._run_id, request_id)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout=HITL_TIMEOUT)
        except TimeoutError:
            future.cancel()
            try:
                await sync_to_async(HitlRequestModel.objects.filter(id=request_id).update)(status="timed_out")
            except Exception:
                log.warning("Failed to mark timed-out HITL request %s in DB", request_id)
            raise RuntimeError(f"Human input timed out after {HITL_TIMEOUT}s (request {request_id})")
        finally:
            _hitl_pending.get(self._run_id, {}).pop(request_id, None)


async def _run_agent(
    *,
    run_id: str,
    conversation_id: str,
    task: str,
    model: str,
    native_tools: list,
    external_mcp_configs: list[MCPServerConfig] | None = None,
    base_instructions: str,
    max_steps: int,
    user_id: str | None,
    session_id: str | None,
    channel: RunNotifyChannel,
    memory_store: PostgresMemoryStore,
    tool_toggles: dict[str, bool] | None = None,
    provider_overrides: dict[str, dict] | None = None,
    user_prefs: dict | None = None,
    project_custom_instructions: str | None = None,
    exo_md_content: str | None = None,
    project_id: str | None = None,
    project_title: str = "",
    project_files: list[dict] | None = None,
) -> None:
    """Execute the agent, persisting every event to the DB and the event bus.

    This is the core function of the server.  It orchestrates:
    - Native tool loading from the tool registry
    - Optional external MCP tool connection (for user-added servers)
    - Agent creation with exo framework
    - Event streaming with batched DB persistence
    - Lease enforcement (runtime, tokens, cost)
    - Backend sync (status + usage updates to Django backend tables)
    - Terminal state handling (completed, failed, cancelled, timeout)

    All DB operations use the Django ORM via sync_to_async wrappers.
    Backend status/usage updates use the backend_sync service instead of webhooks.
    """

    # ── BYOM: inject tool-level provider env var overrides ────────────────
    # Each sandbox serves one user at a time, so os.environ mutation is safe.
    # We save original values and restore them in the finally block.
    _byom_original_env: dict[str, str | None] = {}

    _BYOM_SLOT_ENV_MAP: dict[str, dict[str, str]] = {
        "vision": {
            "MANAGED_VISION_LLM_API_KEY": "api_key",
            "MANAGED_VISION_LLM_BASE_URL": "base_url",
            "MANAGED_VISION_LLM_MODEL": "model_name",
            "MANAGED_VISION_LLM_PROVIDER": "provider_name",
        },
        "audio": {
            "MANAGED_AUDIO_LLM_API_KEY": "api_key",
            "MANAGED_AUDIO_LLM_BASE_URL": "base_url",
            "MANAGED_AUDIO_LLM_MODEL": "model_name",
            "MANAGED_AUDIO_LLM_PROVIDER": "provider_name",
        },
    }

    # Provider-specific extras → env vars.  Keys in the user's ``extras``
    # JSON field are mapped to the env vars that tool modules expect.
    _BYOM_EXTRAS_ENV_MAP: dict[str, str] = {
        # Azure OpenAI
        "azure_endpoint": "AZURE_OPENAI_ENDPOINT",
        "api_version": "AZURE_OPENAI_API_VERSION",
        "azure_deployment": "AZURE_OPENAI_DEPLOYMENT_NAME",
    }

    # Normalise user-facing provider names to what tool modules dispatch on.
    # OpenAI-compatible providers (openrouter, ollama) → "openai" so tools
    # use the OpenAI SDK with the custom base_url; vertex → "gemini" for
    # perception tools that only know "gemini", not "vertex".
    _BYOM_TOOL_PROVIDER_MAP: dict[str, str] = {
        "openai": "openai",
        "anthropic": "anthropic",
        "azure_openai": "azure_openai",
        "openrouter": "openai",
        "ollama": "openai",
    }

    def _byom_set_env(env_var: str, value: str) -> None:
        """Set an env var, saving the original for later restoration."""
        _byom_original_env[env_var] = os.environ.get(env_var)
        os.environ[env_var] = value

    if provider_overrides:
        for slot, env_map in _BYOM_SLOT_ENV_MAP.items():
            if slot in provider_overrides:
                cfg = provider_overrides[slot]
                raw_provider = cfg.get("provider_name", "")

                for env_var, cfg_key in env_map.items():
                    value = cfg.get(cfg_key, "")
                    if not value:
                        continue
                    # Normalise provider_name for tools that dispatch on it.
                    if cfg_key == "provider_name":
                        value = _BYOM_TOOL_PROVIDER_MAP.get(value, value)
                    _byom_set_env(env_var, str(value))

                # For OpenAI-compatible providers (openrouter, ollama, and
                # standard openai with custom base_url), also set the global
                # OPENAI_API_KEY / OPENAI_BASE_URL — some tool code paths
                # (e.g. search.py get_llm) write these into env before
                # constructing LangChain clients.
                api_key = cfg.get("api_key", "")
                base_url = cfg.get("base_url", "")
                if raw_provider in ("openrouter", "ollama", "openai"):
                    if api_key:
                        _byom_set_env("OPENAI_API_KEY", api_key)
                    if base_url:
                        _byom_set_env("OPENAI_BASE_URL", base_url)
                elif raw_provider == "anthropic":
                    if api_key:
                        _byom_set_env("ANTHROPIC_API_KEY", api_key)

                # Also apply provider-specific extras to env vars.
                extras = cfg.get("extras") or {}
                for extras_key, env_var in _BYOM_EXTRAS_ENV_MAP.items():
                    if extras_key in extras and extras[extras_key]:
                        _byom_set_env(env_var, str(extras[extras_key]))

        log.info(
            "Run %s: BYOM overrides applied for slots: %s",
            run_id,
            ", ".join(s for s in _BYOM_SLOT_ENV_MAP if s in provider_overrides),
        )

    # Instructions are fully assembled later via build_planner_instructions()
    # once mcp_catalog is available (after MCP server offloading).

    seq = 0
    msg_seq = 0
    _emit_lock = asyncio.Lock()
    run_started_at = time.perf_counter()
    first_event_emitted = False
    emitted_events = 0

    # ── Per-tool-call billing: MCP server name → credit tier lookup ────────
    _mcp_server_names: set[str] = set()
    _mcp_server_tiers: dict[str, str] = {}
    if external_mcp_configs:
        for cfg in external_mcp_configs:
            _mcp_server_names.add(cfg.name)
            _mcp_server_tiers[cfg.name] = getattr(cfg, "credit_tier", "standard")
    # Addon credit tiers are merged later after run_metadata is loaded.

    # ── Materialized message state ────────────────────────────────────────
    # Text messages: INSERT once on first chunk, accumulate in memory,
    # UPDATE once on finalize.  No per-chunk DB writes.
    _current_text_msg: SandboxMessage | None = None
    _text_accum: str = ""

    from agent_server.models import SandboxMessage  # noqa: C0415

    async def _finalize_text() -> None:
        """Finalize the current streaming text message (one DB write)."""
        nonlocal _current_text_msg, _text_accum
        if _current_text_msg is not None:
            _current_text_msg.content["text"] = _text_accum
            _current_text_msg.is_complete = True
            await sync_to_async(_current_text_msg.save)(update_fields=["content", "is_complete", "updated_at"])
            _current_text_msg = None
            _text_accum = ""

    async def _materialize_message(event_type: str, payload: dict[str, Any]) -> None:
        """Dual-write: incrementally build SandboxMessage rows alongside events.

        Text: INSERT once on first chunk (is_complete=False), accumulate in
        memory (_text_accum), UPDATE once on _finalize_text().
        Other types: INSERT immediately as complete messages.
        """
        nonlocal _current_text_msg, _text_accum, msg_seq

        if event_type == "text":
            if _current_text_msg is None:
                msg_seq += 1
                _current_text_msg = await sync_to_async(SandboxMessage.objects.create)(
                    run_id=run_id,
                    sequence=msg_seq,
                    msg_type="text",
                    content={"type": "text", "text": payload.get("text", "")},
                    is_complete=False,
                )
                _text_accum = payload.get("text", "")
            else:
                _text_accum += payload.get("text", "")  # in-memory only

        elif event_type == "tool_call":
            await _finalize_text()
            if not payload.get("_plan"):
                msg_seq += 1
                await sync_to_async(SandboxMessage.objects.create)(
                    run_id=run_id,
                    sequence=msg_seq,
                    msg_type="tool_call",
                    content=payload,
                )

        elif event_type == "tool_result":
            if not payload.get("_plan"):
                # Merge result into existing tool_call message
                call_id = payload.get("call_id") or payload.get("tool_call_id")
                if call_id:
                    try:
                        tc_msg = await sync_to_async(
                            SandboxMessage.objects.filter(
                                run_id=run_id,
                                msg_type="tool_call",
                            )
                            .order_by("-sequence")
                            .first
                        )()
                        if tc_msg and tc_msg.content.get("callId") == call_id:
                            tc_msg.content["result"] = payload.get("result") or payload.get("content")
                            tc_msg.content["status"] = "completed"
                            await sync_to_async(tc_msg.save)(update_fields=["content", "updated_at"])
                    except Exception:
                        log.debug("Run %s: tool_result merge failed for %s", run_id, call_id, exc_info=True)

        elif event_type in ("step", "hitl_request", "error", "reasoning", "user_message", "mcp_progress"):
            await _finalize_text()
            msg_seq += 1
            await sync_to_async(SandboxMessage.objects.create)(
                run_id=run_id,
                sequence=msg_seq,
                msg_type=event_type,
                content=payload,
            )

        elif event_type in ("run_completed", "run_failed", "run_cancelled"):
            await _finalize_text()

    async def _emit(event_data: dict[str, Any], *, force_flush: bool = False) -> None:
        """Write-ahead event persistence + dual-write message + notify.

        Each event is persisted immediately (single INSERT) with pre-serialized
        JSON for zero-copy SSE output.  No batching — events are visible to
        all SSE clients the instant they're written.

        Uses _emit_lock to serialize concurrent callers (main agent loop +
        live_preview background task) and prevent duplicate sequence numbers.
        """
        nonlocal seq, first_event_emitted, emitted_events

        # Pre-compute billing/sanitization outside the lock (no seq dependency).
        event_type = event_data.get("type", "")

        # 1. Sanitize text events for prompt leakage
        if event_type == "text" and "text" in event_data:
            from agent_server.infra.guards import _PROMPT_FINGERPRINTS  # noqa: C0415

            text = event_data["text"]
            for _fp in _PROMPT_FINGERPRINTS:
                if _fp.search(text):
                    log.warning("Run %s: prompt leakage detected, redacting", run_id)
                    event_data = {**event_data, "text": ""}
                    break

        # 2. Tag plan events server-side (frontend just checks _plan flag)
        if event_type == "tool_call":
            tool_name = event_data.get("tool_name") or event_data.get("name") or ""
            if tool_name in ("plan", "mcp_update_plan", "mcp_advance_plan", "mcp_get_plan"):
                event_data = {**event_data, "_plan": True}

            # 2b. Per-tool-call credit billing (fire-and-forget)
            if tool_name and not event_data.get("_plan"):
                _args_raw = event_data.get("arguments") or ""
                if isinstance(_args_raw, dict):
                    import json as _json

                    _args_raw = _json.dumps(_args_raw)
                _tool_type, _real_name, _matched_server = _billing_classify(tool_name, _args_raw, _mcp_server_names)
                _is_mcp = _tool_type == "mcp"
                _tier = _mcp_server_tiers.get(_matched_server, "standard") if _is_mcp else "standard"
                asyncio.create_task(
                    _bill_tool_call(
                        run_id,
                        _real_name,
                        _is_mcp,
                        event_data.get("callId") or event_data.get("id") or "",
                        credit_tier=_tier,
                    )
                )
                # Track in usage counters
                if _is_mcp:
                    usage_totals.mcp_tool_calls += 1
                else:
                    usage_totals.native_tool_calls += 1

        # 3. Acquire lock, assign sequence, persist, increment — atomic unit.
        async with _emit_lock:
            payload = {**event_data, "sequence": seq}

            if not first_event_emitted:
                first_event_emitted = True
                log.info(
                    "Run %s: first event after %.3fs (type=%s)",
                    run_id,
                    time.perf_counter() - run_started_at,
                    event_type,
                )

            data_json = json.dumps(payload)
            try:
                await sync_to_async(SandboxEvent.objects.create)(
                    run_id=run_id,
                    sequence=seq,
                    event_type=event_type,
                    data=payload,
                    data_raw=data_json,
                )
            except IntegrityError:
                log.debug("Run %s: seq=%d collided on cancel/crash (harmless), skipping", run_id, seq)
            emitted_events += 1

            # Dual-write materialized message
            try:
                await _materialize_message(event_type, payload)
            except Exception:
                log.debug("Run %s: message materialization failed for seq=%d", run_id, seq, exc_info=True)

            # Notify SSE waiters (they read from DB)
            channel.notify(seq)
            seq += 1

        # Throttled idle-timer bump so the sandbox doesn't get culled mid-run.
        # Runs outside the seq lock — best-effort, no back-pressure on emit.
        from agent_server.infra.idle import bump_idle_timer  # noqa: C0415

        asyncio.create_task(bump_idle_timer())

    async def _set_run_status(status: str, error: str | None = None) -> None:
        """Update the sandbox-owned SandboxRun status in the DB."""
        await sync_to_async(SandboxRun.objects.filter(id=run_id).update)(
            status=status, error=error, updated_at=timezone.now()
        )

    usage_totals = UsageTotals()
    usage_events_since_sync = 0
    last_usage_sync_at = time.perf_counter()
    terminal_sync_emitted = False
    timeout_error_code = "run_timeout"
    run_metadata: dict[str, Any] = {}

    # Load run metadata for lease limits and sandbox_id.
    try:
        run_row = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
        if run_row is not None and isinstance(run_row.metadata, dict):
            run_metadata = run_row.metadata
    except Exception:
        log.warning("Run %s: failed to load run metadata for lease/metering", run_id, exc_info=True)

    lease_limits = parse_lease_limits(run_metadata)
    lease_enforcer = LeaseEnforcer(lease_limits, started_monotonic=run_started_at)
    sandbox_id = (
        run_metadata.get("sandbox_id") if isinstance(run_metadata.get("sandbox_id"), str) else SUKUNA_SANDBOX_ID
    )

    # Merge addon credit tiers from backend metadata (addon_name → tier)
    _addon_tiers = (run_metadata or {}).get("addon_credit_tiers") or {}
    if isinstance(_addon_tiers, dict):
        _mcp_server_tiers.update(_addon_tiers)

    # Make usage_totals reachable to sub-agents that run outside this loop
    # (Knowledge Manager). They will fold their own token counts into the
    # same UsageTotals instance so every LLM call gets billed to this run.
    register_run_usage_totals(run_id, usage_totals, sandbox_id=sandbox_id)

    # ── Backend sync helpers (replace old webhook callbacks) ──────────────
    # Instead of enqueuing events into an outbox for a background dispatcher,
    # we call the backend_sync service directly to update Django tables.

    async def _sync_usage(force: bool = False) -> None:
        """Sync accumulated usage to backend tables, throttled by count/time."""
        nonlocal usage_events_since_sync, last_usage_sync_at
        if usage_events_since_sync == 0:
            return
        elapsed = time.perf_counter() - last_usage_sync_at
        if not force and usage_events_since_sync < USAGE_FLUSH_EVENTS and elapsed < USAGE_FLUSH_SECONDS:
            return
        await sync_run_usage(run_id, usage_totals, sandbox_id=sandbox_id)
        usage_events_since_sync = 0
        last_usage_sync_at = time.perf_counter()

    async def _sync_terminal_once(
        *,
        terminal_status: str,
        error: str | None = None,
    ) -> None:
        """Call the appropriate backend_sync terminal function exactly once."""
        nonlocal terminal_sync_emitted
        if terminal_sync_emitted:
            return
        if terminal_status == "completed":
            await sync_run_completed(run_id, usage_totals, sandbox_id=sandbox_id)
        elif terminal_status == "failed":
            await sync_run_failed(run_id, error or "", usage_totals, sandbox_id=sandbox_id)
        elif terminal_status == "cancelled":
            await sync_run_cancelled(run_id, usage_totals, sandbox_id=sandbox_id)
        terminal_sync_emitted = True

    effective_timeout = AGENT_RUN_TIMEOUT
    if lease_limits.max_runtime_seconds is not None and (
        effective_timeout is None or lease_limits.max_runtime_seconds < effective_timeout
    ):
        effective_timeout = lease_limits.max_runtime_seconds
        timeout_error_code = "lease_runtime_exceeded"

    # The continuous Knowledge Manager loop is started once the harness
    # and provider are ready and torn down in the outer finally.  Declared
    # here so the finally can always reach it even on early failure.
    km_loop: Any = None
    # Live document preview loop — mtime-polls the workspace and emits
    # synthetic artifact tool_result events for .pptx/.docx/.xlsx/.pdf/.md
    # changes. Declared here for the same early-failure reason.
    preview_loop: Any = None

    try:
        async with AsyncExitStack() as stack:
            # Native tools are pre-resolved from the tool registry — no MCP needed.
            all_tools = list(native_tools)
            log.info("Run %s: %d native tools loaded from registry", run_id, len(all_tools))

            # Offload external MCP servers via exo-mcp CLI.
            # Instead of loading tool schemas into the agent (which bloats
            # the tools= parameter and breaks KV cache), we write mcp.json
            # to disk and the agent calls tools via shell:
            #   exo-mcp tool call <server> <tool> --config <path> -j '{...}'
            mcp_catalog = ""
            if external_mcp_configs:
                from agent_server.engine.mcp import (
                    build_tool_catalog,
                    write_mcp_config,
                )

                offload_started_at = time.perf_counter()
                mcp_config_path = write_mcp_config(external_mcp_configs)
                _run_mcp_config_paths[run_id] = str(mcp_config_path)
                mcp_catalog = await build_tool_catalog(mcp_config_path)
                log.info(
                    "Run %s: %d external MCP servers offloaded via exo-mcp-cli in %.3fs",
                    run_id,
                    len(external_mcp_configs),
                    time.perf_counter() - offload_started_at,
                )

            from message import MessageTool  # noqa: C0415

            hitl_tool = MessageTool(
                handler=HTTPHumanInputHandler(run_id, conversation_id, _emit),
                timeout=HITL_TIMEOUT,
            )

            # Use overflow="hook" to delegate all context management to our
            # custom context engine (compaction + summarization).
            ctx_cfg = ContextConfig(overflow="hook")

            lead_tools = list(all_tools)

            # Build an explicit provider so the correct API key + base URL are used.
            # _resolve_provider() in exo passes api_key=None → "dummy" which
            # overrides the OPENAI_API_KEY env var; creating it here avoids that.
            # Must be resolved before the Knowledge Manager hooks below — they
            # capture ``provider`` in closures passed to the KM background loop.
            if provider_overrides and "lead_agent" in provider_overrides:
                # BYOM: use the user's custom lead agent provider.
                _lead_cfg = provider_overrides["lead_agent"]
                api_key = _lead_cfg["api_key"]
                base_url = _lead_cfg.get("base_url") or None
                # Provider-specific extras (e.g. google_project, google_location,
                # google_service_account_base64 for Vertex AI) are passed as
                # kwargs to get_provider() which stores them on ModelConfig.
                _provider_extras = _lead_cfg.get("extras") or {}
            else:
                # Default: vault-managed provider from env vars.
                api_key = os.getenv("OPENAI_API_KEY")
                base_url = os.getenv("OPENAI_BASE_URL")
                _provider_extras = {}
            provider = get_provider(
                model,
                api_key=api_key,
                base_url=base_url,
                timeout=AGENT_PROVIDER_TIMEOUT_SECONDS,
                **_provider_extras,
            )

            # Fail fast if the model endpoint is currently unreachable.
            await _run_llm_preflight(
                provider=provider,
                run_id=run_id,
                model=model,
            )

            # ── Shared agent hooks ────────────────────────────────────────
            # All agents (planner, executor, ralph) use identical hooks.
            # Each agent gets a fresh context engine hook (same config,
            # fresh state per agent).
            from agent_server.engine.hooks import (  # noqa: C0415
                make_content_burst_hook,
                make_km_prefetch_hook,
                make_message_discipline_hook,
                make_plan_context_hook,
                make_vital_info_hook,
            )
            from agent_server.engine.knowledge import (  # noqa: C0415
                get_messages_snapshot,
                run_km,
            )
            from tools.plan import (  # noqa: C0415
                init_plan_state,
                make_plan_tool,
                make_schedule_tool,
            )

            # Initialize per-conversation plan state (loads from DB if exists).
            init_plan_state(conversation_id)

            # Replace the global plan and schedule tools with per-conversation
            # instances that capture conversation_id in a closure.  This bypasses
            # ContextVar propagation issues through the async execution chain.
            _bound_plan = make_plan_tool(conversation_id)
            _bound_schedule = make_schedule_tool(conversation_id)
            # Keep schedule as a direct schema even when PTC is enabled.
            _bound_schedule._ptc_exclude = True
            lead_tools = [
                _bound_plan
                if getattr(t, "name", None) == "plan"
                else _bound_schedule
                if getattr(t, "name", None) == "schedule"
                else t
                for t in lead_tools
            ]

            ctx_engine_config = ContextEngineConfig(
                context_budget_tokens=int(os.environ.get("CONTEXT_BUDGET_TOKENS", "128000")),
            )

            # Knowledge Manager hooks.
            # - vital_info_hook (PRE_LLM_CALL): captures the live trajectory
            #   into the per-conversation snapshot AND injects role-scoped
            #   guidance + pending nudges from the advise cache. Does no
            #   LLM work in the hot path.
            # - km_prefetch_hook (POST_LLM_CALL): schedules a background
            #   run_km after each planner/executor turn so the advise
            #   cache is warm for the next PRE_LLM_CALL.
            # - content_burst_hook (POST_LLM_CALL): fires a run_km on 3
            #   consecutive content-heavy tool calls.
            if AGENT_KM_ENABLED:
                _vital_info_hook = make_vital_info_hook(conversation_id)
                _km_prefetch_hook = make_km_prefetch_hook(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    ctx_engine_config=ctx_engine_config,
                )
                _content_burst_hook = make_content_burst_hook(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    ctx_engine_config=ctx_engine_config,
                )
            else:
                _vital_info_hook = None
                _km_prefetch_hook = None
                _content_burst_hook = None
                log.info(
                    "Run %s: Knowledge Manager disabled via AGENT_KM_ENABLED",
                    run_id,
                )
            _message_discipline_hook = make_message_discipline_hook(conversation_id)
            _plan_context_hook = make_plan_context_hook(conversation_id)

            # Pre-compress callback for the knowledge manager.  Fires
            # BEFORE any context summarize/compact so the KM can capture
            # vital information before it is truncated.  The KM's own
            # context hook (resolved lazily by run_km via
            # get_km_context_hook) does NOT carry an on_pre_compress
            # callback, and the _in_km_run ContextVar is the backstop
            # against recursion if anything slips through.
            async def _pre_compress_km(messages: list) -> None:
                if not AGENT_KM_ENABLED:
                    return
                try:
                    await run_km(
                        conversation_id=conversation_id,
                        run_id=run_id,
                        messages=list(messages),
                        provider=provider,
                        model=model,
                        trigger="pre_compression",
                        scope="overall",
                        ctx_engine_config=None,
                        force=True,
                    )
                except Exception:
                    log.warning(
                        "pre_compress_km failed for conv=%s",
                        conversation_id[:8],
                        exc_info=True,
                    )

            is_project_run = bool(project_id)

            def _make_agent_hooks() -> list[tuple]:
                """Build a fresh hooks list for any agent."""
                ctx_hook, _ = make_context_engine_hook(
                    ctx_engine_config,
                    conversation_id=conversation_id,
                    on_pre_compress=_pre_compress_km if AGENT_KM_ENABLED else None,
                )
                hooks = [
                    (HookPoint.CONTEXT_WINDOW, ctx_hook),
                    (HookPoint.PRE_LLM_CALL, _message_discipline_hook),
                    (HookPoint.PRE_LLM_CALL, _plan_context_hook),
                    (HookPoint.PRE_LLM_CALL, budget_monitor_hook),
                    (HookPoint.POST_LLM_CALL, context_persistence_hook),
                    # Stash a token estimate when the provider returned 0;
                    # update_usage_totals consumes it on the matching usage event.
                    (HookPoint.POST_LLM_CALL, billing_estimate_fallback_hook),
                ]
                if is_project_run:
                    from agent_server.engine.hooks import (  # noqa: C0415
                        make_project_coordination_hook,
                    )

                    hooks.append((HookPoint.PRE_LLM_CALL, make_project_coordination_hook()))
                if AGENT_KM_ENABLED and _vital_info_hook is not None:
                    hooks.append((HookPoint.PRE_LLM_CALL, _vital_info_hook))
                if AGENT_KM_ENABLED:
                    if _content_burst_hook is not None:
                        hooks.append((HookPoint.POST_LLM_CALL, _content_burst_hook))
                    if _km_prefetch_hook is not None:
                        hooks.append((HookPoint.POST_LLM_CALL, _km_prefetch_hook))
                return hooks

            # ── Ralph loop tool (closure) ───────────────────────────────
            # Defined here so it captures channel, _emit, model, all_tools,
            # lease_enforcer, usage_totals, etc. from the enclosing scope.
            # Events are persisted to DB and notified via RunNotifyChannel
            # for real-time streaming — NOT buffered via ToolContext.
            #
            # Late-bound `harness`: the OrchestrationHarness is created
            # further down (line ~1272), AFTER this closure is defined but
            # BEFORE this closure is ever invoked as a tool. Declaring it
            # as a nonlocal with an initial None lets the closure reach the
            # live harness at tool-call time, so ralph workers can go
            # through harness.build_ralph_worker() — sharing the executor's
            # hook composition, guardrails, and tool-binding factory.
            harness = None

            async def _ralph_loop_fn(
                prd_path: str,
                instructions: str | None = None,
                max_iterations: int = 10,
            ) -> str:
                """Spawn an autonomous Ralph loop to implement a PRD story-by-story.

                Args:
                    prd_path: Path to the prd.json file in the workspace (absolute or relative to workspace root). The file must contain valid JSON with project, branchName, description, and userStories array. Each story needs id, title, description, acceptanceCriteria, priority, passes fields.
                    instructions: Optional project-specific context for the worker agent (e.g. stack, test commands, conventions).
                    max_iterations: Maximum iterations before stopping. Default 10.
                """
                nonlocal usage_events_since_sync

                ws = SANDBOX_WORKSPACE_ROOT

                # 1. Resolve and read PRD file
                prd_file = FilePath(prd_path)
                if not prd_file.is_absolute():
                    prd_file = FilePath(ws) / prd_file
                if not prd_file.exists():
                    return f"Error: PRD file not found at {prd_file}"
                try:
                    prd_data = json.loads(prd_file.read_text())
                    stories = prd_data.get("userStories", [])
                    if not stories:
                        return "Error: prd.json contains no userStories."
                except json.JSONDecodeError as exc:
                    return f"Error: invalid JSON in {prd_file}: {exc}"

                # 2. Merge on-disk passes states so re-invoking ralph_loop
                #    doesn't reset already-completed stories, then write back.
                #    (Only needed when the file was regenerated with passes reset.)
                canonical_prd = FilePath(ws) / "prd.json"
                if canonical_prd.exists() and canonical_prd.resolve() != prd_file.resolve():
                    try:
                        existing = json.loads(canonical_prd.read_text())
                        existing_stories = existing.get("userStories", [])
                        stories = _merge_prd_passes(stories, existing_stories)
                        prd_data["userStories"] = stories
                        _prev_passed = sum(1 for s in existing_stories if s.get("passes"))
                        log.info(
                            "Ralph loop: merged passes states from existing prd.json (%d already passed)",
                            _prev_passed,
                        )
                    except (json.JSONDecodeError, KeyError):
                        pass  # existing file is corrupt — overwrite
                canonical_prd.write_text(json.dumps(prd_data, indent=2))
                log.info("Ralph loop: wrote prd.json to %s", canonical_prd)

                # 3. Initialize progress.txt if it doesn't exist
                progress_path = FilePath(ws) / "progress.txt"
                if not progress_path.exists():
                    progress_path.write_text("## Codebase Patterns\n\n---\n")

                total_stories = len(stories)
                already_passed = sum(1 for s in stories if s.get("passes"))
                log.info(
                    "Ralph loop: %d stories (%d already passed), max %d iterations",
                    total_stories,
                    already_passed,
                    max_iterations,
                )

                await _emit(
                    {
                        "type": "status",
                        "status": "ralph_started",
                        "total_stories": total_stories,
                        "already_passed": already_passed,
                        "max_iterations": max_iterations,
                    }
                )

                # 4. Build worker instructions.
                #    Ralph workers share the executor's full prompt base
                #    (identity, sandbox, reserved_ports, turn_budget,
                #    format, tool_use, error_handling, message_rules,
                #    executor_result) and append the ralph-specific
                #    workflow addendum. cli_tool_catalog is passed as
                #    empty here because the ralph closure appends
                #    cli_catalog separately below — avoids duplication.
                worker_base = build_executor_instructions(
                    cli_tool_catalog="",
                    context="",
                    user_prefs=user_prefs,
                    skill_registry=skill_registry,
                    is_project_run=is_project_run,
                    project_title=project_title,
                    project_files=project_files,
                )
                worker_prompt = worker_base + "\n\n" + RALPH_WORKFLOW_ADDENDUM
                _exo_md, _ = _load_exo_md()
                if _exo_md:
                    worker_prompt = "<project-context>\n" + _exo_md + "\n</project-context>\n\n" + worker_prompt
                if instructions:
                    worker_prompt += f"\n\n## Project-Specific Context\n{instructions}\n"
                if cli_catalog:
                    worker_prompt += cli_catalog
                # 5. Provider creation moved INSIDE the iteration loop (Fix B).
                #    Hoisting it above the loop meant that if the HTTP socket
                #    died mid-run, every subsequent iteration inherited the
                #    dead provider. Per-iteration recreation is cheap
                #    (~1-5ms) and isolates socket health per iteration.

                def _truncate_patterns_block(block: str, *, max_chars: int = 8000) -> str:
                    """Cap the ``## Codebase Patterns`` block for worker prompts.

                    Keeps the header (before the first ``---`` separator) +
                    the most recent entries from the tail, so the injected
                    block doesn't grow unboundedly as iterations accumulate.
                    Cut points snap to ``\\n## `` boundaries to avoid
                    bisecting a pattern entry.
                    """
                    if len(block) <= max_chars:
                        return block
                    header_end = block.find("\n---")
                    if header_end == -1:
                        head = ""
                    else:
                        head = block[: header_end + 4]  # include the ---
                    # Keep the last (max_chars - len(head) - ~100) chars from
                    # the tail, snapped to the next "\n## " after the cut.
                    budget = max_chars - len(head) - 100
                    if budget <= 0:
                        return head + "\n\n...[older patterns truncated]...\n"
                    tail = block[-budget:]
                    snap = tail.find("\n## ")
                    if snap > 0:
                        tail = tail[snap:]
                    return head + "\n\n...[older patterns truncated]...\n" + tail

                # 6. Iteration loop
                consecutive_failures = 0
                _terminal_emitted = False
                # Initialize outside the loop so the outer except (Fix D) can
                # reference these if the loop is cancelled before the first
                # iteration completes.
                passed = 0
                total = 0
                iteration = 0

                try:
                    for iteration in range(1, max_iterations + 1):
                        # Pre-iteration PRD check. Detailed variant (Fix E)
                        # distinguishes file-missing / parse-error / schema-error
                        # from "no stories yet" — logged via _verbose_harness
                        # so a corrupted prd.json is surfaced instead of silently
                        # reading as (0, 0, 0.0).
                        passed, total, score, prd_error = _check_prd_completion_detailed(ws)
                        if prd_error:
                            _verbose_harness(
                                "prd_completion_error",
                                iteration=iteration,
                                stage="pre",
                                reason=prd_error,
                            )

                        if total > 0 and passed == total:
                            _verbose_harness(
                                "ralph_complete",
                                reason="all_stories_passed",
                                iterations=iteration - 1,
                                passed=passed,
                                total=total,
                            )
                            await _emit(
                                {
                                    "type": "status",
                                    "status": "ralph_complete",
                                    "reason": "all_stories_passed",
                                    "iterations": iteration - 1,
                                    "passed": passed,
                                    "total": total,
                                }
                            )
                            _terminal_emitted = True
                            return f"Ralph loop complete: all {total} stories passed in {iteration - 1} iteration(s)."

                        # Baseline for progress-based consecutive_failures
                        # reset (Fix A). Captured BEFORE the iteration runs.
                        prior_passed = passed

                        _verbose_harness(
                            "ralph_iteration_started",
                            iteration=iteration,
                            max_iterations=max_iterations,
                            passed=passed,
                            total=total,
                        )
                        await _emit(
                            {
                                "type": "status",
                                "status": "ralph_iteration_started",
                                "iteration": iteration,
                                "max_iterations": max_iterations,
                                "passed": passed,
                                "total": total,
                            }
                        )

                        # Inject codebase patterns from prior iterations
                        # (Fix C: truncated to ~8KB).
                        iteration_prompt = worker_prompt
                        patterns = _read_progress_patterns(ws)
                        if patterns:
                            patterns = _truncate_patterns_block(patterns, max_chars=8000)
                            iteration_prompt += f"\n\n## Prior Learnings\n{patterns}\n"

                        # Fresh provider per iteration (Fix B). Cheap
                        # insurance against HTTP socket drops carrying across
                        # iterations. Assumption: get_provider() has no lazy
                        # auth token refresh; if that changes, revisit.
                        _api_key = os.getenv("OPENAI_API_KEY")
                        _base_url = os.getenv("OPENAI_BASE_URL")
                        _provider = get_provider(
                            model,
                            api_key=_api_key,
                            base_url=_base_url,
                            timeout=AGENT_PROVIDER_TIMEOUT_SECONDS,
                        )

                        # Ralph worker = executor + ralph workflow addendum.
                        # Construct through the shared harness factory so hooks,
                        # guardrails, tool binding, and context-engine wiring
                        # stay in lockstep with executor sub-agents. Ralph
                        # workers skip tool gating (mobile/webdev/git preloaded)
                        # and emit RalphResult (Pydantic) as their terminal
                        # output. See harness.build_ralph_worker for details.
                        if harness is None:
                            raise RuntimeError(
                                "ralph_loop invoked before OrchestrationHarness "
                                "was constructed — check _run_agent ordering"
                            )
                        worker = harness.build_ralph_worker(
                            instructions=iteration_prompt,
                            name=f"ralph-worker-{iteration}",
                            max_steps=max_steps,
                        )

                        worker_task = (
                            "Read prd.json in the workspace root and implement "
                            "the next incomplete user story. "
                            f"This is Ralph iteration {iteration}/{max_iterations}."
                        )

                        # Accumulate the worker's top-level TextEvents so we
                        # can parse its terminal RalphResult after the stream
                        # closes (Fix A). Filter by agent_name = this worker's
                        # name so nested sub-agent text (defensive — ralph
                        # workers have no `delegate` tool) doesn't bleed in.
                        ralph_output_parts: list[str] = []
                        stream_errored = False

                        try:
                            async for event in run.stream(
                                worker,
                                worker_task,
                                detailed=True,
                                provider=_provider,
                            ):
                                lease_enforcer.check_runtime()

                                payload = event.model_dump()
                                _verbose_event(payload)

                                if payload.get("type") == "text" and payload.get("agent_name") == worker.name:
                                    text = payload.get("text") or ""
                                    if text:
                                        ralph_output_parts.append(text)

                                if payload.get("type") == "usage":
                                    update_usage_totals(usage_totals, payload)
                                    lease_enforcer.check_usage(usage_totals)
                                    usage_events_since_sync += 1
                                    await _sync_usage(force=False)

                                # Suppress sub-agent terminal StatusEvents.
                                if payload.get("type") == "status" and payload.get("status") in _STATUS_SUPPRESS:
                                    continue

                                # Tag events so they can be associated with the iteration
                                payload["ralph_iteration"] = iteration
                                await _emit(payload)

                        except (LeaseViolation, asyncio.CancelledError):
                            # Propagate to outer try for terminal emit + re-raise
                            raise

                        except Exception as exc:
                            stream_errored = True
                            _verbose_harness(
                                "ralph_iteration_failed",
                                iteration=iteration,
                                error=str(exc),
                            )
                            log.warning(
                                "Ralph iteration %d failed: %s",
                                iteration,
                                exc,
                                exc_info=True,
                            )
                            await _emit(
                                {
                                    "type": "status",
                                    "status": "ralph_iteration_failed",
                                    "iteration": iteration,
                                    "error": str(exc),
                                }
                            )

                        # Parse RalphResult in its OWN try (Fix A). Parse
                        # failures are observability noise, not a stream
                        # failure — the worker stream already succeeded if
                        # we got here. Ralph workers whose output doesn't
                        # validate (hit max_steps, emitted malformed JSON,
                        # etc.) just don't populate ralph_result.
                        ralph_result = None
                        if ralph_output_parts:
                            from agent_server.engine._structured_output import (  # noqa: C0415
                                StructuredOutputError,
                                try_parse_structured,
                            )

                            raw_text = "".join(ralph_output_parts)
                            try:
                                ralph_result = try_parse_structured(raw_text, RalphResult)
                                await _emit(
                                    {
                                        "type": "status",
                                        "status": "ralph_iteration_result",
                                        "iteration": iteration,
                                        "story_id": ralph_result.story_id,
                                        "outcome": ralph_result.outcome,
                                        "committed": ralph_result.committed,
                                        "notes": ralph_result.notes,
                                    }
                                )
                            except StructuredOutputError as parse_exc:
                                # Tolerant parser failed — log a one-liner
                                # plus a head/tail of the raw text so we
                                # can see what the worker actually emitted
                                # without dumping the whole transcript.
                                preview = raw_text[:160].replace("\n", " ")
                                tail = raw_text[-80:].replace("\n", " ") if len(raw_text) > 240 else ""
                                log.warning(
                                    "Ralph iteration %d: RalphResult parse failed "
                                    "after fence-strip + object-extract; "
                                    "last_error=%s | preview=%r | tail=%r",
                                    iteration,
                                    parse_exc.last_error,
                                    preview,
                                    tail,
                                )

                        # Re-check prd.json to detect real progress this
                        # iteration made (Fix A).
                        new_passed, total, score, prd_error = _check_prd_completion_detailed(ws)
                        if prd_error:
                            _verbose_harness(
                                "prd_completion_error",
                                iteration=iteration,
                                stage="post",
                                reason=prd_error,
                            )

                        # Progress-based consecutive_failures reset (Fix A).
                        # The counter should only trip when the loop is
                        # GENUINELY stuck — making no progress AND hitting
                        # stream errors. Transient hiccups during an iteration
                        # that nonetheless advanced prd.json should NOT count.
                        made_progress = new_passed > prior_passed
                        blocked_signal = ralph_result is not None and ralph_result.outcome == "blocked"
                        if made_progress or blocked_signal:
                            consecutive_failures = 0
                        elif stream_errored:
                            consecutive_failures += 1
                        else:
                            # No error, no progress, no blocked-signal.
                            # Worker probably hit max_steps without emitting
                            # a valid RalphResult. Log but do NOT increment —
                            # next iteration retries the same story fresh.
                            log.warning(
                                "Ralph iteration %d completed without progress "
                                "and without error — worker may have hit "
                                "max_steps before emitting RalphResult",
                                iteration,
                            )

                        if consecutive_failures >= 3:
                            _verbose_harness(
                                "ralph_complete",
                                reason="max_consecutive_failures",
                                iterations=iteration,
                                passed=new_passed,
                                total=total,
                            )
                            await _emit(
                                {
                                    "type": "status",
                                    "status": "ralph_complete",
                                    "reason": "max_consecutive_failures",
                                    "iterations": iteration,
                                    "passed": new_passed,
                                    "total": total,
                                    "usage": {
                                        "total_tokens": usage_totals.total_tokens,
                                        "cost_usd": round(usage_totals.cost_usd, 6),
                                    },
                                }
                            )
                            _terminal_emitted = True
                            return (
                                f"Ralph loop stopped: {consecutive_failures} consecutive "
                                f"failures. {new_passed}/{total} stories completed."
                            )

                        passed = new_passed  # carry forward for next iteration
                        _usage = {
                            "total_tokens": usage_totals.total_tokens,
                            "cost_usd": round(usage_totals.cost_usd, 6),
                        }
                        _verbose_harness(
                            "ralph_iteration_completed",
                            iteration=iteration,
                            passed=passed,
                            total=total,
                            score=round(score, 3),
                        )
                        await _emit(
                            {
                                "type": "status",
                                "status": "ralph_iteration_completed",
                                "iteration": iteration,
                                "passed": passed,
                                "total": total,
                                "score": round(score, 3),
                                "usage": _usage,
                            }
                        )

                        if total > 0 and passed == total:
                            _verbose_harness(
                                "ralph_complete",
                                reason="all_stories_passed",
                                iterations=iteration,
                                passed=passed,
                                total=total,
                            )
                            await _emit(
                                {
                                    "type": "status",
                                    "status": "ralph_complete",
                                    "reason": "all_stories_passed",
                                    "iterations": iteration,
                                    "passed": passed,
                                    "total": total,
                                    "usage": _usage,
                                }
                            )
                            _terminal_emitted = True
                            return f"Ralph loop complete: all {total} stories passed in {iteration} iteration(s)."

                    # Max iterations reached — loop exits normally
                    passed, total, _, _ = _check_prd_completion_detailed(ws)
                    _usage = {
                        "total_tokens": usage_totals.total_tokens,
                        "cost_usd": round(usage_totals.cost_usd, 6),
                    }
                    await _emit(
                        {
                            "type": "status",
                            "status": "ralph_complete",
                            "reason": "max_iterations",
                            "iterations": max_iterations,
                            "passed": passed,
                            "total": total,
                            "usage": _usage,
                        }
                    )
                    _terminal_emitted = True
                    return (
                        f"Ralph loop stopped: max iterations ({max_iterations}) reached. "
                        f"{passed}/{total} stories completed."
                    )

                except (asyncio.CancelledError, LeaseViolation) as exc:
                    # Fix D: terminal emit on cancellation / lease violation
                    # so the SSE stream never ends with an empty-error warning.
                    # Re-raise so the run is properly cancelled at the caller.
                    if not _terminal_emitted:
                        await _emit(
                            {
                                "type": "status",
                                "status": "ralph_complete",
                                "reason": (
                                    "cancelled" if isinstance(exc, asyncio.CancelledError) else "lease_violation"
                                ),
                                "iterations": max(iteration - 1, 0),
                                "passed": passed,
                                "total": total,
                                "error": str(exc) or type(exc).__name__,
                                "usage": {
                                    "total_tokens": usage_totals.total_tokens,
                                    "cost_usd": round(usage_totals.cost_usd, 6),
                                },
                            }
                        )
                    raise

            # Ralph loop tool — disabled by default (AGENT_RALPH_ENABLED=False).
            # The implementation below has proven messy and unintuitive, so the
            # planner no longer sees the tool. The closure above + prompts
            # + ``infra/ralph.py`` are intentionally preserved so the feature
            # can be re-enabled by flipping the flag.
            if AGENT_RALPH_ENABLED:
                _ralph_tool = FunctionTool(
                    _ralph_loop_fn,
                    name="ralph_loop",
                    description=(
                        "Spawn an autonomous Ralph loop that implements a PRD "
                        "story-by-story. Each iteration creates a fresh agent that "
                        "picks the next incomplete story, implements it, runs quality "
                        "checks, commits, and marks it as passed. First write the PRD "
                        "to a file (e.g. prd.json), then pass the file path."
                    ),
                )
                # Keep Ralph loop as a direct schema even when PTC is enabled.
                _ralph_tool._ptc_exclude = True
                lead_tools.append(_ralph_tool)

            # ── Assemble planner instructions ────────────────────────────
            from agent_server.engine.prompts import build_planner_instructions  # noqa: C0415

            cli_catalog = build_cli_tool_catalog(tool_toggles)
            if mcp_catalog:
                # Include MCP catalog in the executor/ralph catalog too
                cli_catalog += "\n\n" + mcp_catalog

            planner_instructions = build_planner_instructions(
                user_prefs=user_prefs,
                user_id=user_id,
                session_id=session_id,
                project_custom_instructions=project_custom_instructions or "",
                exo_md_content=exo_md_content,
                mcp_catalog=mcp_catalog,
                is_project_run=is_project_run,
                project_title=project_title,
                project_files=project_files,
            )

            # ── Lifecycle hooks ───────────────────────────────────────────
            from agent_server.engine.harness import build_orchestrator_harness  # noqa: C0415
            from agent_server.engine.knowledge import cleanup_km_state  # noqa: C0415

            lead_context = ExoContext(task_id=run_id, config=ctx_cfg)

            _injected_tool_args = {
                "brief": "A one-sentence preamble describing the purpose of this operation.",
            }

            _planner_hooks = _make_agent_hooks()

            harness = build_orchestrator_harness(
                planner_model=model,
                planner_instructions=planner_instructions,
                all_native_tools=lead_tools,
                memory_store=memory_store,
                skill_registry=skill_registry,
                skill_tool_resolver=skill_tool_resolver,
                hitl_tool=hitl_tool,
                run_id=run_id,
                conversation_id=conversation_id,
                provider=None,  # set after provider resolution below
                max_steps=max_steps,
                hooks=_planner_hooks,
                injected_tool_args=_injected_tool_args,
                context_config=lead_context,
                budget_awareness="per-message",
                guardrail_fn=attach_guardrails,
                executor_ptc=False,
                executor_max_steps=EXECUTOR_MAX_STEPS,
                cli_tool_catalog=cli_catalog,
                ctx_engine_config=ctx_engine_config,
                km_enabled=AGENT_KM_ENABLED,
                user_prefs=user_prefs,
                is_project_run=is_project_run,
                project_title=project_title,
                project_files=project_files,
            )

            runnable = harness

            # ── Harness manifest (component versioning) ─────────────────
            from agent_server.versioning import build_manifest, log_manifest  # noqa: C0415

            _manifest = build_manifest(skill_registry=skill_registry)
            log_manifest(_manifest, prefix=f"Run {run_id}")

            @sync_to_async
            def _persist_manifest() -> None:
                row = SandboxRun.objects.filter(id=run_id).first()
                if row is not None:
                    meta = dict(row.metadata or {})
                    meta["harness_manifest"] = _manifest.to_dict()
                    row.metadata = meta
                    row.save(update_fields=["metadata"])

            await _persist_manifest()

            # Provider is resolved earlier (before KM hooks); wire it onto the
            # harness now that the harness has been constructed.
            harness._provider = provider

            # The planner agent is created lazily inside harness.execute().
            # For hot-swap (inject_message), we expose the harness itself
            # initially.  Once the planner starts, the harness sets
            # self.planner_agent which callers can also use.
            _run_agents[run_id] = harness
            _run_mcp_servers[run_id] = {}
            _active_conversations[conversation_id] = run_id

            # Notify backend that the run has started.
            await sync_run_started(run_id, sandbox_id=sandbox_id)

            # Start the Knowledge Manager continuous loop in parallel
            # with the orchestrator.  Each tick reads the freshest
            # trajectory via ``get_messages_snapshot(conversation_id)``,
            # which is populated by ``vital_info_hook`` on every
            # PRE_LLM_CALL from the planner / executor / ralph worker.
            # Before the first such hook fires the snapshot is empty
            # and the loop short-circuits — safe to start early.
            if AGENT_KM_ENABLED:
                from agent_server.engine.knowledge import start_km_loop  # noqa: C0415

                def _km_messages_provider() -> list:
                    # Read the freshest trajectory from the KM's in-memory
                    # snapshot dict.  The snapshot is populated on every
                    # PRE_LLM_CALL by ``vital_info_hook``, which is installed
                    # on the planner, every executor, and every ralph
                    # worker. This bypasses the fact that
                    # ``harness._ctx.messages`` is never populated on exo's
                    # single-agent code path.
                    return get_messages_snapshot(conversation_id)

                km_loop = start_km_loop(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    provider=provider,
                    model=model,
                    messages_provider=_km_messages_provider,
                    ctx_engine_config=ctx_engine_config,
                )
            else:
                log.info(
                    "Run %s: skipping KM continuous loop (AGENT_KM_ENABLED=false)",
                    run_id,
                )

            # ── Live document preview loop ──────────────────────────────
            # Watches the workspace for office / pdf / markdown changes and
            # pushes synthetic artifact tool_result events through _emit
            # using a stable callId, so the frontend shows a single card
            # that updates in place as the agent builds the document.
            # Gated on LIVE_PREVIEW_ENABLED (default on). The loop lives
            # at the run level, not per-agent, so it survives ralph
            # iterations and sub-agent handoffs without teardown thrash.
            if os.environ.get("LIVE_PREVIEW_ENABLED", "1") not in ("0", "false", "False"):
                from agent_server.engine.live_preview import LivePreviewLoop  # noqa: C0415

                preview_loop = LivePreviewLoop(
                    run_id=run_id,
                    workspace=SANDBOX_WORKSPACE_ROOT,
                    emit=_emit,
                )
                try:
                    await preview_loop.start()
                except Exception:
                    log.warning(
                        "Run %s: live preview loop failed to start",
                        run_id,
                        exc_info=True,
                    )

            async def _stream_agent() -> None:
                nonlocal usage_events_since_sync
                stream_iter = run.stream(
                    runnable,
                    task,
                    detailed=True,
                    provider=provider,
                    conversation_id=conversation_id,
                )
                pending_next: asyncio.Task[Any] | None = None
                stall_count = 0
                # Track the channel's event sequence to detect activity
                # coming from nested/long-running tool calls (e.g. ralph_loop
                # spawning workers that emit via channel but don't advance
                # the planner's own LLM stream).
                last_seen_channel_seq = channel._latest_seq

                try:
                    while True:
                        if pending_next is None:
                            pending_next = asyncio.create_task(stream_iter.__anext__())

                        try:
                            event = await asyncio.wait_for(
                                asyncio.shield(pending_next),
                                timeout=LLM_EVENT_TIMEOUT_SECONDS,
                            )
                            pending_next = None
                            stall_count = 0
                            last_seen_channel_seq = channel._latest_seq
                        except TimeoutError:
                            # If a HITL request is pending for this run, the
                            # stream is intentionally paused waiting on user
                            # input — not a stalled upstream model. Don't
                            # count this toward the stall budget; HITL has
                            # its own HITL_TIMEOUT that will fire if the
                            # user never responds. Without this check the
                            # watchdog kills runs that legitimately called
                            # message(type="ask").
                            if _hitl_pending.get(run_id):
                                log.debug(
                                    "Run %s: stream event timeout ignored — HITL request pending",
                                    run_id,
                                )
                                continue

                            # Nested-tool-call check: the watchdog monitors
                            # the PLANNER'S agent stream specifically. Long-
                            # running tool calls like ralph_loop emit events
                            # through the run channel (_emit) but don't
                            # advance the planner's LLM stream (the planner
                            # is blocked on the tool call's return value).
                            # If channel._latest_seq has advanced since the
                            # last check, the run is clearly alive — the
                            # silence is just "planner waiting on a tool
                            # that's busy doing real work." Without this
                            # check, a multi-hour ralph_loop gets auto-killed
                            # at 6 minutes.
                            current_channel_seq = channel._latest_seq
                            if current_channel_seq > last_seen_channel_seq:
                                log.debug(
                                    "Run %s: planner stream idle but channel "
                                    "advanced %d → %d events — nested tool "
                                    "active, not a stall",
                                    run_id,
                                    last_seen_channel_seq,
                                    current_channel_seq,
                                )
                                last_seen_channel_seq = current_channel_seq
                                stall_count = 0
                                continue

                            stall_count += 1
                            waited_seconds = LLM_EVENT_TIMEOUT_SECONDS * stall_count
                            max_stalls = LLM_EVENT_TIMEOUT_RETRIES + 1
                            if stall_count <= LLM_EVENT_TIMEOUT_RETRIES:
                                log.warning(
                                    "Run %s: no stream event for %.1fs (%d/%d) — waiting for upstream model",
                                    run_id,
                                    waited_seconds,
                                    stall_count,
                                    max_stalls,
                                )
                                continue

                            if pending_next is not None:
                                pending_next.cancel()
                                with suppress(Exception):
                                    await pending_next
                                pending_next = None

                            raise UpstreamModelError(
                                code="llm_call_timeout",
                                message=(
                                    "Upstream model timed out while generating a response "
                                    f"(waited {waited_seconds:.1f}s with no events)"
                                ),
                            )
                        except StopAsyncIteration:
                            pending_next = None
                            break

                        lease_enforcer.check_runtime()

                        payload = event.model_dump()
                        _verbose_event(payload)

                        if payload.get("type") == "usage":
                            update_usage_totals(usage_totals, payload)
                            lease_enforcer.check_usage(usage_totals)
                            usage_events_since_sync += 1
                            await _sync_usage(force=False)

                        # Suppress sub-agent terminal StatusEvents (see _STATUS_SUPPRESS).
                        if payload.get("type") == "status" and payload.get("status") in _STATUS_SUPPRESS:
                            continue

                        await _emit(payload)

                        # ── Context event persistence: when the context engine
                        # summarises or offloads, persist the event to summaries.md
                        # so context can be re-injected into future prompts.
                        if payload.get("type") == "context":
                            _ctx_action = payload.get("action", "")
                            if _ctx_action in ("summarize", "offload"):
                                persist_context_event(
                                    action=_ctx_action,
                                    details=payload.get("details"),
                                )

                        # ── Attachment sync: when message(type=result) returns files,
                        # upload them to S3 and create StoredFile + ConversationFile
                        # records in the shared DB.
                        if payload.get("type") == "tool_result" and payload.get("tool_name") == "message":
                            try:
                                result_data = payload.get("result") or payload.get("content") or {}
                                if isinstance(result_data, str):
                                    try:
                                        result_data = json.loads(result_data)
                                    except (json.JSONDecodeError, ValueError, TypeError):
                                        try:
                                            import ast

                                            result_data = ast.literal_eval(result_data)
                                        except Exception:
                                            result_data = {}
                                if not isinstance(result_data, dict):
                                    result_data = {}
                                metadata = result_data.get("metadata") or {}
                                attachment_files = metadata.get("files") or []
                                # Resolve user_id string → integer owner_id for StoredFile FK
                                _owner_id: int | None = None
                                if user_id:
                                    try:
                                        _owner_id = int(user_id)
                                    except (ValueError, TypeError):
                                        pass
                                for fpath in attachment_files:
                                    await sync_attachment(
                                        file_path=fpath,
                                        conversation_id=conversation_id,
                                        owner_id=_owner_id,
                                    )
                            except Exception:
                                log.warning("Run %s: attachment sync failed", run_id, exc_info=True)
                finally:
                    if pending_next is not None:
                        pending_next.cancel()
                        with suppress(Exception):
                            await pending_next

            if effective_timeout:
                await asyncio.wait_for(_stream_agent(), timeout=effective_timeout)
            else:
                await _stream_agent()

            # Mark completed INSIDE the context so the DB write happens before
            # any cleanup can raise CancelledError during subprocess teardown.
            await _set_run_status("completed")
            await _sync_usage(force=True)
            await _sync_terminal_once(terminal_status="completed")
            await _emit({"type": "run_completed", "run_id": run_id}, force_flush=True)
            log.info("Run completed: %s", run_id)

    except TimeoutError:
        error_code = timeout_error_code
        message = "Run timed out" if error_code != "lease_runtime_exceeded" else "lease_runtime_exceeded"
        log.warning(
            "Run timeout run_id=%s conversation_id=%s code=%s",
            run_id,
            conversation_id,
            error_code,
        )
        await _set_run_status("failed", error=error_code)
        await _sync_usage(force=True)
        await _sync_terminal_once(terminal_status="failed", error=error_code)
        await _emit(
            {
                "type": "run_failed",
                "run_id": run_id,
                "error": message,
                "error_code": error_code,
            },
            force_flush=True,
        )

    except UpstreamModelError as exc:
        log.warning(
            "Run %s: upstream model failure code=%s detail=%s",
            run_id,
            exc.code,
            exc.message,
        )
        await _set_run_status("failed", error=exc.code)
        await _sync_usage(force=True)
        await _sync_terminal_once(terminal_status="failed", error=exc.code)
        await _emit(
            {
                "type": "run_failed",
                "run_id": run_id,
                "error": exc.message,
                "error_code": exc.code,
            },
            force_flush=True,
        )

    except LeaseViolation as exc:
        log.warning(
            "Lease violation run_id=%s conversation_id=%s code=%s usage_total_tokens=%d usage_cost_usd=%.6f",
            run_id,
            conversation_id,
            exc.code,
            usage_totals.total_tokens,
            usage_totals.cost_usd,
        )
        await _set_run_status("failed", error=exc.code)
        await _sync_usage(force=True)
        await _sync_terminal_once(terminal_status="failed", error=exc.code)
        await _emit(
            {
                "type": "run_failed",
                "run_id": run_id,
                "error": exc.code,
                "error_code": exc.code,
            },
            force_flush=True,
        )

    except asyncio.CancelledError:
        try:
            await _set_run_status("cancelled")
            await _sync_usage(force=True)
            await _sync_terminal_once(terminal_status="cancelled")
            await _emit({"type": "run_cancelled", "run_id": run_id}, force_flush=True)
        except Exception:
            log.exception("Error during cancellation cleanup for run %s", run_id)
        log.info("Run cancelled: %s", run_id)
        raise

    except (_GuardrailError, _RailAbortError) as exc:
        log.warning("Run %s: guardrail blocked request: %s", run_id, exc)
        error_code = "guardrail_blocked"
        error_message = "Request blocked by safety filter"
        await _set_run_status("failed", error=error_code)
        await _sync_usage(force=True)
        await _sync_terminal_once(terminal_status="failed", error=error_code)
        await _emit(
            {
                "type": "error",
                "message": error_message,
                "error": error_code,
                "recoverable": True,
            },
            force_flush=True,
        )
        await _emit(
            {
                "type": "run_failed",
                "run_id": run_id,
                "error": error_message,
                "error_code": error_code,
            },
            force_flush=True,
        )

    except Exception as exc:
        log.exception("Run failed: %s", run_id)
        await _set_run_status("failed", error=str(exc))
        await _sync_usage(force=True)
        await _sync_terminal_once(terminal_status="failed", error=str(exc))
        await _emit({"type": "run_failed", "run_id": run_id, "error": str(exc)}, force_flush=True)

    finally:
        # Finalize any in-progress text message
        try:
            await _finalize_text()
        except Exception:
            log.debug("Run %s: _finalize_text failed during cleanup", run_id, exc_info=True)
        if emitted_events:
            log.info("Run %s: persisted %d events (write-ahead)", run_id, emitted_events)

        channel.close()
        _run_channels.pop(run_id, None)
        _run_tasks.pop(run_id, None)
        _hitl_pending.pop(run_id, None)
        _popped_agent = _run_agents.pop(run_id, None)
        _run_mcp_servers.pop(run_id, None)
        _run_mcp_config_paths.pop(run_id, None)
        # Clean up usage tracking and billing caches for this run.
        cleanup_run_usage(run_id)
        unregister_run_usage_totals(run_id)
        _billing_clear_hold_cache(run_id)
        # Stop the Knowledge Manager continuous loop before clearing its
        # per-run state.  ``stop_km_loop`` is a no-op if the loop never
        # started (e.g. an early failure before the start call).
        try:
            from agent_server.engine.knowledge import stop_km_loop  # noqa: C0415

            await stop_km_loop(km_loop)
        except Exception:
            log.debug("stop_km_loop failed during cleanup", exc_info=True)

        # Stop the live document preview loop.  ``stop`` is idempotent and
        # a no-op if the loop never started (early failure, feature gated off).
        if preview_loop is not None:
            try:
                await preview_loop.stop()
            except Exception:
                log.debug("live preview loop stop failed", exc_info=True)

        # Clean up KM per-run state.
        try:
            cleanup_km_state(run_id)
        except Exception:
            pass
        # Clean up per-conversation plan state.
        try:
            from tools.plan import cleanup_plan_state  # noqa: C0415

            cleanup_plan_state(conversation_id)
        except Exception:
            pass
        # Restore BYOM env var overrides to their original values.
        for env_var, original_value in _byom_original_env.items():
            if original_value is None:
                os.environ.pop(env_var, None)
            else:
                os.environ[env_var] = original_value
        # Only remove if this run still owns the conversation slot (a race
        # between two runs on the same conversation_id could overwrite it).
        if _active_conversations.get(conversation_id) == run_id:
            _active_conversations.pop(conversation_id, None)
