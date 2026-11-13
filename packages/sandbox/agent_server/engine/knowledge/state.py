"""In-memory state for the Knowledge Manager.

Every mutable dict, counter, lock, and ContextVar the KM subsystem needs
lives here.  Keeping them in one place makes it obvious what state is
per-conversation vs per-run, what is ephemeral vs what is a cache, and
what belongs in tests' ``clean_state`` fixtures.

None of this persists across process restarts.  The KM's durable store
is the filesystem (`.sukuna/km/`) plus the `VitalInformation` index
table; everything in this file is runtime-only.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from contextvars import ContextVar
from typing import Any

from .models import KMAdvice, KMNudge, KMScope

log = logging.getLogger("knowledge_manager")


# ─────────────────────────────────────────────────────────────────────────
# Re-entry guard
# ─────────────────────────────────────────────────────────────────────────

# Set to True inside a KM run.  Prevents the KM's own context-engine hook
# from recursively firing another KM run when the KM itself hits its own
# context overflow.
_in_km_run: ContextVar[bool] = ContextVar("_in_km_run", default=False)


# ─────────────────────────────────────────────────────────────────────────
# Message snapshot — live trajectory exposed via the PRE_LLM_CALL hook
# ─────────────────────────────────────────────────────────────────────────
#
# The sandbox orchestrator uses exo's single-agent code path
# (``ctx.stream_agent``), which does not populate ``harness._ctx.messages``
# with the planner's / executor's live message list — that only happens on
# the parallel-agent path.  Without a workaround the KM sees an empty
# trajectory on every invocation and effectively does nothing.
#
# The fix:
#
# - ``vital_info_hook`` is already installed as a PRE_LLM_CALL hook on
#   every orchestrator-spawned agent (planner, executor, ralph worker).
# - Exo's PRE_LLM_CALL handler passes the live ``msg_list`` to hooks as
#   the ``messages=`` kwarg.
# - On every firing, ``vital_info_hook`` now captures that list into
#   ``_km_message_snapshots[conversation_id]`` via
#   ``capture_messages_snapshot``.
# - Every downstream consumer (the continuous loop's messages provider,
#   the content-burst hook, the KM prefetch hook) reads from
#   ``get_messages_snapshot(conversation_id)`` instead of reaching into
#   ``agent.messages`` (which doesn't exist on exo agents) or
#   ``harness._ctx.messages`` (which isn't populated on the single-agent
#   path).
#
# One snapshot per conversation is enough: the orchestrator runs one
# agent at a time on the single-agent path, so successive PRE_LLM_CALLs
# naturally overwrite the snapshot with the freshest trajectory.

_km_message_snapshots: dict[str, list] = {}


def capture_messages_snapshot(conversation_id: str, messages: list) -> None:
    """Store the freshest trajectory for a conversation.

    Called from ``vital_info_hook`` on every PRE_LLM_CALL firing (planner,
    executor, ralph worker).  Copies the list so later mutations by exo
    do not race with KM consumers.
    """
    if not conversation_id:
        return
    try:
        _km_message_snapshots[conversation_id] = list(messages or [])
    except Exception:
        # Snapshot capture must never break the hot path.
        log.debug("capture_messages_snapshot: failed", exc_info=True)


def get_messages_snapshot(conversation_id: str) -> list:
    """Return the latest captured trajectory, or an empty list."""
    return list(_km_message_snapshots.get(conversation_id, []))


def clear_messages_snapshot(conversation_id: str) -> None:
    _km_message_snapshots.pop(conversation_id, None)


# ─────────────────────────────────────────────────────────────────────────
# In-flight locks — one per (conversation, scope)
# ─────────────────────────────────────────────────────────────────────────
#
# A worker-scope run should not block an overall-scope run (and vice
# versa): they operate on different windows and do not conflict.  Keying
# the lock on ``(conversation_id, scope)`` lets both scopes run
# concurrently while still deduping concurrent triggers within the same
# scope.

_km_inflight_locks: dict[tuple[str, str], asyncio.Lock] = {}
_km_inflight_locks_mtx = asyncio.Lock()


async def get_km_lock(conversation_id: str, scope: KMScope) -> asyncio.Lock:
    """Return the per-(conversation, scope) in-flight lock."""
    key = (conversation_id, scope)
    async with _km_inflight_locks_mtx:
        lock = _km_inflight_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _km_inflight_locks[key] = lock
        return lock


# ─────────────────────────────────────────────────────────────────────────
# Rate limit — minimum interval between KM runs per (conversation, scope)
# ─────────────────────────────────────────────────────────────────────────

# Non-forced triggers are rate-limited to at most one every N seconds per
# (conversation, scope).  ``force=True`` callers (pre-compression, error
# strikes) bypass the floor.
KM_RUN_MIN_INTERVAL_SEC = 10.0

# Cached advice older than this is considered stale by the PRE_LLM_CALL
# injection hook.
KM_ADVICE_MAX_AGE_SEC = 90.0

_km_last_run_ts: dict[tuple[str, str], float] = {}


def km_run_rate_limited(conversation_id: str, scope: KMScope) -> bool:
    """True when the last run for this (conversation, scope) was too recent."""
    key = (conversation_id, scope)
    last = _km_last_run_ts.get(key, 0.0)
    return (time.time() - last) < KM_RUN_MIN_INTERVAL_SEC


def mark_km_ran(conversation_id: str, scope: KMScope) -> None:
    _km_last_run_ts[(conversation_id, scope)] = time.time()


# The shared per-conversation KM context hook cache + its factory wrapper
# (``get_km_context_hook``) now live in ``agent_server.engine.hooks``,
# alongside ``make_context_engine_hook`` and the other agent hooks.


# ─────────────────────────────────────────────────────────────────────────
# Gates
# ─────────────────────────────────────────────────────────────────────────

# Threshold for ``should_run_km``: at least this many new messages must
# arrive since the last run, or the trigger is skipped.
_KM_SHOULD_RUN_MIN_NEW_MESSAGES = 4

_km_last_message_count: dict[str, int] = {}


def should_run_km(agent_id: str, current_message_count: int) -> bool:
    """Skip guard for KM triggers.

    Returns True only when at least ``_KM_SHOULD_RUN_MIN_NEW_MESSAGES``
    new messages have arrived since the last time this function returned
    True for the same ``agent_id``.  Keeps the multi-step KM from firing
    on every trivial turn.
    """
    last = _km_last_message_count.get(agent_id, 0)
    if current_message_count < last + _KM_SHOULD_RUN_MIN_NEW_MESSAGES:
        return False
    _km_last_message_count[agent_id] = current_message_count
    return True


def cleanup_km_state(run_id: str) -> None:
    """Drop per-run KM state on run completion."""
    _km_last_message_count.pop(run_id, None)
    # The message snapshot is keyed on conversation_id, not run_id, but
    # tests that pass run_id == conversation_id benefit from the same
    # clear.  Safe no-op otherwise.
    _km_message_snapshots.pop(run_id, None)


def is_trivial_window(messages: list) -> bool:
    """Return True when the recent message window has nothing worth
    running the KM on.

    Trivial = no user message, no long assistant text, and no substantial
    tool output in the last ~10 messages.  Cheap pre-check before paying
    for a multi-step KM run.
    """
    if not messages:
        return True

    window = messages[-10:]
    for msg in window:
        role = _msg_attr(msg, "role")
        if role in ("user", "system"):
            return False
        content = _msg_attr(msg, "content")
        if isinstance(content, str) and len(content) > 400:
            return False
    return True


def _msg_attr(msg: Any, name: str) -> Any:
    """Read an attribute from either a dict-shaped or object-shaped message."""
    value = getattr(msg, name, None)
    if value is None and isinstance(msg, dict):
        value = msg.get(name)
    return value


# ─────────────────────────────────────────────────────────────────────────
# Error strike tracking (forces KM write on 3+ consecutive same error)
# ─────────────────────────────────────────────────────────────────────────

# conversation_id -> (error_signature, streak_length)
_km_error_strikes: dict[str, tuple[str, int]] = {}


def record_error_strike(conversation_id: str, error_signature: str) -> bool:
    """Record an observed error.

    Returns True when the same ``error_signature`` has now been seen
    three or more times in a row — callers should force a write-mode run.
    """
    prev = _km_error_strikes.get(conversation_id)
    if prev is None or prev[0] != error_signature:
        _km_error_strikes[conversation_id] = (error_signature, 1)
        return False
    new_count = prev[1] + 1
    _km_error_strikes[conversation_id] = (error_signature, new_count)
    return new_count >= 3


def reset_error_strikes(conversation_id: str) -> None:
    _km_error_strikes.pop(conversation_id, None)


# ─────────────────────────────────────────────────────────────────────────
# Content-burst tracking (3 consecutive heavy tool calls → fire KM)
# ─────────────────────────────────────────────────────────────────────────

_km_content_burst_counters: dict[str, int] = {}
_KM_CONTENT_BURST_THRESHOLD = 3


def record_content_heavy_toolcall(conversation_id: str) -> bool:
    """Increment the content-burst counter.

    Returns True on the Nth consecutive content-heavy call — callers
    should fire a ``content_burst`` write-mode run and call
    ``reset_content_burst``.
    """
    current = _km_content_burst_counters.get(conversation_id, 0) + 1
    _km_content_burst_counters[conversation_id] = current
    return current >= _KM_CONTENT_BURST_THRESHOLD


def reset_content_burst(conversation_id: str) -> None:
    _km_content_burst_counters.pop(conversation_id, None)


# ─────────────────────────────────────────────────────────────────────────
# Active-items version — bumped whenever a KM run writes files
# ─────────────────────────────────────────────────────────────────────────

# Conversations that have had at least one successful file-writing KM
# run.  Kept as a signal for observability; the unified runner stores
# advice regardless of bootstrap state.
_km_has_run_write: set[str] = set()


def mark_wrote(conversation_id: str) -> None:
    _km_has_run_write.add(conversation_id)


def has_ever_written(conversation_id: str) -> bool:
    return conversation_id in _km_has_run_write


# Bumped every time a KM run persists new / updated / superseded files.
# Used to invalidate cached advice implicitly: if the cached entry's
# ``active_items_version`` does not match the current value, it is stale.
_km_active_items_version: dict[str, int] = {}


def bump_active_items_version(conversation_id: str) -> int:
    new_version = _km_active_items_version.get(conversation_id, 0) + 1
    _km_active_items_version[conversation_id] = new_version
    return new_version


def get_active_items_version(conversation_id: str) -> int:
    return _km_active_items_version.get(conversation_id, 0)


# ─────────────────────────────────────────────────────────────────────────
# Advise cache
# ─────────────────────────────────────────────────────────────────────────

# (conversation_id, role) -> latest KMAdvice.
# Populated by the unified runner when it produces non-empty guidance
# blocks.  Read by the PRE_LLM_CALL injection hook.
_km_advise_cache: dict[tuple[str, str], KMAdvice] = {}


def store_advice(conversation_id: str, advice: KMAdvice) -> None:
    """Write the same advice into both role slots of the cache."""
    _km_advise_cache[(conversation_id, "planner")] = advice
    _km_advise_cache[(conversation_id, "executor")] = advice


def get_cached_advice(conversation_id: str, role: str, trajectory_hash: str) -> KMAdvice | None:
    """Strict cache lookup: (conv_id, role, hash, version) must all match."""
    entry = _km_advise_cache.get((conversation_id, role))
    if entry is None:
        return None
    if entry.active_items_version != get_active_items_version(conversation_id):
        return None
    if entry.trajectory_hash != trajectory_hash:
        return None
    return entry


def get_latest_advice(conversation_id: str, role: str) -> KMAdvice | None:
    """Lenient cache lookup: return the latest entry regardless of hash.

    Used by the injection hook as a "stale is better than nothing"
    reader.  Returns ``None`` if the entry is older than
    ``KM_ADVICE_MAX_AGE_SEC``.
    """
    entry = _km_advise_cache.get((conversation_id, role))
    if entry is None:
        return None
    if (time.time() - entry.generated_at) > KM_ADVICE_MAX_AGE_SEC:
        return None
    return entry


def invalidate_advise_cache(
    conversation_id: str,
    *,
    reason: str,
    role: str = "both",
) -> None:
    """Drop cached advice for a conversation and log the reason."""
    if role in ("planner", "both"):
        _km_advise_cache.pop((conversation_id, "planner"), None)
    if role in ("executor", "both"):
        _km_advise_cache.pop((conversation_id, "executor"), None)
    log.debug(
        "invalidate_advise_cache: conv=%s reason=%s role=%s",
        conversation_id[:8],
        reason,
        role,
    )


# ─────────────────────────────────────────────────────────────────────────
# Trajectory hash
# ─────────────────────────────────────────────────────────────────────────

TRAJECTORY_HASH_TAIL = 8


def trajectory_hash(messages: list, tail: int = TRAJECTORY_HASH_TAIL) -> str:
    """Cheap hash of the last N messages for cache keying.

    The hash captures role + first ~300 chars of content per message,
    which is enough to detect meaningful drift without being so coarse
    that cosmetic changes force a refresh.
    """
    if not messages:
        return "empty"

    window = messages[-tail:]
    parts: list[str] = []
    for msg in window:
        role = _msg_attr(msg, "role")
        content = _msg_attr(msg, "content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        parts.append(f"{role}:{content[:300]}")
    blob = "||".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(blob).hexdigest()[:16]


# ─────────────────────────────────────────────────────────────────────────
# Nudge store
# ─────────────────────────────────────────────────────────────────────────

# Pending nudges per conversation.  Consumed-on-inject: ``pop_nudges``
# returns the matching items and removes them from the queue.
_km_pending_nudges: dict[str, list[KMNudge]] = {}


def push_nudge(conversation_id: str, nudge: KMNudge) -> None:
    """Queue a nudge for later consumption by the injection hook."""
    _km_pending_nudges.setdefault(conversation_id, []).append(nudge)
    log.info(
        "km_nudge pushed: conv=%s target=%s urgency=%s title=%s",
        conversation_id[:8],
        nudge.target_role,
        nudge.urgency,
        nudge.title,
    )


def pop_nudges(conversation_id: str, role: str) -> list[KMNudge]:
    """Return and remove all nudges matching ``role`` (or ``both``)."""
    queue = _km_pending_nudges.get(conversation_id)
    if not queue:
        return []
    matching: list[KMNudge] = []
    remaining: list[KMNudge] = []
    for nudge in queue:
        if nudge.target_role == role or nudge.target_role == "both":
            matching.append(nudge)
        else:
            remaining.append(nudge)
    if remaining:
        _km_pending_nudges[conversation_id] = remaining
    else:
        _km_pending_nudges.pop(conversation_id, None)
    return matching


def peek_nudges(conversation_id: str) -> list[KMNudge]:
    """Return a snapshot of pending nudges without consuming them."""
    return list(_km_pending_nudges.get(conversation_id, []))


def clear_nudges(conversation_id: str) -> None:
    _km_pending_nudges.pop(conversation_id, None)


# ─────────────────────────────────────────────────────────────────────────
# Test-support helpers (let tests reset everything between cases)
# ─────────────────────────────────────────────────────────────────────────


def _reset_all_state() -> None:
    """Clear every module-level dict / set / counter.

    Intended for test fixtures.  DO NOT call this from production code —
    it will wipe live conversations' state.
    """
    _km_last_message_count.clear()
    _km_inflight_locks.clear()
    _km_last_run_ts.clear()
    _km_message_snapshots.clear()
    _km_error_strikes.clear()
    _km_content_burst_counters.clear()
    _km_has_run_write.clear()
    _km_active_items_version.clear()
    _km_advise_cache.clear()
    _km_pending_nudges.clear()

    # Clear the KM context hook cache that now lives alongside the other
    # agent hooks in ``agent_server.engine.hooks``.  Lazy import keeps
    # state.py free of a back-edge on hooks.py.
    from agent_server.engine.hooks import _km_context_hooks  # noqa: C0415,PLC0415

    _km_context_hooks.clear()
