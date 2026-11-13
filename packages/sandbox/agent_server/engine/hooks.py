"""Centralised agent hook factories and hook coroutines.

Every ``inject_ephemeral`` site and every ``HookPoint`` registration used
by the sandbox orchestrator lives in this module. The goal is a single
source of truth — consumers (``run.py``, ``harness.py``,
``knowledge/runner.py``) import from here and nowhere else.

The helpers the hooks depend on (instruction-prompt builders, plan
markers/formatters, KM state caches, token-budget usage dict, context
engine primitives) deliberately stay in their domain modules so module
boundaries survive this refactor.

Hook inventory:

* CONTEXT_WINDOW
    - ``make_context_engine_hook``  (planner / executor / KM)
    - ``get_km_context_hook``       (per-conversation cached wrapper)
* START
    - ``make_planner_fresh_message_start_hook``
* PRE_LLM_CALL
    - ``make_message_discipline_hook``
    - ``make_plan_context_hook``
    - ``make_executor_plan_context_hook``
    - ``make_filesystem_first_hook``
    - ``make_project_coordination_hook``
    - ``make_vital_info_hook``
    - ``budget_monitor_hook``
    - ``make_executor_max_steps_warning_hook``
* POST_LLM_CALL
    - ``context_persistence_hook``
    - ``billing_estimate_fallback_hook``
    - ``make_km_prefetch_hook``
    - ``make_content_burst_hook``
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from exo.types import AssistantMessage, UserMessage  # noqa: F401 — UserMessage kept for callers that need it

from agent_server.engine.context import (
    ContextEngineConfig,
    ContextEngineState,
    compact_messages,
    estimate_tokens,
    summarize_messages,
)
from agent_server.engine.knowledge.advise import (
    detect_role,
    format_injection,
)
from agent_server.engine.knowledge.state import (
    _in_km_run,
    capture_messages_snapshot,
    get_latest_advice,
    get_messages_snapshot,
    km_run_rate_limited,
    pop_nudges,
    record_content_heavy_toolcall,
    reset_content_burst,
)
from agent_server.infra.guards import (
    _BUDGET_WARNING_THRESHOLD,
    _DEFAULT_CONTEXT_WINDOW,
    _get_run_id_for_agent,
    _run_usage,
    _workspace_root_path,
)
from tools.plan import (
    _PHASE_STATUS_GLYPH,
    Phase,
    _get_current_plan,
)

log = logging.getLogger("agent_server.hooks")

__version__ = "0.1.0"


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Injected-text markers and prompt constants                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Every marker and multi-line instruction string that gets injected into
# an agent's message list or ephemerals lives here, next to the hooks
# that write them.  The formatters just below turn these into the final
# markdown blocks.

# HTML-comment markers used to find-and-replace prior injections on the
# next turn.  They read as ordinary markdown section markers to the
# target agent and do not leak any subsystem identity.
_PLAN_CONTEXT_MARKER = "<!-- plan -->"
_EXECUTOR_PLAN_CONTEXT_MARKER = "<!-- task -->"
_COMMUNICATION_DISCIPLINE_MARKER = "<!-- message-discipline -->"

_COMMUNICATION_DISCIPLINE_LINES = (
    "Communication discipline: when I need to communicate with the user, I must use "
    "my message tool. Raw assistant text is reserved for my internal thinking only.",
    "I should periodically share task-completion status updates with the same message "
    "tool as I make meaningful progress.",
    "My raw assistant text must stay concise (max 200 words, no long paragraphs). "
    "If content is big or important, I must communicate it via the message tool.",
    "My internal thoughts must stay concise too (max 100 words).",
    "In my internal thoughts, I should not repeat content already delivered through the "
    "message tool; I should reference prior updates and focus only on new delta information.",
)


def _filesystem_first_instruction() -> str:
    workspace_root = _workspace_root_path()
    return (
        f"Reminder about my workspace at {workspace_root}/: this is where I "
        "persist outputs I need beyond my working memory. My context is "
        "durable enough to hold what I did in the last handful of turns; I "
        "write to disk for things that are too big to survive compression "
        "or that I'll need across many turns.\n"
        "\n"
        "- Save to disk: search hits, web_fetch / browse results, "
        "perception findings on images or PDFs, long command output, "
        "distilled research notes. Markdown only (.md or .markdown).\n"
        "- Do NOT save: content I just read from the workspace with "
        "`read_file` — it's already on disk, writing it again creates a "
        "duplicate under a new name. Trivial tool results (a number, a "
        "boolean, a short status line) — those stay in working memory.\n"
        "- Before I write a new file: I list the workspace and check "
        "whether an existing file already covers this topic. If one does, "
        "I append to it rather than create a parallel file. If I can't "
        "tell, I read its first few lines before deciding.\n"
        "- Before I re-read a saved file: I scan my recent messages first. "
        "If the information is still there, I use it directly. I call "
        "`read_file` on my own output only when I genuinely can no longer "
        "see it — not as a reflex because this reminder made me doubt my "
        "context.\n"
        "- If I wrote a file this conversation, I do not read it back on "
        "the next turn, or the one after. It becomes worth re-reading only "
        "once it has scrolled out of recent history.\n"
        "- Multimodal is the exception: after viewing an image or PDF, I "
        "write findings to markdown now — pixels don't persist even if my "
        "notes do.\n"
        "- Resume behaviour: if summarization has run and I cannot see "
        "where I was, I read plan/findings files to re-orient. Not every "
        "turn.\n"
        "\n"
        "Order of operations: list → decide → read-or-append → act. "
        "Never: act → save → re-read → save again."
    )


def _project_coordination_instruction() -> str:
    return (
        "Reminder about the shared project sandbox I'm running in:\n"
        "\n"
        "- Other agents may be working in this sandbox concurrently. The "
        "workspace is shared mutable state, so I coordinate rather than "
        "assume I'm alone.\n"
        "- AGENTS.md at the workspace root is our coordination channel. "
        "If I haven't read it yet this conversation, I read it once to "
        "see what other agents are working on. I do not re-read it every "
        "turn as a reflex.\n"
        "- When I learn something another agent would need — a failing "
        "test, a fragile dependency, a file I'm actively editing — I "
        "append it to AGENTS.md. I do not append status updates or "
        "chatter; only information other agents cannot discover on their "
        "own.\n"
        "- Before my first file edit in this conversation, I claim a "
        "branch with `git worktree add .worktrees/<slug>`. I check "
        'AGENTS.md\'s "Active worktrees" section first to avoid a name '
        "collision. Once claimed, the worktree is mine for the rest of "
        "the conversation — I do not re-claim.\n"
        "- I do not edit files on a branch another agent holds."
    )


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  Plan & message-discipline markdown formatters                           ║
# ╚══════════════════════════════════════════════════════════════════════════╝
#
# Pure string builders — no agent, no messages, just produce the text
# that the PRE_LLM_CALL hooks below will inject.


def format_plan_markdown(conversation_id: str | None = None) -> str | None:
    """Format the current plan as the planner's own inner monologue.

    Returns None if no plan exists.  The output preserves every piece
    of the original plan-context hook — goal, current phase, full plan
    map with per-phase status, progress count, active skills — but
    rewritten in first-person reasoning voice so the planner reads it
    as its own live reference block instead of a labelled system note.
    """
    plan = _get_current_plan(conversation_id)
    if plan is None:
        return None

    current_phase: Phase | None = None
    for phase in plan.phases:
        if phase.id == plan.current_phase_id:
            current_phase = phase
            break

    total = len(plan.phases)
    completed = sum(1 for p in plan.phases if p.status == "completed")

    lines: list[str] = [_PLAN_CONTEXT_MARKER]
    lines.append(f"Where I am in my plan — goal I am working toward: {plan.goal}.")
    if current_phase is not None:
        lines.append(f"I am currently on phase {current_phase.id} of {total}: {current_phase.title}.")
    lines.append(f"Progress so far: {completed}/{total} phases completed.")
    lines.append("")
    lines.append("Full plan map (so I can see where this step fits):")
    for phase in plan.phases:
        glyph = _PHASE_STATUS_GLYPH.get(phase.status, "· pending")
        cursor = "  ← I am here" if phase.id == plan.current_phase_id else ""
        lines.append(f"- phase {phase.id} — {phase.title} ({glyph}){cursor}")

    if current_phase is not None:
        active = current_phase.capabilities.active_skills()
        if active:
            lines.append("")
            lines.append(f"Skills relevant to the phase I am on: {', '.join(active)}.")

    lines.append("")
    lines.extend(_COMMUNICATION_DISCIPLINE_LINES)

    return "\n".join(lines)


def format_message_discipline_markdown() -> str:
    """Format the always-on communication discipline reminder block."""
    lines: list[str] = [_COMMUNICATION_DISCIPLINE_MARKER]
    lines.extend(_COMMUNICATION_DISCIPLINE_LINES)
    return "\n".join(lines)


def format_executor_plan_context(
    conversation_id: str | None = None,
    task: str = "",
) -> str | None:
    """Format the executor's plan context as its own inner monologue.

    Returns None if no plan exists.  Preserves every piece of the
    original hook — the delegated task front and centre, the overall
    goal (so the executor knows *why* the task matters), the full plan
    map (so it knows where the task fits), and the "focus only on this
    phase" directive — but rewritten in first-person reasoning voice
    so the executor reads it as its own working context instead of a
    labelled system note.
    """
    plan = _get_current_plan(conversation_id)
    if plan is None:
        return None

    current_phase: Phase | None = None
    for phase in plan.phases:
        if phase.id == plan.current_phase_id:
            current_phase = phase
            break

    if current_phase is None:
        return None

    total = len(plan.phases)
    lines: list[str] = [_EXECUTOR_PLAN_CONTEXT_MARKER]

    if task:
        lines.append(f"The task I have been handed: {task}")
        lines.append("")

    lines.append(f"Why this task matters — the overall goal I am contributing to is: {plan.goal}.")
    lines.append(f"This task is part of phase {current_phase.id} of {total}: {current_phase.title}.")
    lines.append("")
    lines.append("Where the phase sits in the larger plan:")
    for phase in plan.phases:
        glyph = _PHASE_STATUS_GLYPH.get(phase.status, "· pending")
        cursor = "  ← my task belongs to this phase" if phase.id == plan.current_phase_id else ""
        lines.append(f"- phase {phase.id} — {phase.title} ({glyph}){cursor}")
    lines.append("")
    lines.append(
        f"My scope for this run: complete the task as described, nothing "
        f"more. Other phases are not mine to work on — even if I notice "
        f"something I could improve there, I leave it for the planner to "
        f"assign. Staying inside phase {current_phase.id} keeps the plan "
        f"coherent."
    )
    lines.append("")
    lines.extend(_COMMUNICATION_DISCIPLINE_LINES)
    return "\n".join(lines)


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  CONTEXT_WINDOW hooks                                                    ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def make_context_engine_hook(
    config: ContextEngineConfig,
    conversation_id: str = "",
    on_pre_compress: Callable[[list[Any]], Awaitable[None]] | None = None,
) -> tuple[Any, ContextEngineState]:
    """Create a configured ``CONTEXT_WINDOW`` hook and its state object.

    Args:
        config: Engine configuration including token budget and agent role.
        conversation_id: Conversation ID for loading KM vital info during
            summarization.
        on_pre_compress: Optional async callback invoked with the current
            messages list **just before** any compaction or summarization.
            Used by the Knowledge Manager to capture vital information
            from the window before it is compressed.

    Returns:
        ``(hook_function, state)`` — register the hook on
        ``HookPoint.CONTEXT_WINDOW``.
    """
    state = ContextEngineState()

    async def _fire_pre_compress(messages: list[Any], reason: str) -> None:
        if on_pre_compress is None:
            return
        try:
            await on_pre_compress(messages)
        except Exception:
            log.warning(
                "context engine: pre-compress callback failed (reason=%s), proceeding with compression",
                reason,
                exc_info=True,
            )

    async def context_engine_hook(
        *,
        agent: Any,
        messages: list[Any],
        info: Any,
        provider: Any,
        actions: list[Any],
        **_: Any,
    ) -> None:
        # NOTE on "turn":
        # The CONTEXT_WINDOW hook fires once per LLM step within a SINGLE
        # agent (one planner step, one executor step, or one KM step). The
        # planner and each executor spawn carry their own ContextEngineState
        # (the executor gets a fresh state on every delegation in
        # harness.py); the KM has one cached state per conversation. So
        # "turn 100" is 100 LLM calls for THIS agent, not 100 user
        # turns or 100 messages in memory.
        state.turn_count += 1
        turn = state.turn_count

        agent_name = getattr(info, "agent_name", "") or getattr(agent, "name", "?")
        # Prefer the real prompt-token count from the last LLM call; the
        # message-list estimate is only a structural approximation and
        # excludes whatever the provider added on its own end.
        agent_tools = getattr(agent, "tools", None)

        def _tokens_now() -> int:
            real = getattr(info, "input_tokens", 0) or 0
            if real > 0:
                return real
            return estimate_tokens(messages, tools=agent_tools)

        # ── Primary triggers (turn-based, deterministic) ──────────────

        # Summarization every N turns (subsumes compaction at that turn)
        if turn > 0 and turn % config.summarization_turn_interval == 0:
            await _fire_pre_compress(messages, reason="primary_summarize")
            state.summary_count += 1
            tokens_before = _tokens_now()
            log.info(
                "context engine [%s]: turn %d — triggering SUMMARIZATION "
                "(every %d LLM steps) | before: %d messages, ~%d tokens",
                agent_name,
                turn,
                config.summarization_turn_interval,
                len(messages),
                tokens_before,
            )
            await summarize_messages(
                messages,
                provider,
                config,
                state.summary_count,
                conversation_id=conversation_id,
            )
            tokens_after = estimate_tokens(messages, tools=agent_tools)
            log.info(
                "context engine [%s]: SUMMARIZATION complete | "
                "after: %d messages, ~%d tokens (saved ~%d tokens, %.0f%% reduction)",
                agent_name,
                len(messages),
                tokens_after,
                tokens_before - tokens_after,
                ((tokens_before - tokens_after) / max(tokens_before, 1)) * 100,
            )
            state.compaction_count = 0
            return

        # Compaction every N turns
        if turn > 0 and turn % config.compaction_turn_interval == 0:
            await _fire_pre_compress(messages, reason="primary_compact")
            tokens_before = _tokens_now()
            log.info(
                "context engine [%s]: turn %d — triggering COMPACTION "
                "(every %d LLM steps) | before: %d messages, ~%d tokens "
                "(level 4=%d, fill=%.0f%%)",
                agent_name,
                turn,
                config.compaction_turn_interval,
                len(messages),
                tokens_before,
                config.level_4,
                100.0 * tokens_before / max(config.level_4, 1),
            )
            compact_messages(messages)
            tokens_after = estimate_tokens(messages, tools=agent_tools)
            log.info(
                "context engine [%s]: COMPACTION complete | "
                "after: %d messages, ~%d tokens (saved ~%d tokens, %.0f%% reduction)",
                agent_name,
                len(messages),
                tokens_after,
                tokens_before - tokens_after,
                ((tokens_before - tokens_after) / max(tokens_before, 1)) * 100,
            )
            state.compaction_count += 1
            return

        # ── Safety net (token-based) ──────────────────────────────────

        tokens = _tokens_now()

        if tokens >= config.level_4:
            await _fire_pre_compress(messages, reason="safety_net_compact")
            log.info(
                "context engine [%s]: turn %d — token safety net COMPACTION "
                "(%d tokens >= level 4 threshold %d) | %d messages",
                agent_name,
                turn,
                tokens,
                config.level_4,
                len(messages),
            )
            compact_messages(messages)
            state.compaction_count += 1

            # Re-check: if still over Level 4, summarize
            tokens_after = estimate_tokens(messages, tools=agent_tools)
            log.info(
                "context engine [%s]: token safety net COMPACTION complete | "
                "after: %d messages, ~%d tokens (saved ~%d tokens, %.0f%% reduction)",
                agent_name,
                len(messages),
                tokens_after,
                tokens - tokens_after,
                ((tokens - tokens_after) / max(tokens, 1)) * 100,
            )
            if tokens_after >= config.level_4:
                log.info(
                    "context engine [%s]: turn %d — token safety net SUMMARIZATION "
                    "(%d tokens >= level 4 threshold %d after compaction)",
                    agent_name,
                    turn,
                    tokens_after,
                    config.level_4,
                )
                state.summary_count += 1
                await summarize_messages(
                    messages,
                    provider,
                    config,
                    state.summary_count,
                    conversation_id=conversation_id,
                )
                tokens_final = estimate_tokens(messages, tools=agent_tools)
                log.info(
                    "context engine [%s]: token safety net SUMMARIZATION complete | "
                    "after: %d messages, ~%d tokens (saved ~%d tokens total from %d)",
                    agent_name,
                    len(messages),
                    tokens_final,
                    tokens - tokens_final,
                    tokens,
                )
                state.compaction_count = 0

    return context_engine_hook, state


# ─────────────────────────────────────────────────────────────────────────
# Shared KM context hook — one (hook, state) pair per conversation
# ─────────────────────────────────────────────────────────────────────────
#
# The KM uses the same ``ContextEngineConfig`` the planner and executor
# use.  Its context-engine hook is created once per conversation and
# reused across every ``run_km`` invocation so that turn counts, summary
# counts, and compaction counts persist and the summarization behaviour
# stays consistent across runs.  The shared hook is NEVER given an
# ``on_pre_compress`` callback — the ``_in_km_run`` guard would already
# block recursion, but omitting the callback entirely is cleaner.

_km_context_hooks: dict[str, tuple[Any, Any]] = {}
_km_context_hooks_mtx = asyncio.Lock()


async def get_km_context_hook(
    conversation_id: str,
    ctx_engine_config: ContextEngineConfig | None,
) -> tuple[Any, Any] | None:
    """Return ``(hook_fn, state)`` for the KM's context engine.

    Creates the pair on first call and caches it per conversation.
    Returns ``None`` if ``ctx_engine_config`` is ``None`` (the caller
    then skips installing a CONTEXT_WINDOW hook).
    """
    if ctx_engine_config is None:
        return None
    async with _km_context_hooks_mtx:
        pair = _km_context_hooks.get(conversation_id)
        if pair is None:
            pair = make_context_engine_hook(
                ctx_engine_config,
                conversation_id=conversation_id,
                # Deliberately no on_pre_compress — the KM must not
                # recursively trigger itself.
            )
            _km_context_hooks[conversation_id] = pair
        return pair


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  START hooks                                                             ║
# ╚══════════════════════════════════════════════════════════════════════════╝


_PLANNER_FRESH_MESSAGE_ACK_THOUGHT = (
    "User sent a fresh message, I need to acknowledge user's request with "
    "my available message tool immediately before I decide I should plan or not. "
    "If this likely needs 2+ delegations, I should plan first. "
    "When I delegate, I should assign only one atomic objective."
)


def make_planner_fresh_message_start_hook():
    """Create a START hook that seeds a fresh-message acknowledgement thought.

    Fires when the planner is handed a new user message so the planner's
    first move is to acknowledge via its ``message`` tool before deciding
    whether to plan or delegate.
    """

    async def planner_fresh_message_start_hook(*, agent: Any, **_: Any) -> None:
        try:
            agent.inject_ephemeral(AssistantMessage(content=_PLANNER_FRESH_MESSAGE_ACK_THOUGHT))
        except Exception:
            log.debug("planner fresh-message START hook failed", exc_info=True)

    return planner_fresh_message_start_hook


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  PRE_LLM_CALL hooks                                                      ║
# ╚══════════════════════════════════════════════════════════════════════════╝


def make_message_discipline_hook(conversation_id: str | None = None):
    """Create a PRE_LLM_CALL hook that injects communication discipline
    even when no execution plan exists.

    Ephemeral: the reminder is visible for exactly one LLM call and then
    dropped.  When a plan IS active, the plan-context / executor-plan-
    context hooks inject a block that already carries the discipline
    lines, so this hook skips to avoid duplication.  Skipping is
    determined by calling into the plan tool directly — no peeking at
    other hooks' state.
    """

    async def message_discipline_hook(*, agent: Any, **_) -> None:
        try:
            if _get_current_plan(conversation_id) is not None:
                # plan-context hook is injecting the richer block
                # which already contains the discipline lines.
                return
            agent.inject_ephemeral(AssistantMessage(content=format_message_discipline_markdown()))
        except Exception:
            log.warning("message_discipline_hook: failed", exc_info=True)

    return message_discipline_hook


def make_plan_context_hook(conversation_id: str):
    """Create a PRE_LLM_CALL hook scoped to a specific conversation.

    Ephemeral: injects the current plan state as a single-call visibility
    message.  If no plan exists, injects nothing.  Because the injection
    is ephemeral, the plan block never accumulates in the persisted
    message list and is always re-read from the live plan state on the
    next turn (no stale plan ever lingers).
    """

    async def plan_context_hook(*, agent: Any, **_) -> None:
        try:
            plan_md = format_plan_markdown(conversation_id)
            if plan_md is None:
                return  # No plan yet — inject nothing.
            agent.inject_ephemeral(AssistantMessage(content=plan_md))
        except Exception:
            log.warning(
                "plan_context_hook: failed for conv=%s",
                conversation_id[:8],
                exc_info=True,
            )

    return plan_context_hook


def make_executor_plan_context_hook(conversation_id: str, task: str = ""):
    """Create a PRE_LLM_CALL hook for executor agents.

    Similar to ``make_plan_context_hook`` but injects executor-specific
    plan context that includes the delegated task and the full plan map.
    Ephemeral: visible for one LLM call, then dropped.
    """

    async def executor_plan_context_hook(*, agent: Any, **_) -> None:
        try:
            plan_md = format_executor_plan_context(conversation_id, task=task)
            if plan_md is None:
                return  # no plan active — nothing to inject for executor
            agent.inject_ephemeral(AssistantMessage(content=plan_md))
        except Exception:
            log.warning(
                "executor_plan_context_hook: failed for conv=%s",
                conversation_id[:8],
                exc_info=True,
            )

    return executor_plan_context_hook


def make_filesystem_first_hook():
    """Create a PRE_LLM_CALL hook that keeps the executor's "save it to
    disk" reflex warm.

    Uses ``inject_ephemeral`` so the note appears every turn without
    accumulating in the conversation history.  The injected text is
    written in the executor's own voice (bare imperative bullets) so the
    executor reads it as its own working note, not an external reminder.
    """

    async def filesystem_first_hook(*, agent: Any, **_: Any) -> None:
        try:
            agent.inject_ephemeral(AssistantMessage(content=_filesystem_first_instruction()))
        except Exception:
            log.debug("filesystem_first_hook: injection failed", exc_info=True)

    return filesystem_first_hook


def make_project_coordination_hook():
    """Create a PRE_LLM_CALL hook that reminds project-scoped agents to
    coordinate via AGENTS.md and use git worktrees for coding work.

    Registered only when a run is project-scoped (see ``_run_agent``'s
    hook builder).  Uses ``inject_ephemeral`` so the reminder is fresh
    every turn without bloating history.
    """

    async def project_coordination_hook(*, agent: Any, **_: Any) -> None:
        try:
            agent.inject_ephemeral(AssistantMessage(content=_project_coordination_instruction()))
        except Exception:
            log.debug("project_coordination_hook: injection failed", exc_info=True)

    return project_coordination_hook


def make_vital_info_hook(conversation_id: str):
    """PRE_LLM_CALL hook that captures the live trajectory and injects
    pre-computed KM guidance + nudges.

    Two responsibilities:

    1. **Capture** — every PRE_LLM_CALL hands the hook the live message
       list via the ``messages=`` kwarg.  The hook copies it into the
       per-conversation snapshot dict in ``state.py`` so downstream
       consumers (the continuous loop, the prefetch hook, the
       content-burst hook) can read the freshest trajectory.  This is
       the fix for the silent-KM bug where ``harness._ctx.messages``
       is never populated on exo's single-agent code path.
    2. **Inject** — the hook is a pure cache reader: it never calls an
       LLM in the hot path, and it never gates on turn counts or any
       other hardcoded rhythm.  If the cache has something for this
       role, it is injected; if not, nothing is injected.

    Behaviour:
    - Detect role from ``agent.name``. Unknown roles (the KM itself)
      get nothing — neither capture nor injection.
    - Capture the live messages kwarg into the snapshot dict.
    - Consume any pending nudges matching this role.
    - Look up the latest cached advice for this role (lenient — stale
      is OK up to ``KM_ADVICE_MAX_AGE_SEC``).
    - If anything is present, compose and inject a single ephemeral
      block via ``agent.inject_ephemeral``.
    - Swallow every exception with a warning.  Injection must never
      break the planner / executor turn.
    """

    async def vital_info_hook(*, agent: Any, messages: list | None = None, **_: Any) -> None:
        try:
            role = detect_role(agent)
            if role == "other":
                return

            # Capture the live trajectory.  Exo's PRE_LLM_CALL handler
            # passes ``msg_list`` as ``messages``; fall back to an
            # empty list if something upstream changes.
            if messages is not None:
                capture_messages_snapshot(conversation_id, messages)

            nudges = pop_nudges(conversation_id, role)
            advice = get_latest_advice(conversation_id, role)

            block = format_injection(role=role, advice=advice, nudges=nudges)
            if not block:
                return

            agent.inject_ephemeral(AssistantMessage(content=block))
            log.debug(
                "vital_info_hook: role=%s conv=%s advice=%s nudges=%d chars=%d",
                role,
                conversation_id[:8],
                "hit" if advice else "none",
                len(nudges),
                len(block),
            )
        except Exception:
            log.warning(
                "vital_info_hook: failed for conv=%s",
                conversation_id[:8],
                exc_info=True,
            )

    return vital_info_hook


async def budget_monitor_hook(*, agent: Any, **_: Any) -> None:
    """Nudge the agent to persist vital state when the context window is
    nearly full.

    The injected note is written as the agent's own inner reasoning —
    first-person, with the full *why* and a concrete checklist of what
    to save — so it reads as a self-reminder rather than an external
    alert.
    """
    try:
        run_id = _get_run_id_for_agent(agent)
        if not run_id:
            return
        usage = _run_usage.get(run_id)
        if not usage:
            return
        input_tokens = usage.get("input_tokens", 0)
        context_window = usage.get("context_window", _DEFAULT_CONTEXT_WINDOW)
        if context_window <= 0:
            return
        fill_ratio = input_tokens / context_window
        if fill_ratio >= _BUDGET_WARNING_THRESHOLD and not usage.get("warning_sent"):
            agent.inject_ephemeral(
                AssistantMessage(
                    content=(
                        f"Context check: I'm at roughly {fill_ratio:.0%} of my "
                        "window — compression is imminent. If I have unwritten "
                        "state that would hurt to lose across compression, I "
                        "persist it now before my next action."
                    )
                )
            )
            usage["warning_sent"] = True
            log.info(
                "Budget warning injected at %.0f%% for run %s",
                fill_ratio * 100,
                run_id,
            )
    except Exception:  # noqa: BLE001
        log.debug("Budget monitor hook failed", exc_info=True)


def make_executor_max_steps_warning_hook(max_steps: int):
    """PRE_LLM_CALL hook that fires a soft-stop warning 3 turns before
    the executor hits ``max_steps``.

    Used by the harness to nudge an executor into wrap-up mode while it
    still has time to return a structured result.  The hook counts its
    own LLM calls via a closure, fires exactly once (``_fired`` flag),
    and stays silent otherwise.  Replaces the inline per-turn check the
    harness used to run in its delegation loop.
    """
    warn_at = max_steps - 3
    state: dict[str, int | bool] = {"call_count": 0, "fired": False}

    async def executor_max_steps_warning_hook(*, agent: Any, **_: Any) -> None:
        if state["fired"]:
            return
        state["call_count"] = int(state["call_count"]) + 1
        if state["call_count"] < warn_at:
            return
        try:
            agent.inject_ephemeral(
                AssistantMessage(
                    content=(
                        "I'm close to the maximum turn budget for this executor "
                        "session — I need to wrap up now while I still have room. "
                        "I stop starting new work, summarize what I accomplished "
                        "and what remains, and return my structured output so the "
                        "planner can re-delegate anything unfinished."
                    )
                )
            )
            state["fired"] = True
            log.debug(
                "executor_max_steps_warning_hook: injected at call %d (warn_at=%d, max_steps=%d)",
                state["call_count"],
                warn_at,
                max_steps,
            )
        except Exception:
            log.debug(
                "executor_max_steps_warning_hook: injection failed at call %d",
                state["call_count"],
                exc_info=True,
            )

    return executor_max_steps_warning_hook


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  POST_LLM_CALL hooks                                                     ║
# ╚══════════════════════════════════════════════════════════════════════════╝


async def context_persistence_hook(*, agent: Any, response: Any, **_: Any) -> None:
    try:
        run_id = _get_run_id_for_agent(agent)
        if not run_id:
            return
        usage_obj = getattr(response, "usage", None)
        if usage_obj:
            if run_id not in _run_usage:
                _run_usage[run_id] = {}
            input_tokens = getattr(usage_obj, "input_tokens", 0)
            if input_tokens > 0:
                _run_usage[run_id]["input_tokens"] = input_tokens
    except Exception:  # noqa: BLE001
        log.debug("Context persistence hook failed", exc_info=True)


async def billing_estimate_fallback_hook(*, agent: Any, response: Any, **_: Any) -> None:
    """Fallback usage estimator for providers that report zero tokens.

    Some local Ollama / vLLM endpoints stream completions without ever
    emitting a usable ``Usage`` payload, which means the downstream
    billing pipeline records 0 tokens and 0 cost for the call. This
    POST_LLM_CALL hook fills the gap:

        1. If ``response.usage.total_tokens > 0``, do nothing — the
           provider's own count wins.
        2. Otherwise, structurally estimate the prompt tokens from the
           agent's current message list + tool schemas (the same path the
           context engine uses for safety-net checks) and approximate the
           output tokens from the response text.
        3. Stash the estimate keyed by ``agent.name``. The next ``usage``
           event from this agent — emitted by exo immediately after the
           POST_LLM_CALL — will pick it up inside
           ``update_usage_totals`` and flow through the normal billing
           settlement path (cost is then derived from the model pricing
           table in :mod:`agent_server.engine.pricing`).

    Cheap to install on every agent (planner / executor / KM); the
    estimate path only runs when the upstream count is truly missing.
    """
    try:
        usage_obj = getattr(response, "usage", None)
        if usage_obj is not None and getattr(usage_obj, "total_tokens", 0) > 0:
            return

        agent_name = getattr(agent, "name", "") or ""
        if not agent_name:
            return

        messages = list(getattr(agent, "messages", []) or [])
        if not messages:
            return

        tools = getattr(agent, "tools", None)
        model = getattr(agent, "model", "") or ""

        input_estimate = estimate_tokens(messages, tools=tools)

        # Output is whatever text we ended up streaming back.
        output_estimate = 0
        text = getattr(response, "content", "") or ""
        if isinstance(text, str) and text:
            try:
                # Reuse the cached counter for accuracy; fall back to /4.
                from agent_server.engine.context import _get_counter  # noqa: C0415

                output_estimate = _get_counter().count(text)
            except Exception:  # noqa: BLE001
                output_estimate = max(len(text) // 4, 0)

        if input_estimate <= 0 and output_estimate <= 0:
            return

        from agent_server.infra.state import stash_estimated_usage  # noqa: C0415

        stash_estimated_usage(
            agent_name,
            input_tokens=input_estimate,
            output_tokens=output_estimate,
            model=model,
        )
    except Exception:  # noqa: BLE001
        log.debug("billing_estimate_fallback_hook failed", exc_info=True)


def make_km_prefetch_hook(
    *,
    conversation_id: str,
    run_id: str,
    provider: Any,
    model: str,
    ctx_engine_config: ContextEngineConfig | None = None,
):
    """POST_LLM_CALL hook that pre-computes KM output for the NEXT turn.

    After each planner or executor LLM call completes, this hook fires
    a ``run_km`` invocation as a background task so the advise cache
    is warm by the time the next PRE_LLM_CALL hook runs — the
    injection hook can then read directly without any synchronous KM
    work.

    Scope is chosen from the calling agent's role:
    - ``planner`` turns → ``scope="overall"``
    - ``executor`` / ``ralph-worker`` turns → ``scope="worker"``
    - anything else (including the KM's own runs) is ignored

    The hook also honours the rate-limit floor so a chain of rapid
    POST_LLM_CALLs does not create a thundering herd of KM runs.
    """

    async def km_prefetch_hook(*, agent: Any = None, **_: Any) -> None:
        if _in_km_run.get(False):
            return
        role = detect_role(agent)
        if role == "other":
            return

        scope = "overall" if role == "planner" else "worker"
        if km_run_rate_limited(conversation_id, scope):
            return

        # Read the snapshot captured by ``vital_info_hook`` on the
        # PRE_LLM_CALL that preceded this POST_LLM_CALL.  ``exo.Agent``
        # does not expose a ``.messages`` attribute; the snapshot is
        # the one reliable source of trajectory content.
        messages = get_messages_snapshot(conversation_id)
        if not messages:
            return

        worker_task = ""
        if scope == "worker":
            # Best-effort: pick up the delegated task if the orchestrator
            # stashed it on the agent. Empty string is fine — the
            # worker frame falls back to plan-only context.
            worker_task = getattr(agent, "_km_worker_task", "") or ""

        try:
            from agent_server.engine.knowledge.runner import run_km  # noqa: C0415

            asyncio.create_task(
                run_km(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    messages=messages,
                    provider=provider,
                    model=model,
                    trigger="prefetch",
                    scope=scope,
                    ctx_engine_config=ctx_engine_config,
                    worker_task=worker_task,
                ),
                name=f"km-prefetch-{conversation_id[:8]}-{scope}",
            )
        except Exception:
            log.debug(
                "km_prefetch_hook: failed to schedule run_km",
                exc_info=True,
            )

    return km_prefetch_hook


# ─────────────────────────────────────────────────────────────────────────
# Content-burst hook — fires the KM on 3 consecutive content-heavy tools
# ─────────────────────────────────────────────────────────────────────────

# Tools whose results are content-heavy enough that the KM should
# consider summarising them eagerly.  ``read_file`` is deliberately
# excluded — small workspace reads are too noisy to gate on.
CONTENT_HEAVY_TOOLS: frozenset[str] = frozenset(
    {
        "web_search",
        "web_fetch",
        "browse",
        "browser_navigate",
        "browser_snapshot",
        "perception",
        "perception_analyze_image",
    }
)


def _extract_last_tool_name(agent: Any, info: Any) -> str | None:
    """Best-effort extraction of the most recent tool call's name.

    Exo's ``POST_LLM_CALL`` info shape varies slightly across versions,
    so this probes several plausible attributes and falls back to
    scanning the agent's recent messages.
    """
    # Direct attributes on the info object
    for attr in ("last_tool_name", "tool_name"):
        value = getattr(info, attr, None)
        if isinstance(value, str) and value:
            return value

    # info.tool_calls list — take the last one's name
    tool_calls = getattr(info, "tool_calls", None)
    if tool_calls:
        try:
            last = tool_calls[-1]
            name = getattr(last, "name", None)
            if name is None and isinstance(last, dict):
                name = last.get("name")
            if isinstance(name, str) and name:
                return name
        except (IndexError, AttributeError, TypeError):
            pass

    # Fallback: scan recent messages for a tool_call or tool-result
    messages = getattr(agent, "messages", None) or []
    for msg in reversed(messages[-6:]):
        name = _name_from_message(msg)
        if name is not None:
            return name
    return None


def _name_from_message(msg: Any) -> str | None:
    """Pull a tool name out of a single message, handling both dict and
    object shapes."""
    if isinstance(msg, dict):
        tc = msg.get("tool_calls") or []
        if tc:
            last = tc[-1]
            if isinstance(last, dict):
                fn = last.get("function") or {}
                return fn.get("name") if isinstance(fn, dict) else None
        if msg.get("role") == "tool":
            name = msg.get("name")
            return name if isinstance(name, str) and name else None
        return None

    tc = getattr(msg, "tool_calls", None)
    if tc:
        try:
            last = tc[-1]
            name = getattr(last, "name", None)
            if name is None:
                fn = getattr(last, "function", None)
                name = getattr(fn, "name", None) if fn is not None else None
            if isinstance(name, str) and name:
                return name
        except (IndexError, AttributeError):
            pass
    if getattr(msg, "role", None) == "tool":
        name = getattr(msg, "name", None)
        return name if isinstance(name, str) and name else None
    return None


def make_content_burst_hook(
    *,
    conversation_id: str,
    run_id: str,
    provider: Any,
    model: str,
    ctx_engine_config: ContextEngineConfig | None = None,
):
    """Build a POST_LLM_CALL hook that fires a ``content_burst`` KM run
    on the 3rd consecutive content-heavy tool call.

    Safe to install on both planner and executor.  The streak counter
    is per-conversation (not per-agent) so the two agents share one
    counter naturally.  Scope is chosen from the calling agent's role
    via ``detect_role``: a content burst observed during an executor
    turn fires a ``scope="worker"`` run; during a planner turn it
    fires a ``scope="overall"`` run.
    """

    async def content_burst_hook(*, agent: Any = None, info: Any = None, **_: Any) -> None:
        if _in_km_run.get(False):
            return
        try:
            tool_name = _extract_last_tool_name(agent, info)
            if tool_name is None:
                return
            if tool_name not in CONTENT_HEAVY_TOOLS:
                reset_content_burst(conversation_id)
                return
            if not record_content_heavy_toolcall(conversation_id):
                return

            reset_content_burst(conversation_id)

            role = detect_role(agent)
            if role == "other":
                return
            scope = "overall" if role == "planner" else "worker"

            # Read the snapshot captured by ``vital_info_hook`` on the
            # preceding PRE_LLM_CALL.  Falls back to empty which the
            # runner's gates will short-circuit on.
            messages = get_messages_snapshot(conversation_id)
            if not messages:
                return

            worker_task = ""
            if scope == "worker":
                worker_task = getattr(agent, "_km_worker_task", "") or ""

            log.info(
                "content_burst: firing run_km (conv=%s scope=%s last_tool=%s)",
                conversation_id[:8],
                scope,
                tool_name,
            )

            from agent_server.engine.knowledge.runner import run_km  # noqa: C0415

            asyncio.create_task(
                run_km(
                    conversation_id=conversation_id,
                    run_id=run_id,
                    messages=messages,
                    provider=provider,
                    model=model,
                    trigger="content_burst",
                    scope=scope,
                    ctx_engine_config=ctx_engine_config,
                    worker_task=worker_task,
                ),
                name=f"km-content-burst-{conversation_id[:8]}-{scope}",
            )
        except Exception:
            log.debug(
                "content_burst_hook: swallowed exception (conv=%s)",
                conversation_id[:8],
                exc_info=True,
            )

    return content_burst_hook


__all__ = [
    # Context window
    "make_context_engine_hook",
    "get_km_context_hook",
    # START
    "make_planner_fresh_message_start_hook",
    # PRE_LLM_CALL
    "make_message_discipline_hook",
    "make_plan_context_hook",
    "make_executor_plan_context_hook",
    "make_filesystem_first_hook",
    "make_project_coordination_hook",
    "make_vital_info_hook",
    "budget_monitor_hook",
    "make_executor_max_steps_warning_hook",
    # POST_LLM_CALL
    "context_persistence_hook",
    "billing_estimate_fallback_hook",
    "make_km_prefetch_hook",
    "make_content_burst_hook",
    # Constants & test-facing state
    "CONTENT_HEAVY_TOOLS",
]
