"""Notify channels, per-run state, Google OAuth cache, lease enforcement, and usage metering."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from exo.memory.backends.postgres import PostgresMemoryStore
from ninja import Router

log = logging.getLogger("agent_server")

if TYPE_CHECKING:
    from exo import Agent as AgentType


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  DJANGO NINJA ROUTERS                                                      ║
# ║                                                                            ║
# ║  Router instances that group endpoints by domain. Each router is imported  ║
# ║  and mounted by urls.py onto the NinjaAPI application.                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def _get_auth_user_id(request) -> str | None:
    """Extract the authenticated user's ID from the request.

    Returns the user_id as a string when authenticated via bearer token
    (Django user) or JWT stream token (frontend direct-to-sandbox).
    Returns None when authenticated via static API key (backend RPC —
    the backend already scopes requests, so the sandbox should not filter
    further).
    """
    auth = getattr(request, "auth", None)
    if auth is None or auth == "api_key_user":
        return None  # API key auth — no user scoping
    if isinstance(auth, dict) and auth.get("type") == "jwt_stream":
        user_id = auth.get("user_id")
        return str(user_id) if user_id else None
    # Bearer token auth — auth is a DjangoUser instance
    return str(getattr(auth, "id", "")) or None


from agent_server.auth import default_auth, stream_auth  # noqa: E402

runs_router = Router(tags=["runs"], auth=stream_auth)
streaming_router = Router(tags=["streaming"], auth=stream_auth)
hitl_router = Router(tags=["hitl"], auth=stream_auth)
mcp_router = Router(tags=["mcp"], auth=stream_auth)
files_router = Router(tags=["files"], auth=stream_auth)
skills_router = Router(tags=["skills"])
health_router = Router(tags=["health"], auth=[])
# integrations_router carries per-endpoint auth (signature-based for webhooks,
# bearer-based for JSON API calls).  Its router-level default is
# bearer/static-key; webhooks override via ``auth=`` per endpoint.
integrations_router = Router(tags=["integrations"], auth=default_auth)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  NOTIFY CHANNEL — Lightweight per-run wake signal for SSE streaming        ║
# ║                                                                            ║
# ║  RunNotifyChannel carries NO payload — it only wakes SSE waiters so they   ║
# ║  read new events from the DB (the single source of truth).  Each SSE      ║
# ║  connection creates its own asyncio.Event waiter via create_waiter().      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class RunNotifyChannel:
    """Lightweight per-run notification channel for SSE streaming.

    No payload, no buffering, no truncation.  When ``_emit()`` writes an event
    to the DB it calls ``notify(seq)`` which sets every waiter's Event, waking
    all SSE connections.  Each connection then reads from the DB using its own
    cursor (``?after=<seq>``).
    """

    def __init__(self) -> None:
        self._waiters: list[asyncio.Event] = []
        self._closed = False
        self._latest_seq = -1

    def notify(self, seq: int) -> None:
        """Wake all SSE waiters — new event available at ``seq``."""
        self._latest_seq = seq
        for w in self._waiters:
            w.set()

    def create_waiter(self) -> asyncio.Event:
        """Create a per-connection waiter.  Caller must ``remove_waiter()`` on disconnect."""
        e = asyncio.Event()
        self._waiters.append(e)
        return e

    def remove_waiter(self, e: asyncio.Event) -> None:
        """Remove a waiter on SSE disconnect."""
        try:
            self._waiters.remove(e)
        except ValueError:
            pass

    def close(self) -> None:
        """Signal run completion — wake all waiters so they drain final events and exit."""
        self._closed = True
        for w in self._waiters:
            w.set()

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def latest_seq(self) -> int:
        return self._latest_seq


# ── Per-run in-process state ──────────────────────────────────────────────────

_run_channels: dict[str, RunNotifyChannel] = {}
_hitl_pending: dict[str, dict[str, asyncio.Future[str]]] = {}
_run_tasks: dict[str, asyncio.Task[None]] = {}

# Live Agent instances — populated while a run is active; used for hot-swap
# and live message injection.
_run_agents: dict[str, AgentType] = {}
# server_name → list of tool names that came from that server.
# Only tracks dynamically-added servers (not the initial ones from StartRunRequest).
_run_mcp_servers: dict[str, dict[str, list[str]]] = {}
# run_id → Path to the mcp.json config for exo-mcp-cli offloading.
_run_mcp_config_paths: dict[str, str] = {}

# conversation_id → run_id for currently active runs.
# Used to detect when a new message targets a conversation that already has a
# running agent, so it can be injected instead of spawning a parallel run.
_active_conversations: dict[str, str] = {}

# Module-level reference set by init_server() at startup.
_memory_store: PostgresMemoryStore | None = None


def _format_sse_event(event_type: str, data: dict[str, Any], event_id: int | None = None) -> str:
    """Format a single SSE event with optional id field for Last-Event-ID resumption."""
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event_type}")
    parts.append(f"data: {json.dumps(data)}")
    parts.append("")
    parts.append("")
    return "\n".join(parts)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  LEASE ENFORCEMENT — Runtime/token/cost limits                             ║
# ║                                                                            ║
# ║  The lease system enforces per-run resource limits set by the backend      ║
# ║  (via run metadata).  LeaseEnforcer is called on every agent event to      ║
# ║  check runtime and on every usage event to check token/cost limits.        ║
# ║  If a limit is exceeded, LeaseViolation is raised and the run fails.       ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@dataclass(slots=True)
class LeaseLimits:
    max_runtime_seconds: float | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None


@dataclass(slots=True)
class UsageTotals:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    native_tool_calls: int = 0
    mcp_tool_calls: int = 0


class LeaseViolation(RuntimeError):
    """Raised when run usage exceeds one of the lease constraints."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_number(raw: Any) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        value = raw.strip()
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _parse_positive_float(raw: Any) -> float | None:
    parsed = _parse_number(raw)
    if parsed is None or parsed < 0:
        return None
    return parsed


def _parse_positive_int(raw: Any) -> int | None:
    parsed = _parse_number(raw)
    if parsed is None:
        return None
    val = int(parsed)
    if val < 0:
        return None
    return val


def parse_lease_limits(run_metadata: dict[str, Any] | None) -> LeaseLimits:
    """Extract lease limits from run metadata.

    Supports both flat metadata (``metadata.max_runtime_seconds``) and nested
    ``metadata.lease.max_runtime_seconds`` layouts.
    """
    if not isinstance(run_metadata, dict):
        return LeaseLimits()

    source = run_metadata
    lease_candidate = run_metadata.get("lease")
    if isinstance(lease_candidate, dict):
        source = lease_candidate

    return LeaseLimits(
        max_runtime_seconds=_parse_positive_float(source.get("max_runtime_seconds")),
        max_total_tokens=_parse_positive_int(source.get("max_total_tokens")),
        max_cost_usd=_parse_positive_float(source.get("max_cost_usd")),
    )


class LeaseEnforcer:
    """Checks runtime and usage counters against lease limits.

    Created once per run with the limits extracted from run metadata.
    ``check_runtime()`` is called on every agent event; ``check_usage()``
    is called after every usage event.
    """

    def __init__(self, limits: LeaseLimits, *, started_monotonic: float | None = None) -> None:
        self._limits = limits
        self._started = time.perf_counter() if started_monotonic is None else started_monotonic

    @property
    def limits(self) -> LeaseLimits:
        return self._limits

    def check_runtime(self, *, now_monotonic: float | None = None) -> None:
        limit = self._limits.max_runtime_seconds
        if limit is None:
            return
        now = time.perf_counter() if now_monotonic is None else now_monotonic
        elapsed = now - self._started
        if elapsed > limit:
            raise LeaseViolation(
                "lease_runtime_exceeded",
                f"Lease runtime exceeded: elapsed={elapsed:.3f}s limit={limit:.3f}s",
            )

    def check_usage(self, usage: UsageTotals) -> None:
        token_limit = self._limits.max_total_tokens
        if token_limit is not None and usage.total_tokens > token_limit:
            raise LeaseViolation(
                "lease_tokens_exceeded",
                f"Lease token limit exceeded: total_tokens={usage.total_tokens} limit={token_limit}",
            )
        cost_limit = self._limits.max_cost_usd
        if cost_limit is not None and usage.cost_usd > cost_limit:
            raise LeaseViolation(
                "lease_cost_exceeded",
                f"Lease cost limit exceeded: cost_usd={usage.cost_usd:.6f} limit={cost_limit:.6f}",
            )


# ── Usage metering helpers ────────────────────────────────────────────────────


def _meter_to_int(raw: Any) -> int | None:
    """Coerce a raw value to int for token metering, returning None for unparseable values."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str):
        val = raw.strip()
        if not val:
            return None
        try:
            return int(float(val))
        except ValueError:
            return None
    return None


def _meter_to_float(raw: Any) -> float | None:
    """Coerce a raw value to float for cost metering, returning None for unparseable values."""
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        val = raw.strip()
        if not val:
            return None
        try:
            return float(val)
        except ValueError:
            return None
    return None


# ── Per-agent estimated-usage side-channel ───────────────────────────────────
#
# When an LLM provider returns a usage event with zero tokens (some local
# Ollama / vLLM endpoints don't report usage), our POST_LLM_CALL hook
# (``engine.hooks.make_usage_estimate_hook``) populates this dict with a
# structural estimate keyed by agent name. ``update_usage_totals`` consumes
# the estimate when it sees a zero-token event and pops the entry so each
# estimate is used at most once.
#
# Process-wide (single asyncio loop) — no lock required.

_pending_estimates: dict[str, dict[str, Any]] = {}


def stash_estimated_usage(
    agent_name: str,
    *,
    input_tokens: int,
    output_tokens: int,
    model: str = "",
) -> None:
    """Record a fallback estimate for the next zero-usage event from *agent_name*."""
    if not agent_name:
        return
    _pending_estimates[agent_name] = {
        "input_tokens": max(int(input_tokens), 0),
        "output_tokens": max(int(output_tokens), 0),
        "model": model or "",
    }


def _pop_estimate(agent_name: str) -> dict[str, Any] | None:
    return _pending_estimates.pop(agent_name, None) if agent_name else None


def update_usage_totals(usage: UsageTotals, event: dict[str, Any]) -> UsageTotals:
    """Best-effort usage parser for exo usage events.

    Handles multiple naming conventions (input_tokens vs prompt_tokens,
    cost_usd vs cost) and both flat and nested ``usage`` sub-dicts.

    Two billing fallbacks kick in when the upstream event is incomplete
    (typical for local Ollama / vLLM and any provider that omits cost):

      1. **Token estimate** — if the event reports 0 input + 0 output
         tokens but ``stash_estimated_usage()`` left a pending estimate
         for this agent, consume that estimate.
      2. **Cost derivation** — if we end up with a non-zero token delta
         but no ``cost_usd``, compute one via
         :func:`agent_server.engine.pricing.derive_cost`.
    """
    source = event.get("usage") if isinstance(event.get("usage"), dict) else event

    input_tokens = _meter_to_int(source.get("input_tokens"))
    if input_tokens is None:
        input_tokens = _meter_to_int(source.get("prompt_tokens"))

    output_tokens = _meter_to_int(source.get("output_tokens"))
    if output_tokens is None:
        output_tokens = _meter_to_int(source.get("completion_tokens"))

    total_tokens = _meter_to_int(source.get("total_tokens"))

    # Model can live on the event or on the nested usage sub-dict.
    model = (
        event.get("model")
        if isinstance(event, dict) and event.get("model")
        else source.get("model")
        if isinstance(source, dict)
        else ""
    ) or ""

    # Fallback #1: zero-usage event → consume any stashed estimate for this agent.
    used_estimate = False
    if (input_tokens or 0) == 0 and (output_tokens or 0) == 0 and (total_tokens or 0) == 0:
        agent_name = (event.get("agent_name") if isinstance(event, dict) else "") or ""
        estimate = _pop_estimate(agent_name)
        if estimate is not None:
            input_tokens = estimate["input_tokens"]
            output_tokens = estimate["output_tokens"]
            if not model:
                model = estimate.get("model", "")
            used_estimate = True

    if input_tokens is not None:
        usage.input_tokens += max(input_tokens, 0)
    if output_tokens is not None:
        usage.output_tokens += max(output_tokens, 0)

    explicit_delta = (input_tokens or 0) + (output_tokens or 0)
    if explicit_delta > 0:
        usage.total_tokens += explicit_delta
        if total_tokens is not None and total_tokens >= usage.total_tokens:
            usage.total_tokens = total_tokens
    elif total_tokens is not None:
        if total_tokens >= usage.total_tokens:
            usage.total_tokens = total_tokens
        else:
            usage.total_tokens += max(total_tokens, 0)

    usage.total_tokens = max(usage.total_tokens, usage.input_tokens + usage.output_tokens)

    cost = _meter_to_float(source.get("cost_usd"))
    if cost is None:
        cost = _meter_to_float(source.get("cost"))

    # Fallback #2: provider didn't price this step — derive from tokens.
    if cost is None and explicit_delta > 0 and model:
        try:
            from agent_server.engine.pricing import derive_cost  # noqa: C0415

            derived = derive_cost(model, int(input_tokens or 0), int(output_tokens or 0))
        except Exception:  # noqa: BLE001
            derived = 0.0
        if derived > 0:
            usage.cost_usd += derived
            cost = None  # already applied; skip the merge below

    if cost is not None:
        if cost >= usage.cost_usd:
            usage.cost_usd = cost
        else:
            usage.cost_usd += max(cost, 0.0)

    if used_estimate:
        # One log line per fallback so operators can see when local /
        # zero-usage providers are being billed via estimates.
        import logging  # noqa: C0415

        logging.getLogger(__name__).info(
            "billing fallback: estimated %d in / %d out tokens for agent %r (model=%r, derived $%.6f)",
            input_tokens or 0,
            output_tokens or 0,
            event.get("agent_name", ""),
            model,
            usage.cost_usd,
        )

    return usage


# ── Per-run UsageTotals registry ──────────────────────────────────────────────
#
# Sub-agents that execute *outside* the main run loop (notably the Knowledge
# Manager, which is invoked via fire-and-forget ``run()`` from hooks and the
# background loop) cannot reach the ``usage_totals`` dataclass owned by
# ``engine/run.py``. Without this registry their tokens are never billed.
#
# The main run registers its ``UsageTotals`` + ``sandbox_id`` under ``run_id``
# at startup and unregisters in the ``finally`` block. Sub-agents look up the
# entry by ``run_id``, fold their own token counts into the shared totals, and
# trigger a backend sync. The event loop is single-threaded so the in-place
# mutation is safe without a lock.


@dataclass(slots=True)
class RunUsageContext:
    usage_totals: UsageTotals
    sandbox_id: str | None


_run_usage_totals: dict[str, RunUsageContext] = {}


def register_run_usage_totals(
    run_id: str,
    usage_totals: UsageTotals,
    *,
    sandbox_id: str | None,
) -> None:
    """Register the main run's UsageTotals so sub-agents can bill into it."""
    _run_usage_totals[run_id] = RunUsageContext(
        usage_totals=usage_totals,
        sandbox_id=sandbox_id,
    )


def get_run_usage_context(run_id: str) -> RunUsageContext | None:
    """Return the registered UsageTotals context for ``run_id`` if any."""
    return _run_usage_totals.get(run_id)


def unregister_run_usage_totals(run_id: str) -> None:
    """Drop the registry entry for ``run_id`` (idempotent)."""
    _run_usage_totals.pop(run_id, None)
