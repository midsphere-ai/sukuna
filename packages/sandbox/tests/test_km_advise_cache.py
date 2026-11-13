"""Tests for the Knowledge Manager cache, snapshot, and injection helpers.

These cover the pure-Python layer that sits between Exo hooks and the
unified ``run_km`` runner:

- message snapshot capture / read (the fix for the silent-KM bug)
- strict cache lookup: (conversation_id, role, trajectory_hash,
  active_items_version)
- lenient cache lookup: ``get_latest_advice`` honours the freshness TTL
- invalidation on handoff / write-persisted / selected role
- version bump invalidates implicitly
- role detection from ``agent.name`` — including ralph workers
- trajectory hash is deterministic and only sensitive to the last N
  messages
- nudge push / pop flow
- ``format_injection`` composes role-scoped blocks with zero KM
  branding leakage
- ``run_km`` early-return gates (trivial window, rate limit, re-entry)
"""

from __future__ import annotations

import pytest

from agent_server.engine.knowledge import (
    KMAdvice,
    KMNudge,
    KMOutput,
    _reset_all_state,
    capture_messages_snapshot,
    detect_role,
    format_injection,
    get_cached_advice,
    get_km_lock,
    get_latest_advice,
    get_messages_snapshot,
    has_ever_written,
    invalidate_advise_cache,
    km_run_rate_limited,
    mark_km_ran,
    mark_wrote,
    peek_nudges,
    pop_nudges,
    push_nudge,
    run_km,
    store_advice,
    trajectory_hash,
)
from agent_server.engine.knowledge import state as km_state


@pytest.fixture(autouse=True)
def clean_state() -> None:
    """Wipe every piece of KM state between cases."""
    _reset_all_state()
    yield
    _reset_all_state()


# ─────────────────────────────────────────────────────────────────────────
# Role detection
# ─────────────────────────────────────────────────────────────────────────


class _FakeAgent:
    def __init__(self, name: str) -> None:
        self.name = name


def test_detect_role_planner() -> None:
    assert detect_role(_FakeAgent("planner")) == "planner"


def test_detect_role_executor_with_uuid_suffix() -> None:
    assert detect_role(_FakeAgent("executor_abc123")) == "executor"


def test_detect_role_ralph_worker() -> None:
    """Ralph worker agents share the executor cache slot and nudge role."""
    assert detect_role(_FakeAgent("ralph-worker-3")) == "executor"


def test_detect_role_knowledge_manager_is_other() -> None:
    assert detect_role(_FakeAgent("knowledge_manager")) == "other"


def test_detect_role_missing_name_is_other() -> None:
    assert detect_role(_FakeAgent("")) == "other"


# ─────────────────────────────────────────────────────────────────────────
# Message snapshot — the fix for the silent-KM bug
# ─────────────────────────────────────────────────────────────────────────


def test_get_messages_snapshot_empty_before_capture() -> None:
    """A conversation that has never had a PRE_LLM_CALL fire returns []."""
    assert get_messages_snapshot("conv-fresh") == []


def test_capture_then_get_snapshot_roundtrips() -> None:
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]
    capture_messages_snapshot("conv-1", msgs)
    snap = get_messages_snapshot("conv-1")
    assert snap == msgs


def test_capture_snapshot_is_defensive_copy() -> None:
    """Mutations to the original list after capture must not leak through."""
    msgs = [{"role": "user", "content": "hello"}]
    capture_messages_snapshot("conv-1", msgs)
    msgs.append({"role": "user", "content": "mutation"})
    snap = get_messages_snapshot("conv-1")
    assert len(snap) == 1
    assert snap[0]["content"] == "hello"


def test_capture_snapshot_overwrites_prior() -> None:
    """Successive PRE_LLM_CALLs replace the snapshot with the freshest."""
    capture_messages_snapshot("conv-1", [{"role": "user", "content": "old"}])
    capture_messages_snapshot("conv-1", [{"role": "user", "content": "new"}])
    snap = get_messages_snapshot("conv-1")
    assert len(snap) == 1
    assert snap[0]["content"] == "new"


def test_capture_snapshot_is_per_conversation() -> None:
    capture_messages_snapshot("conv-a", [{"role": "user", "content": "A"}])
    capture_messages_snapshot("conv-b", [{"role": "user", "content": "B"}])
    assert get_messages_snapshot("conv-a")[0]["content"] == "A"
    assert get_messages_snapshot("conv-b")[0]["content"] == "B"


def test_capture_empty_conversation_id_is_noop() -> None:
    """Empty conversation_id must not silently pollute the global slot."""
    capture_messages_snapshot("", [{"role": "user", "content": "x"}])
    assert get_messages_snapshot("") == []


# ─────────────────────────────────────────────────────────────────────────
# Trajectory hash
# ─────────────────────────────────────────────────────────────────────────


def test_trajectory_hash_deterministic() -> None:
    msgs = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    assert trajectory_hash(msgs) == trajectory_hash(msgs)


def test_trajectory_hash_changes_with_content() -> None:
    a = trajectory_hash([{"role": "user", "content": "A"}])
    b = trajectory_hash([{"role": "user", "content": "B"}])
    assert a != b


def test_trajectory_hash_empty_is_stable() -> None:
    assert trajectory_hash([]) == "empty"


def test_trajectory_hash_uses_last_N_messages_only() -> None:
    """Old messages outside the tail window must not affect the hash."""
    tail = [{"role": "user", "content": f"msg-{i}"} for i in range(10, 18)]
    with_old = [{"role": "system", "content": "ancient"}] + tail
    without_old = tail
    assert trajectory_hash(with_old) == trajectory_hash(without_old)


# ─────────────────────────────────────────────────────────────────────────
# run_km early-return gates
# ─────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_km_returns_neutral_on_trivial_window() -> None:
    """run_km short-circuits on empty / trivial trajectories without
    touching the LLM or the store."""
    result = await run_km(
        conversation_id="conv-trivial",
        run_id="r1",
        messages=[],
        provider=None,
        model="claude",
        trigger="manual",
    )
    assert isinstance(result, KMOutput)
    assert result.nothing_to_do is True
    assert result.is_silent()


@pytest.mark.asyncio
async def test_run_km_returns_neutral_when_rate_limited() -> None:
    """After marking a recent run, a non-forced call for the same
    (conversation, scope) short-circuits immediately."""
    # Pass enough messages to clear the should_run_km threshold AND
    # the is_trivial_window check.  One substantial user message does it.
    messages = [{"role": "user", "content": "substantial user input " * 40}] + [
        {"role": "assistant", "content": "substantial assistant reply " * 40} for _ in range(5)
    ]
    mark_km_ran("conv-rate", "overall")
    assert km_run_rate_limited("conv-rate", "overall") is True
    result = await run_km(
        conversation_id="conv-rate",
        run_id="r1",
        messages=messages,
        provider=None,
        model="claude",
        trigger="manual",
    )
    assert result.nothing_to_do is True
    assert "rate limited" in (result.summary or "")


@pytest.mark.asyncio
async def test_run_km_reentry_guard_blocks_nested_calls() -> None:
    """A run_km invocation inside another run_km invocation returns
    immediately without touching the LLM."""
    from agent_server.engine.knowledge.state import _in_km_run

    token = _in_km_run.set(True)
    try:
        result = await run_km(
            conversation_id="conv-nested",
            run_id="r1",
            messages=[{"role": "user", "content": "x"}],
            provider=None,
            model="claude",
            trigger="manual",
        )
    finally:
        _in_km_run.reset(token)
    assert result.nothing_to_do is True
    assert "re-entry" in (result.summary or "")


@pytest.mark.asyncio
async def test_run_km_worker_and_overall_scopes_have_independent_locks() -> None:
    """Worker-scope and overall-scope runs for the same conversation
    use different in-flight locks."""
    worker_lock = await get_km_lock("conv-1", "worker")
    overall_lock = await get_km_lock("conv-1", "overall")
    assert worker_lock is not overall_lock
    # Same scope returns the same lock.
    worker_lock_again = await get_km_lock("conv-1", "worker")
    assert worker_lock is worker_lock_again


# ─────────────────────────────────────────────────────────────────────────
# Bootstrap tracking (observability only; no gate)
# ─────────────────────────────────────────────────────────────────────────


def test_has_ever_written_tracks_mark_wrote() -> None:
    assert has_ever_written("conv-1") is False
    mark_wrote("conv-1")
    assert has_ever_written("conv-1") is True


# ─────────────────────────────────────────────────────────────────────────
# Strict cache lookup (trajectory + version)
# ─────────────────────────────────────────────────────────────────────────


def test_cache_miss_when_empty() -> None:
    assert get_cached_advice("conv-1", "planner", "hash-x") is None


def test_cache_hit_when_all_keys_match() -> None:
    km_state._km_active_items_version["conv-1"] = 3
    store_advice(
        "conv-1",
        KMAdvice(
            for_planner="## plan",
            for_executor="",
            trajectory_hash="hash-x",
            active_items_version=3,
        ),
    )
    hit = get_cached_advice("conv-1", "planner", "hash-x")
    assert hit is not None
    assert hit.for_planner == "## plan"


def test_cache_miss_when_trajectory_hash_differs() -> None:
    km_state._km_active_items_version["conv-1"] = 3
    store_advice(
        "conv-1",
        KMAdvice(
            for_planner="old",
            trajectory_hash="old-hash",
            active_items_version=3,
        ),
    )
    assert get_cached_advice("conv-1", "planner", "new-hash") is None


def test_cache_miss_when_version_bumped() -> None:
    km_state._km_active_items_version["conv-1"] = 1
    store_advice(
        "conv-1",
        KMAdvice(
            for_planner="v1",
            trajectory_hash="h",
            active_items_version=1,
        ),
    )
    # A write-mode run bumps the version.
    km_state._km_active_items_version["conv-1"] = 2
    assert get_cached_advice("conv-1", "planner", "h") is None


# ─────────────────────────────────────────────────────────────────────────
# Lenient cache lookup (the PRE_LLM_CALL hook's hot-path reader)
# ─────────────────────────────────────────────────────────────────────────


def test_get_latest_advice_returns_entry_ignoring_hash() -> None:
    store_advice(
        "conv-1",
        KMAdvice(
            for_executor="stale but present",
            trajectory_hash="old",
            active_items_version=1,
        ),
    )
    stale = get_latest_advice("conv-1", "executor")
    assert stale is not None
    assert stale.for_executor == "stale but present"


def test_get_latest_advice_returns_none_when_too_old() -> None:
    import time

    store_advice(
        "conv-1",
        KMAdvice(
            for_executor="ancient",
            generated_at=time.time() - 10_000,  # way older than TTL
        ),
    )
    assert get_latest_advice("conv-1", "executor") is None


# ─────────────────────────────────────────────────────────────────────────
# Invalidation
# ─────────────────────────────────────────────────────────────────────────


def test_invalidate_both_roles_drops_both() -> None:
    store_advice("conv-1", KMAdvice())
    invalidate_advise_cache("conv-1", reason="handoff")
    assert ("conv-1", "planner") not in km_state._km_advise_cache
    assert ("conv-1", "executor") not in km_state._km_advise_cache


def test_invalidate_single_role_only() -> None:
    store_advice("conv-1", KMAdvice())
    invalidate_advise_cache("conv-1", reason="turn_floor", role="executor")
    assert ("conv-1", "planner") in km_state._km_advise_cache
    assert ("conv-1", "executor") not in km_state._km_advise_cache


def test_invalidate_unknown_conv_is_noop() -> None:
    # Must not raise.
    invalidate_advise_cache("conv-nobody", reason="handoff")


# ─────────────────────────────────────────────────────────────────────────
# Nudge queue
# ─────────────────────────────────────────────────────────────────────────


def test_push_and_pop_nudge_matching_role() -> None:
    push_nudge(
        "conv-1",
        KMNudge(
            title="save the webhook secret",
            target_role="executor",
            message="Write the signing secret to .env.local",
        ),
    )
    taken = pop_nudges("conv-1", "executor")
    assert len(taken) == 1
    assert taken[0].title == "save the webhook secret"
    # Queue is drained.
    assert pop_nudges("conv-1", "executor") == []


def test_push_both_goes_to_both_roles_once() -> None:
    """A nudge targeted at 'both' should reach the first role that polls."""
    push_nudge(
        "conv-1",
        KMNudge(title="t", target_role="both", message="m"),
    )
    # First poll (planner) takes it.
    taken = pop_nudges("conv-1", "planner")
    assert len(taken) == 1
    # Second poll (executor) gets nothing because 'both' is consumed by
    # the first matching pop.
    assert pop_nudges("conv-1", "executor") == []


def test_pop_leaves_non_matching_nudges() -> None:
    push_nudge("conv-1", KMNudge(title="a", target_role="planner", message="m"))
    push_nudge("conv-1", KMNudge(title="b", target_role="executor", message="m"))
    taken = pop_nudges("conv-1", "planner")
    assert [n.title for n in taken] == ["a"]
    # The executor nudge is still there for its own pop.
    remaining = peek_nudges("conv-1")
    assert [n.title for n in remaining] == ["b"]


# ─────────────────────────────────────────────────────────────────────────
# Injection formatter
# ─────────────────────────────────────────────────────────────────────────
#
# The planner and executor MUST NOT know the KM exists.  Every injection
# must be indistinguishable from bare working notes the target agent
# might have written to itself — no envelope, no headers, no attribution.


# Words or markers that would leak KM identity if they appeared in the
# injected text.
_FORBIDDEN_IN_INJECTION = (
    "knowledge-manager",
    "Knowledge Manager",
    "KM_INJECTION",
    "<knowledge",
    "## Steering",
    "## Guidance",
    "## Notes",
    "## Advice",
    "Reminder:",
    "FYI:",
    "Heads up",
    "## Steering",
    "vital-information",
)


def _assert_no_km_leak(block: str) -> None:
    for needle in _FORBIDDEN_IN_INJECTION:
        assert needle not in block, f"injection leaks KM branding {needle!r}: {block!r}"


def test_format_injection_empty_returns_empty_string() -> None:
    assert format_injection(role="planner", advice=None, nudges=[]) == ""


def test_format_injection_has_no_km_envelope_or_headers() -> None:
    """The whole point: the reader must not be able to tell this came
    from a separate agent."""
    nudges = [
        KMNudge(
            title="save-webhook-secret",
            target_role="executor",
            message="Save the Stripe signing secret to `.env.local` first.",
        ),
    ]
    advice = KMAdvice(
        for_executor="- Current phase: scaffold API handlers\n- CORS preflight fails on OPTIONS",
    )
    block = format_injection(role="executor", advice=advice, nudges=nudges)
    _assert_no_km_leak(block)
    # And the actual content IS present
    assert "Stripe signing secret" in block
    assert "CORS preflight" in block


def test_format_injection_nudges_only_are_bare_bullets() -> None:
    nudges = [
        KMNudge(
            title="internal-label",
            target_role="executor",
            message="Save the file before continuing.",
        ),
    ]
    block = format_injection(role="executor", advice=None, nudges=nudges)
    _assert_no_km_leak(block)
    # Starts with a bare bullet, not a header
    assert block.startswith("- ")
    # The internal ``title`` is NOT leaked into the injection
    assert "internal-label" not in block


def test_format_injection_advice_only_respects_role() -> None:
    advice = KMAdvice(for_planner="- plan note", for_executor="- exec note")
    planner_block = format_injection(role="planner", advice=advice, nudges=[])
    executor_block = format_injection(role="executor", advice=advice, nudges=[])
    _assert_no_km_leak(planner_block)
    _assert_no_km_leak(executor_block)
    assert "plan note" in planner_block
    assert "exec note" not in planner_block
    assert "exec note" in executor_block
    assert "plan note" not in executor_block


def test_format_injection_high_urgency_nudge_sorts_first() -> None:
    nudges = [
        KMNudge(
            title="l",
            target_role="planner",
            message="low-priority bullet",
            urgency="low",
        ),
        KMNudge(
            title="h",
            target_role="planner",
            message="HIGH-priority bullet",
            urgency="high",
        ),
    ]
    block = format_injection(role="planner", advice=None, nudges=nudges)
    _assert_no_km_leak(block)
    assert block.index("HIGH-priority") < block.index("low-priority")


def test_format_injection_adds_bullet_prefix_if_missing() -> None:
    """The KM might write a nudge message without the leading '- '; the
    formatter normalises it so the injected block reads as consistent
    bullet list."""
    nudges = [
        KMNudge(title="t", target_role="planner", message="Do the thing."),
    ]
    block = format_injection(role="planner", advice=None, nudges=nudges)
    assert block == "- Do the thing."


def test_format_injection_keeps_existing_bullet_prefix() -> None:
    """If the KM already wrote the message with a leading dash, don't
    double-prefix."""
    nudges = [
        KMNudge(title="t", target_role="planner", message="- Already a bullet"),
    ]
    block = format_injection(role="planner", advice=None, nudges=nudges)
    assert block == "- Already a bullet"


# ─────────────────────────────────────────────────────────────────────────
# KMOutput convenience methods
# ─────────────────────────────────────────────────────────────────────────


def test_kmoutput_is_silent_when_all_empty() -> None:
    assert KMOutput(nothing_to_do=True).is_silent() is True
    assert KMOutput().is_silent() is True


def test_kmoutput_not_silent_with_files() -> None:
    out = KMOutput(files_written=["conv-1/issue/foo.md"])
    assert out.is_silent() is False
    assert out.touched_files() is True
    assert out.has_guidance() is False


def test_kmoutput_not_silent_with_guidance() -> None:
    out = KMOutput(for_planner="- focus on step X")
    assert out.is_silent() is False
    assert out.has_guidance() is True
    assert out.touched_files() is False


def test_kmoutput_not_silent_with_nudges() -> None:
    out = KMOutput(
        nudges=[KMNudge(title="t", target_role="planner", message="m")],
    )
    assert out.is_silent() is False
