"""Knowledge Manager subsystem — public API.

A single unified KM runner (``run_km``) replaces the old
write / advise / steer split.  It emits a single ``KMOutput`` per
invocation covering file writes, nudges, and role-scoped guidance
blocks all at once.  Two scopes select which trajectory window the
runner sees:

- ``worker``  — the executor's or ralph worker's own context, with a
                synthesised vital frame prepended
- ``overall`` — the planner's full orchestration view

The package is split by concern:

- ``prompts``  — ``KM_BASE_INSTRUCTIONS`` + ``KM_TASK_SUFFIX`` (the
                 stable system prompt used for KV-cache-friendly runs)
- ``models``   — pydantic output types (``KMOutput``, ``KMAdvice``,
                 ``KMNudge``) and type literals
- ``state``    — in-memory caches, locks, counters, gates, nudge
                 queue, trajectory hash, message snapshot
- ``runner``   — ``run_km`` (the unified runner)
- ``advise``   — ``detect_role`` + ``format_injection`` (pure helpers;
                 the PRE_/POST_LLM_CALL hook factories that consume
                 them live in ``agent_server.engine.hooks``)
- ``loop``     — ``KMContinuousLoop`` background ticker

All KM-facing agent hooks (``make_vital_info_hook``,
``make_km_prefetch_hook``, ``make_content_burst_hook``,
``get_km_context_hook``, ``CONTENT_HEAVY_TOOLS``) are centralised in
``agent_server.engine.hooks``; import them from there.

Everything below is re-exported so existing call sites that imported
from ``agent_server.engine.knowledge`` continue to work.
"""

from __future__ import annotations

__version__ = "0.3.0"

# ── Prompts ─────────────────────────────────────────────────────────────
# ── State (private surface — used by tests) ────────────────────────────
# Exposed as module attributes so tests can reset state between cases
# via ``_reset_all_state`` without reaching into the submodule directly.
from . import state as _state

# ── Pure helpers consumed by the KM hook factories ─────────────────────
from .advise import (
    detect_role,
    format_injection,
)

# ── Continuous loop ─────────────────────────────────────────────────────
from .loop import KMContinuousLoop, start_km_loop, stop_km_loop

# ── Models ──────────────────────────────────────────────────────────────
from .models import (
    KMAdvice,
    KMNudge,
    KMOutput,
    KMScope,
    KMTrigger,
    NudgeUrgency,
    TargetRole,
)
from .prompts import (
    KM_BASE_INSTRUCTIONS,
    KM_TASK_SUFFIX,
)

# ── Runner ──────────────────────────────────────────────────────────────
from .runner import KM_MAX_STEPS, run_km

# ── State (public surface) ──────────────────────────────────────────────
from .state import (  # noqa: F401
    KM_ADVICE_MAX_AGE_SEC,
    KM_RUN_MIN_INTERVAL_SEC,
    _in_km_run,
    _km_active_items_version,
    _km_advise_cache,
    _km_has_run_write,
    _km_inflight_locks,
    _km_last_run_ts,
    _km_message_snapshots,
    _km_pending_nudges,
    _reset_all_state,
    bump_active_items_version,
    capture_messages_snapshot,
    cleanup_km_state,
    clear_messages_snapshot,
    clear_nudges,
    get_active_items_version,
    get_cached_advice,
    get_km_lock,
    get_latest_advice,
    get_messages_snapshot,
    has_ever_written,
    invalidate_advise_cache,
    is_trivial_window,
    km_run_rate_limited,
    mark_km_ran,
    mark_wrote,
    peek_nudges,
    pop_nudges,
    push_nudge,
    record_content_heavy_toolcall,
    record_error_strike,
    reset_content_burst,
    reset_error_strikes,
    should_run_km,
    store_advice,
    trajectory_hash,
)

__all__ = [
    # Prompts
    "KM_BASE_INSTRUCTIONS",
    "KM_TASK_SUFFIX",
    # Models
    "KMOutput",
    "KMAdvice",
    "KMNudge",
    "KMTrigger",
    "KMScope",
    "TargetRole",
    "NudgeUrgency",
    # State helpers
    "should_run_km",
    "cleanup_km_state",
    "is_trivial_window",
    "trajectory_hash",
    "record_error_strike",
    "reset_error_strikes",
    "record_content_heavy_toolcall",
    "reset_content_burst",
    "mark_wrote",
    "has_ever_written",
    "bump_active_items_version",
    "get_active_items_version",
    "get_cached_advice",
    "get_latest_advice",
    "store_advice",
    "invalidate_advise_cache",
    "push_nudge",
    "pop_nudges",
    "peek_nudges",
    "clear_nudges",
    "capture_messages_snapshot",
    "get_messages_snapshot",
    "clear_messages_snapshot",
    "get_km_lock",
    "km_run_rate_limited",
    "mark_km_ran",
    "KM_ADVICE_MAX_AGE_SEC",
    "KM_RUN_MIN_INTERVAL_SEC",
    # Runner
    "run_km",
    "KM_MAX_STEPS",
    # Pure helpers (hook factories live in agent_server.engine.hooks)
    "detect_role",
    "format_injection",
    # Continuous loop
    "KMContinuousLoop",
    "start_km_loop",
    "stop_km_loop",
    # Test support
    "_reset_all_state",
]
