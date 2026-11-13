"""Orchestrator Harness — Planner + Executor sub-agent model.

Replaces the monolithic single-Agent approach.  The Planner receives user input
and delegates tasks to dynamically-created Executor sub-agents via the
``delegate`` signal tool.  The harness loop detects the delegation signal and
runs the executor via ``ctx.stream_agent()`` — events flow through the natural
yield chain for proper usage tracking, lease enforcement, and SSE streaming.

A Knowledge Manager agent extracts vital information after sub-agent execution,
every 5 planner turns, and every 10 executor turns.

Usage in ``server.py``::

    harness = build_orchestrator_harness(
        planner_model=model,
        planner_instructions=instructions,
        ...
    )
    runnable = harness
    # Then: run.stream(runnable, task, detailed=True, provider=provider, ...)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from exo import Agent, FunctionTool
from exo.guardrail.types import GuardrailError
from exo.harness import Harness, HarnessContext
from exo.hooks import HookPoint
from exo.rail import RailAbortError
from exo.types import AssistantMessage, TextEvent
from pydantic import BaseModel, Field

from agent_server.engine._compaction_prompts import PTC_EXTRA_COMPACTION_ARGS
from agent_server.engine.context import ContextEngineConfig
from agent_server.engine.hooks import (
    make_context_engine_hook,
    make_executor_max_steps_warning_hook,
    make_executor_plan_context_hook,
    make_filesystem_first_hook,
    make_planner_fresh_message_start_hook,
)
from agent_server.engine.knowledge import (
    get_messages_snapshot,
    invalidate_advise_cache,
    run_km,
    should_run_km,
)
from agent_server.engine.prompts import build_executor_instructions
from agent_server.engine.verbose import log_harness as _verbose

__version__ = "0.1.0"

log = logging.getLogger("orchestrator_harness")


def _iter_leaf_exceptions(exc: BaseException):
    """Yield leaf exceptions from nested BaseExceptionGroup trees."""
    if isinstance(exc, BaseExceptionGroup):
        for child in exc.exceptions:
            yield from _iter_leaf_exceptions(child)
        return
    yield exc


def _normalize_stream_exception(exc: Exception) -> Exception:
    """Prefer meaningful inner rail/guardrail exceptions over wrapper groups."""
    for leaf in _iter_leaf_exceptions(exc):
        if isinstance(leaf, (RailAbortError, GuardrailError)):
            return leaf
    return exc


def _is_policy_block(exc: Exception) -> bool:
    return isinstance(exc, (RailAbortError, GuardrailError))


def _error_text(exc: Exception) -> str:
    text = str(exc).strip()
    return text or repr(exc)


def _km_task_done(task: asyncio.Task) -> None:
    """Log exceptions from fire-and-forget KM tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("Background KM task %s failed: %s", task.get_name(), exc)


# ---------------------------------------------------------------------------
# Tool partitioning constants
# ---------------------------------------------------------------------------

# Tools available to the planner (orchestration only).
# The planner's job is to plan and delegate — nothing else.
# `artifact` is intentionally excluded: artifacts are user-facing content
# production, which is the executor's job. The planner delivers executor-
# produced artifacts to the user via message(result).attachments (file paths).
PLANNER_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "plan",
        "message",
        "ralph_loop",
        # delegate is injected dynamically by the harness
    }
)

# Tools excluded from sub-agent workers (both executors and ralph workers).
# Both types flow through _build_worker_agent which uses self._executor_tools,
# so exclusions here apply to both. `plan` is excluded because:
#   - Executors do single focused delegations; phase management is the
#     planner's concern, not theirs.
#   - Ralph workers follow a fixed 7-step autonomous workflow on a prd.json;
#     they have no multi-phase orchestration to plan.
# `delegate` is also never given (no recursive spawning).
# `message` is NOT excluded — both can communicate with users.
EXECUTOR_EXCLUDED_TOOLS: frozenset[str] = frozenset(
    {
        "plan",
    }
)

# Safety limit for planner-executor delegation cycles
MAX_DELEGATION_ITERATIONS = 20


# ---------------------------------------------------------------------------
# DelegationSignal — mutable signal set by the delegate tool
# ---------------------------------------------------------------------------


@dataclass
class DelegationSignal:
    """Mutable signal set by the ``delegate`` tool, read by the harness loop."""

    task: str | None = None
    context: str = ""
    use_history: bool = False

    def reset(self) -> None:
        self.task = None
        self.context = ""
        self.use_history = False


# ---------------------------------------------------------------------------
# ExecutorResult — fixed output wrapper for all sub-agents
# ---------------------------------------------------------------------------


class RalphResult(BaseModel):
    """Terminal output schema for ralph workers.

    A ralph worker emits exactly ONE ``RalphResult`` when it finishes its
    single assigned story. Producing this output is the worker's explicit
    exit signal — the agent runtime terminates the session once the output
    is validated, so the ralph_loop can advance to the next iteration with
    a fresh worker. Workers MUST NOT continue working after emitting this.

    This is intentionally minimal compared to ``ExecutorResult``. Ralph
    workers' real artifacts are filesystem side-effects (the git commit,
    the prd.json mutation, the progress.txt append) — not handoff content.
    The fields here exist purely so the ralph_loop can log progress,
    detect blocked stories, and decide whether to advance or retry.
    """

    success: bool = Field(
        description=(
            "True if the story was completed and committed. False if the "
            "worker gave up, found the story impossible/blocked, or failed "
            "quality checks after retries."
        ),
    )
    story_id: str = Field(
        description="ID of the story this worker attempted (e.g. 'AU-01').",
    )
    outcome: str = Field(
        description=(
            "One of: 'completed' (committed + prd.json+progress.txt updated), "
            "'blocked' (can't proceed; noted in prd.json notes field), "
            "'skipped' (moved past this one for a later retry)."
        ),
    )
    committed: bool = Field(
        default=False,
        description="True if a git commit was made for this story.",
    )
    notes: str = Field(
        default="",
        description=(
            "Brief note (under 100 words) for the ralph_loop log. Use this "
            "to surface blockers, unexpected findings, or decisions you "
            "made during the story — not a full summary of what you did."
        ),
    )


class ExecutorResult(BaseModel):
    """Fixed output schema for all executor sub-agents.

    This is the planner<->executor coordination protocol. Executors MUST
    populate these fields so the planner has enough context to decide the
    next action without re-delegating a 'read and understand' pass.
    """

    success: bool
    # Stated cap: 512 words (what the executor is told).
    # Hard backstop: 16 KB applied in planner_result assembly below (~2500 words).
    # The gap is deliberate — LLMs overshoot stated caps by 20-40%, and we'd
    # rather absorb the overshoot silently than surprise-truncate. Do not
    # "fix" this mismatch; keep the stated target tight and the backstop loose.
    summary: str = Field(
        default="",
        description=(
            "What was accomplished AND what the planner needs to know to "
            "decide the next step. Under 512 words. Not a one-liner — "
            "calibrate depth to the task: generous for ingestion/exploration "
            "delegations (reading PRDs, surveying codebases), tight for "
            "narrow tasks (one-line edits, single-file changes). Include "
            "the shape of the deliverable, constraints discovered, and "
            "risks noticed. A thin summary forces the planner to re-delegate "
            "for basic facts; a bloated one wastes planner context."
        ),
    )
    key_findings: list[str] = Field(
        default_factory=list,
        description=(
            "3-7 structured bullets of what the executor LEARNED that the "
            "planner needs to know. NOT a log of what was done — that's "
            "`summary`. This is for non-obvious facts the planner would "
            "otherwise have to re-delegate to discover. E.g. 'DB schema "
            "already exists at lib/db/schema.ts', 'tests directory is "
            "empty — no test framework wired', 'package.json pins React "
            "18 not 19'."
        ),
    )
    open_decisions: list[str] = Field(
        default_factory=list,
        description=(
            "Decisions surfaced during the work that require planner "
            "judgment, proactively — do not wait to be asked. E.g. 'PRD "
            "doesn't specify session storage — cookie vs JWT?'. Empty "
            "list means everything was clear."
        ),
    )
    suggested_next_delegations: list[str] = Field(
        default_factory=list,
        description=(
            "The executor just saw the work; it often knows the logical "
            "next step. Suggest 1-3 concrete delegation tasks the planner "
            "could launch next. The planner is free to ignore these, but "
            "they prevent the planner from having to re-explore."
        ),
    )
    result_files: list[str] = Field(
        default_factory=list,
        description=(
            "Absolute markdown file paths containing substantive results. "
            "On success, this should include the primary deliverable files."
        ),
    )
    planner_questions: list[str] = Field(
        default_factory=list,
        description=(
            "Questions the planner should ask the USER when clarification "
            "or approval is required. Executors must not ask users directly. "
            "Keep these distinct from `open_decisions` (planner-facing)."
        ),
    )
    files_modified: list[str] = Field(default_factory=list)
    messages_sent_to_user: list[str] = Field(
        default_factory=list,
        description=(
            "Summary of each info message already sent to the user via the "
            "message tool during this execution. The planner uses this to "
            "avoid repeating already-shared content."
        ),
    )
    error: str | None = None
    # Legacy alias for backwards compatibility — prefer `summary`. If both
    # are set, `summary` wins. Kept so existing executor outputs don't break.
    result: str = Field(default="", description="DEPRECATED: use `summary`.")


# ---------------------------------------------------------------------------
# delegate tool factory
# ---------------------------------------------------------------------------


def _build_delegate_tool(signal: DelegationSignal) -> FunctionTool:
    """Build the ``delegate`` signal tool.

    This tool does NO execution — it records the planner's intent and
    returns immediately.  The harness loop detects the signal after the
    planner's turn ends and runs the executor via ``ctx.stream_agent()``.
    """

    async def delegate(
        task: str,
        context: str = "",
        use_history: bool = False,
        brief: str = "",
    ) -> str:
        """Submit a task for execution by the system.

        The system has full tool access (file, git, search, browse,
        perception, web, mobile, media, etc.) and runs independently.
        Use for implementation, research, or any task requiring tool use.

        After calling this, end your turn. Results will be provided
        in your next turn.

        Args:
            task: Clear, specific task description.
            context: Additional constraints, acceptance criteria, or background.
            use_history: Set True to give the system access to the full
                conversation history for context-heavy tasks.
            brief: One-sentence preamble describing the delegation purpose.
        """
        # Re-entrance guard: only accept ONE delegation per planner turn.
        # The harness early-exits after the planner step that called
        # delegate, but if the LLM emits multiple delegate calls in a
        # single step we must reject the extras so the first task is not
        # silently overwritten.
        if signal.task is not None:
            log.warning(
                "Duplicate delegate call rejected (already delegated: %.120s)",
                signal.task,
            )
            return (
                "ERROR: A task was already delegated this turn. Only one "
                "delegation per turn is allowed. End your turn now — the "
                "first task is being executed and its result will be "
                "delivered in your next turn."
            )
        if not task or not task.strip():
            return "ERROR: delegate requires a non-empty task description. Please provide a clear, specific objective."
        signal.task = task
        signal.context = context
        signal.use_history = use_history
        return "Task accepted. Execution will begin after this turn ends."

    return FunctionTool(
        delegate,
        name="delegate",
        description=(
            "Submit a task for execution by the system. "
            "The system has full tool access (file, git, search, browse, "
            "perception, web, mobile, media, etc.) and runs independently. "
            "Use for implementation, research, or any task requiring "
            "substantive tool use.  Results arrive in your next turn."
        ),
    )


# ---------------------------------------------------------------------------
# OrchestratorHarness
# ---------------------------------------------------------------------------


class OrchestratorHarness(Harness):
    """Planner + Executor orchestration harness.

    Creates a Planner agent that receives user input and delegates tasks
    to dynamically-created Executor sub-agents.  Unlike the previous
    ``call_executor`` tool approach, executors run at the harness level
    via ``ctx.stream_agent()`` — events flow through the natural yield
    chain for proper usage tracking, lease enforcement, and SSE streaming.

    The planner signals delegation intent via a lightweight ``delegate``
    tool.  It does not know about executor agents — it just submits
    tasks to "the system."
    """

    def __init__(
        self,
        *,
        name: str = "orchestrator",
        planner_model: str,
        planner_instructions: str,
        planner_tools: list,
        executor_tools: list,
        memory_store: Any,
        skill_registry: Any | None = None,
        skill_tool_resolver: Any | None = None,
        hitl_tool: Any | None = None,
        run_id: str,
        conversation_id: str,
        provider: Any,
        max_steps: int = 200,
        hooks: list[tuple] | None = None,
        injected_tool_args: dict[str, str] | None = None,
        context_config: Any | None = None,
        budget_awareness: str = "per-message",
        guardrail_fn: callable | None = None,
        middleware: list | None = None,
        executor_ptc: bool = False,
        executor_ptc_timeout: int = 600,
        executor_max_steps: int = 250,
        cli_tool_catalog: str = "",
        ctx_engine_config: ContextEngineConfig | None = None,
        km_enabled: bool = True,
        user_prefs: dict | None = None,
        is_project_run: bool = False,
        project_title: str = "",
        project_files: list[dict] | None = None,
    ) -> None:
        super().__init__(name=name, middleware=middleware)

        self._planner_model = planner_model
        self._planner_instructions = planner_instructions
        self._planner_tools = planner_tools
        self._executor_tools = executor_tools
        self._memory_store = memory_store
        self._skill_registry = skill_registry
        self._skill_tool_resolver = skill_tool_resolver
        self._hitl_tool = hitl_tool
        self._run_id = run_id
        self._conversation_id = conversation_id
        self._provider = provider
        self._max_steps = max_steps
        self._hooks = hooks or []
        self._injected_tool_args = injected_tool_args or {}
        self._context_config = context_config
        self._budget_awareness = budget_awareness
        self._guardrail_fn = guardrail_fn
        self._executor_ptc = executor_ptc
        self._executor_ptc_timeout = executor_ptc_timeout
        self._executor_max_steps = executor_max_steps
        self._cli_tool_catalog = cli_tool_catalog
        self._ctx_engine_config = ctx_engine_config
        self._km_enabled = km_enabled
        self._user_prefs = user_prefs
        self._is_project_run = is_project_run
        self._project_title = project_title
        self._project_files = project_files

        # Set during execute() — exposed for hot-swap (inject_message)
        self.planner_agent: Agent | None = None

    # -- Hot-swap delegation (called by /inject and /mcp endpoints) ----------

    def inject_message(self, message: str) -> None:
        """Forward inject_message to the planner agent."""
        if self.planner_agent is not None:
            self.planner_agent.inject_message(message)
        else:
            log.warning("inject_message called before planner agent was created")

    @property
    def tools(self) -> dict:
        """Expose planner's tools dict for hot-swap introspection."""
        if self.planner_agent is not None:
            return self.planner_agent.tools
        return {}

    # -- Planner & executor builders -----------------------------------------

    def _build_planner(self, delegate_tool: FunctionTool) -> Agent:
        """Build the planner agent with the delegate tool."""
        planner_tools = [*self._planner_tools, delegate_tool]
        if self._hitl_tool is not None:
            planner_tools.append(self._hitl_tool)

        agent_kwargs: dict[str, Any] = {
            "name": "planner",
            "model": self._planner_model,
            "instructions": self._planner_instructions,
            "tools": planner_tools,
            "max_steps": self._max_steps,
            "memory": self._memory_store,
            "hooks": list(self._hooks),
            "injected_tool_args": self._injected_tool_args,
            "budget_awareness": self._budget_awareness,
            "allow_self_spawn": False,
            "bare_tools": True,
        }
        if self._skill_registry is not None:
            agent_kwargs["skills"] = self._skill_registry
        if self._skill_tool_resolver is not None:
            agent_kwargs["tool_resolver"] = self._skill_tool_resolver
        if self._context_config is not None:
            agent_kwargs["context"] = self._context_config

        planner = Agent(**agent_kwargs)

        planner.hook_manager.add(HookPoint.START, make_planner_fresh_message_start_hook())

        # Propagate conversation_id so the planner can load/save conversation
        # history from the memory store.  Without this, each new run in the
        # same conversation starts with a fresh random UUID and the planner
        # has no context from previous turns.
        planner.conversation_id = self._conversation_id

        if self._guardrail_fn is not None:
            self._guardrail_fn(planner)

        return planner

    def _build_worker_agent(
        self,
        *,
        instructions: str,
        name: str,
        output_type: type | None,
        skip_tool_gate: bool,
        max_steps: int,
        task_for_plan_hook: str = "",
    ) -> Agent:
        """Shared factory for executor and ralph worker construction.

        Centralizes hook composition, tool binding, guardrail attachment,
        and Agent kwargs so executors and ralph workers stay in lockstep.
        See ``_build_executor`` and ``build_ralph_worker`` for callers.

        Dimensions that differ between executor and ralph:
            ``output_type``   — ExecutorResult for executor; None for ralph
            ``skip_tool_gate`` — False for executor; True for ralph
            ``max_steps``     — executor uses self._executor_max_steps;
                               ralph uses its own (typically larger) budget
            ``instructions``  — executor base for executor; executor base
                               + RALPH_WORKFLOW_ADDENDUM for ralph
        """
        # Fresh context engine hook (same config as planner, fresh state)
        worker_hooks: list[tuple] = []
        if self._ctx_engine_config is not None:
            fresh_ctx_hook, _ = make_context_engine_hook(self._ctx_engine_config, conversation_id=self._conversation_id)
            worker_hooks.append((HookPoint.CONTEXT_WINDOW, fresh_ctx_hook))

        # Inherit all non-CONTEXT_WINDOW hooks from the planner, but replace
        # the planner's plan_context_hook with the executor-variant that
        # focuses on the active phase + delegated task.
        plan_hook = make_executor_plan_context_hook(self._conversation_id, task=task_for_plan_hook)
        for hp, fn in self._hooks:
            if hp == HookPoint.CONTEXT_WINDOW:
                continue
            if hp == HookPoint.PRE_LLM_CALL and getattr(fn, "__name__", "") == "plan_context_hook":
                worker_hooks.append((hp, plan_hook))
            else:
                worker_hooks.append((hp, fn))

        # Worker-specific PRE_LLM_CALL hooks
        worker_hooks.append((HookPoint.PRE_LLM_CALL, make_filesystem_first_hook()))
        worker_hooks.append(
            (
                HookPoint.PRE_LLM_CALL,
                make_executor_max_steps_warning_hook(max_steps),
            )
        )

        from agent_server.infra.registry import registry  # noqa: C0415

        worker_tools = list(self._executor_tools)
        if self._hitl_tool is not None and all(
            getattr(t, "name", "") != getattr(self._hitl_tool, "name", "") for t in worker_tools
        ):
            worker_tools.append(self._hitl_tool)

        # Tool gating: gate for executors (only unlocks web_*/mobile_*/git
        # after web_init/mobile_init). Skip entirely for ralph workers —
        # full-stack builders that need those tools preloaded from turn 1.
        tool_gate = None if skip_tool_gate else registry.get_tool_gates(worker_tools)

        # Pre-seed gates that already fired earlier in this conversation.
        # The store is keyed by ``conversation_id``, so unlocks persist
        # across every executor built for the conversation — same run or
        # a later one. Without this, each new executor starts with an
        # empty ``Agent._unlocked_gates`` and would have to re-run
        # web_init/mobile_init/browser — losing state that earlier work
        # (and on-disk scaffolding) already established. For one-shot
        # triggers (web_init, mobile_init), also remove the trigger tool
        # itself so the agent cannot re-scaffold the project.
        from agent_server.infra.registry import get_unlocked_gates  # noqa: C0415

        conv_unlocked = get_unlocked_gates(self._conversation_id)
        if tool_gate and conv_unlocked:
            already_fired = conv_unlocked & tool_gate.keys()
            for trigger_name in list(already_fired):
                gated = tool_gate.pop(trigger_name)
                existing_names = {getattr(t, "name", "") for t in worker_tools}
                for t in gated:
                    if t.name not in existing_names:
                        worker_tools.append(t)
                        existing_names.add(t.name)
                if registry.is_one_shot_trigger(trigger_name):
                    worker_tools = [t for t in worker_tools if getattr(t, "name", "") != trigger_name]

        worker = Agent(
            name=name,
            model=self._planner_model,
            instructions=instructions,
            overflow="hook",
            tools=worker_tools,
            output_type=output_type,
            max_steps=max_steps,
            ptc=self._executor_ptc,
            ptc_timeout=self._executor_ptc_timeout,
            ptc_extra_args=PTC_EXTRA_COMPACTION_ARGS,
            injected_tool_args=self._injected_tool_args,
            hooks=worker_hooks,
            bare_tools=True,
            allow_self_spawn=False,
            tool_gate=tool_gate,
        )

        # Shared guardrails: input filter + message-mode + result-file
        # + prompt leakage + tool blacklist + markdown context storage.
        # The result-file rail is inert for ralph workers (output_type=None
        # means the `finished` event carries a str, not a dict, and the
        # rail returns CONTINUE — see guards.py:_as_dict).
        from agent_server.infra.guards import attach_executor_guardrails  # noqa: C0415

        attach_executor_guardrails(worker)

        return worker

    def _build_executor(self, signal: DelegationSignal) -> Agent:
        """Build a fresh executor agent for a single delegation."""
        return self._build_worker_agent(
            instructions=build_executor_instructions(
                cli_tool_catalog=self._cli_tool_catalog,
                context=signal.context,
                user_prefs=self._user_prefs,
                skill_registry=self._skill_registry,
                is_project_run=self._is_project_run,
                project_title=self._project_title,
                project_files=self._project_files,
            ),
            name=f"executor_{uuid4().hex[:8]}",
            output_type=ExecutorResult,
            skip_tool_gate=False,
            max_steps=self._executor_max_steps,
            task_for_plan_hook=signal.task,
        )

    def build_ralph_worker(
        self,
        *,
        instructions: str,
        name: str,
        max_steps: int,
    ) -> Agent:
        """Build a fresh ralph worker.

        Public counterpart to ``_build_executor`` for the ralph_loop tool.
        Ralph workers share tools, hooks, and guardrails with executors;
        they differ in output shape (``RalphResult`` instead of
        ``ExecutorResult``), tool gating (full toolbox preloaded), and
        turn budget (wider per-story).

        The ``output_type=RalphResult`` is the worker's explicit exit
        signal — once validated, the agent runtime terminates the session,
        which lets the ralph_loop advance to the next iteration with a
        fresh worker. Without a structured terminal output, workers would
        loop past their single story (observed in logs: worker finishes
        story N and starts drifting into story N+1 within the same
        session, violating the one-story-per-session contract).
        """
        return self._build_worker_agent(
            instructions=instructions,
            name=name,
            output_type=RalphResult,
            skip_tool_gate=True,
            max_steps=max_steps,
            task_for_plan_hook="",
        )

    # -- Input formatting ----------------------------------------------------

    @staticmethod
    def _format_planner_input(
        user_input: str,
        execution_results: list[dict[str, Any]],
    ) -> str:
        """Build the planner's input for the next iteration.

        Iteration 0 (no delegations yet) → returns the user request verbatim.

        Iteration N>0 → returns ONLY the most recent delegation result.
        The planner has memory persistence enabled with a stable
        conversation_id, so prior iterations' inputs (including earlier
        delegation results) are already in its conversation history.
        Re-sending the entire ``execution_results`` list each iteration
        produced N² duplication: iteration N's input carried N−1 prior
        results, exo's memory persistence stored that fat string, so
        after N delegations the planner's history held N copies of a
        progressively larger prefix (1.2K → 19.8K token ramp across 16
        iterations, ~160K tokens total).

        This relies on two invariants:
            1. Memory persistence preserves the original user request
               from iteration 0 at the head of the conversation.
            2. ``summarize_messages`` (context.py) preserves the first
               non-hook user message across summarization, so even when
               the context engine fires, the original goal stays anchored
               alongside the summary of intervening turns.
        """
        if not execution_results:
            return user_input

        result = execution_results[-1]
        parts: list[str] = [
            f"--- Task completed: {result['task']} ---",
            f"Summary: {result['result']}",
        ]
        if result.get("key_findings"):
            parts.append("\nKey findings (facts you need to plan from — DO NOT re-delegate to rediscover these):")
            for kf in result["key_findings"]:
                parts.append(f"  - {kf}")
        if result.get("open_decisions"):
            parts.append("\nOpen decisions requiring YOUR judgment (not user's):")
            for od in result["open_decisions"]:
                parts.append(f"  - {od}")
        if result.get("suggested_next_delegations"):
            parts.append("\nExecutor's suggested next delegations (consider these before inventing your own):")
            for sn in result["suggested_next_delegations"]:
                parts.append(f"  - {sn}")
        if result.get("result_files"):
            parts.append("\nExecutor result files:")
            for path in result["result_files"]:
                parts.append(f"  - {path}")
            parts.append(
                "Use these files as attachments when delivering the final "
                "message(result) to the user. Do NOT re-delegate readings of these."
            )
        if result.get("planner_questions"):
            parts.append("\nQuestions the executor wants you to ask the USER:")
            for q in result["planner_questions"]:
                parts.append(f"  - {q}")
        if result.get("messages_sent"):
            parts.append("\nMessages already sent to user by executor:")
            for msg in result["messages_sent"]:
                parts.append(f"  - {msg}")
            parts.append("DO NOT repeat or re-summarize the above — the user has already seen this content.")

        parts.append("\nBased on this result, decide what to do next: delegate another task or respond to the user.")
        return "\n".join(parts)

    # -- Core orchestration loop ---------------------------------------------

    async def execute(self, ctx: HarnessContext) -> AsyncIterator:
        """Core orchestration loop.

        1. Build planner agent with delegate signal tool
        2. Stream planner — user sees thinking in real-time
        3. If planner delegated: build executor, stream via ctx.stream_agent()
        4. Feed executor result back as context, loop
        5. If no delegation: planner responded directly, done

        A continuous Knowledge Manager loop is started by ``run.py``
        around the whole orchestration.  That loop reads the live
        trajectory through the KM's per-conversation message snapshot
        (populated by ``vital_info_hook`` on every PRE_LLM_CALL), not
        through ``ctx.messages`` — the single-agent code path used by
        ``ctx.stream_agent`` does not populate ``ctx.messages``.
        """
        _verbose("orchestrator_started", run_id=self._run_id)
        yield ctx.emit("orchestrator_started", planner="planner", run_id=self._run_id)

        signal = DelegationSignal()
        delegate_tool = _build_delegate_tool(signal)

        # Build planner agent once
        self.planner_agent = self._build_planner(delegate_tool)

        execution_results: list[dict[str, Any]] = []
        planner_turn_count = 0
        stop_reason = "max_iterations"

        for _iteration in range(MAX_DELEGATION_ITERATIONS):
            signal.reset()
            _verbose("planner_streaming", iteration=_iteration)

            # Build planner input with accumulated context
            planner_input = self._format_planner_input(ctx.input, execution_results)

            # Stream planner — events flow to frontend in real-time.
            #
            # Robustness contract (see the diagnosis in harness tests):
            #   1. If the delegate tool fires during a step, we break out
            #      of the planner stream as soon as the step completes.
            #      This prevents the planner from making any further LLM
            #      calls (and therefore any further failures) after a
            #      delegation has already been captured.
            #   2. If the planner stream raises an exception, we do NOT
            #      immediately abort the iteration.  The delegate tool
            #      may have fired *before* the exception — in that case
            #      signal.task is set and we still have a valid task to
            #      execute.  The old behaviour ``break``-ed here and
            #      silently dropped any pending delegation, which is
            #      exactly the bug reported in production logs.
            planner_failed = False
            planner_error: Exception | None = None
            try:
                # Role assignment for ``planner_input`` depends on whether
                # it is real user input or an executor-produced result.
                #
                # * Iteration 0 — ``planner_input`` IS the real user's
                #   request.  Pass it as the ``input`` arg so exo's runner
                #   wraps it as a ``UserMessage`` and persists it as a
                #   ``HumanMemory`` — the correct "user turn" semantics.
                #
                # * Iteration N>0 — ``planner_input`` is a delegation
                #   result produced by the executor (another AI agent).
                #   Pass it via ``messages=[AssistantMessage(...)]`` so
                #   the planner's live history carries it as an assistant
                #   turn.  ``input`` is empty — exo still appends a
                #   trailing ``UserMessage("")`` (and persists it as an
                #   empty ``HumanMemory``), which the LLM tolerates.
                #
                # Either way, exo's memory persistence reconstructs prior
                # turns from the DB on every call, so we don't pass
                # historical context explicitly.
                if execution_results:
                    _stream_input: Any = ""
                    _stream_messages: list | None = [AssistantMessage(content=planner_input)]
                else:
                    _stream_input = planner_input
                    _stream_messages = None

                async for event in ctx.stream_agent(
                    self.planner_agent,
                    _stream_input,
                    messages=_stream_messages,
                    detailed=True,
                    provider=self._provider,
                ):
                    yield event

                    # Count planner turns for KM triggering
                    evt_type = getattr(event, "type", None)
                    if evt_type == "step":
                        status = getattr(event, "status", None)
                        if status == "completed":
                            planner_turn_count += 1

                            if (
                                self._km_enabled
                                and planner_turn_count % 5 == 0
                                and should_run_km(self._run_id, planner_turn_count * 2)
                            ):
                                _verbose("km_trigger", trigger="turn_fallback", scope="overall")
                                _km_task = asyncio.create_task(
                                    run_km(
                                        conversation_id=self._conversation_id,
                                        run_id=self._run_id,
                                        messages=get_messages_snapshot(self._conversation_id),
                                        provider=self._provider,
                                        model=self._planner_model,
                                        trigger="turn_fallback",
                                        scope="overall",
                                        ctx_engine_config=self._ctx_engine_config,
                                    ),
                                    name=f"km-planner-turn-{planner_turn_count}",
                                )
                                _km_task.add_done_callback(_km_task_done)

                            # Early exit: if the delegate tool fired
                            # during this step, stop the planner now so
                            # that no subsequent LLM call can fail and
                            # kill the run with an unrelated error.
                            if signal.task is not None:
                                _verbose("delegation_detected", task=signal.task)
                                log.debug(
                                    "Delegate signal captured at planner step %d "
                                    "(iteration %d), stopping planner stream early",
                                    planner_turn_count,
                                    _iteration,
                                )
                                break

            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                normalized_exc = _normalize_stream_exception(exc)
                error_text = _error_text(normalized_exc)
                planner_failed = True
                planner_error = normalized_exc
                _verbose("planner_error", error=error_text, iteration=_iteration)
                if _is_policy_block(normalized_exc):
                    log.warning(
                        "Planner streaming blocked on iteration %d: %s",
                        _iteration,
                        error_text,
                    )
                else:
                    log.error(
                        "Planner streaming failed on iteration %d: %r",
                        _iteration,
                        normalized_exc,
                        exc_info=True,
                    )
                yield ctx.emit(
                    "planner_error",
                    error=error_text,
                    error_type=type(normalized_exc).__name__,
                    blocked_by_guardrail=_is_policy_block(normalized_exc),
                    iteration=_iteration,
                )

            # Check if planner delegated a task.  This is evaluated on
            # BOTH the happy path and the error path — a planner error
            # that happened after a successful delegate call must still
            # produce executor execution, otherwise the delegation is
            # silently dropped (the reported bug).
            if signal.task is None:
                if planner_failed:
                    stop_reason = "planner_error"
                    _verbose("planner_error", error=repr(planner_error), iteration=_iteration)
                    log.error(
                        "Orchestrator stopping: planner errored on iteration %d with no delegation signal (error=%r)",
                        _iteration,
                        planner_error,
                    )
                else:
                    stop_reason = "planner_direct_response"
                    _verbose("planner_direct_response", iteration=_iteration)
                    log.info(
                        "Orchestrator stopping: planner responded directly (iteration %d)",
                        _iteration,
                    )
                break

            if planner_failed:
                _verbose("planner_error_with_delegation")
                log.info(
                    "Planner errored on iteration %d but delegate signal was "
                    "set — proceeding with executor (task: %.200s)",
                    _iteration,
                    signal.task,
                )

            # Planner → executor handoff: invalidate the KM advise cache
            # so the executor's next LLM call reads freshly-prefetched,
            # role-scoped guidance instead of whatever was left over from
            # the planner's view of the trajectory.
            _verbose("advise_cache_invalidated", reason="handoff", role="both")
            invalidate_advise_cache(self._conversation_id, reason="handoff", role="both")

            # Build and stream executor — events flow through natural yield chain
            executor = self._build_executor(signal)
            executor_name = executor.name
            _verbose("executor_created", executor_name=executor_name, use_history=signal.use_history)
            _verbose("handoff_to_executor", executor_name=executor_name)

            # Append execution contract so planner<->executor handoff is
            # explicit about communication boundaries and result delivery.
            signal.task += (
                "\n\nIMPORTANT EXECUTOR CONTRACT:\n"
                "- If message tool is available, use only type='info' and keep it brief.\n"
                "- Never use message types 'ask' or 'result'.\n"
                "- Populate `summary` (under 512 words) with what you did AND "
                "what the planner needs to know to choose the next step. "
                "Calibrate depth to the task: generous for ingestion/exploration, "
                "tight for narrow tasks. A thin summary forces the planner to "
                "re-delegate for basic facts.\n"
                "- Populate `key_findings` with 3-7 structured bullets of non-obvious "
                "facts the planner needs (existing files, tech constraints, gaps, "
                "things you had to infer). Not a log of what you did — that's summary.\n"
                "- Populate `open_decisions` with anything that needs planner judgment "
                "(not user judgment — that's planner_questions). Empty if everything "
                "was clear.\n"
                "- Populate `suggested_next_delegations` with 1-3 concrete next tasks "
                "the planner could delegate. You just saw the work; suggest what "
                "should happen next.\n"
                "- Write substantive outputs to markdown files and list absolute paths "
                "in result_files.\n"
                "- If user input is required, put exact questions in planner_questions.\n"
                "- If any info messages were sent to the user, summarize each in "
                "messages_sent_to_user."
            )
            result_parts: list[str] = []
            executor_turn_count = 0
            executor_completed = False
            executor_error: Exception | None = None

            try:
                async for event in ctx.stream_agent(
                    executor,
                    signal.task,
                    messages=list(ctx.messages) if signal.use_history else None,
                    detailed=True,
                    provider=self._provider,
                ):
                    # Stamp source_agent for frontend identification
                    if hasattr(event, "agent_name"):
                        pass  # agent_name already set by the executor
                    yield event

                    if isinstance(event, TextEvent):
                        result_parts.append(event.text)

                    evt_type = getattr(event, "type", None)
                    if evt_type == "step":
                        status = getattr(event, "status", None)
                        if status == "completed":
                            executor_turn_count += 1

                            # The soft-stop warning at ``max_steps - 3`` now
                            # runs as a PRE_LLM_CALL hook
                            # (``make_executor_max_steps_warning_hook``).

                            # KM every 20 executor turns (loosened from 10
                            # because the knowledge manager is multi-step and more
                            # expensive per run than the old extractor).
                            if (
                                self._km_enabled
                                and executor_turn_count % 20 == 0
                                and should_run_km(executor_name, executor_turn_count * 2)
                            ):
                                _verbose("km_trigger", trigger="turn_fallback", scope="worker")
                                _km_task = asyncio.create_task(
                                    run_km(
                                        conversation_id=self._conversation_id,
                                        run_id=self._run_id,
                                        messages=get_messages_snapshot(self._conversation_id),
                                        provider=self._provider,
                                        model=self._planner_model,
                                        trigger="turn_fallback",
                                        scope="worker",
                                        worker_task=signal.task or "",
                                        ctx_engine_config=self._ctx_engine_config,
                                    ),
                                    name=f"km-executor-{executor_name}-turn-{executor_turn_count}",
                                )
                                _km_task.add_done_callback(_km_task_done)
                    elif evt_type == "status":
                        evt_status = getattr(event, "status", None)
                        evt_agent = getattr(event, "agent_name", "")
                        if evt_status == "completed" and evt_agent == executor_name:
                            executor_completed = True
                            _verbose("executor_completed", executor_name=executor_name, turns=executor_turn_count)

            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                normalized_exc = _normalize_stream_exception(exc)
                error_text = _error_text(normalized_exc)
                _verbose("executor_error", executor_name=executor_name, error=error_text)
                if _is_policy_block(normalized_exc):
                    log.warning(
                        "Executor %s blocked by guardrail: %s",
                        executor_name,
                        error_text,
                    )
                else:
                    log.error(
                        "Executor %s failed: %s",
                        executor_name,
                        normalized_exc,
                        exc_info=True,
                    )
                executor_error = normalized_exc
                yield ctx.emit(
                    "executor_error",
                    executor=executor_name,
                    error=error_text,
                    error_type=type(normalized_exc).__name__,
                    blocked_by_guardrail=_is_policy_block(normalized_exc),
                )

            executor_output = "".join(result_parts)

            # Carry unlocked gates forward so every subsequent executor
            # built for this conversation — same run or a later one —
            # inherits them (see ``_build_worker_agent``). Without this,
            # web_init/mobile_init/browser would re-gate each time.
            fired = getattr(executor, "_unlocked_gates", None)
            if fired:
                from agent_server.infra.registry import mark_gates_unlocked  # noqa: C0415

                mark_gates_unlocked(self._conversation_id, set(fired))

            # Detect silent max_steps exhaustion (runner ends without StatusEvent)
            if not executor_completed and executor_error is None:
                _verbose("executor_truncated", executor_name=executor_name)
                log.warning(
                    "Executor %s exhausted max_steps=%d without natural completion (turns=%d). Task may be incomplete.",
                    executor_name,
                    self._executor_max_steps,
                    executor_turn_count,
                )
                executor_output += (
                    "\n\n[EXECUTOR TRUNCATED: This executor reached its step limit "
                    f"({self._executor_max_steps} steps) without producing a final "
                    "answer. The task may be incomplete. Consider re-delegating "
                    "the remaining work.]"
                )

            if executor_error is not None:
                executor_output += (
                    f"\n\n[EXECUTOR ERROR: {executor_error}. "
                    "The task failed. Consider retrying or breaking it into "
                    "smaller steps.]"
                )

            # Knowledge Manager run after executor completes.  Awaited
            # (not fire-and-forget) so the planner's next iteration
            # sees anything the KM just captured.  No timeout — LLMs
            # can be slow, especially local ones, and cutting the run
            # short loses the write.
            if self._km_enabled:
                _verbose("km_trigger", trigger="post_executor", scope="overall")
                try:
                    await run_km(
                        conversation_id=self._conversation_id,
                        run_id=self._run_id,
                        messages=get_messages_snapshot(self._conversation_id),
                        provider=self._provider,
                        model=self._planner_model,
                        trigger="post_executor",
                        scope="overall",
                        ctx_engine_config=self._ctx_engine_config,
                    )
                    _verbose("km_completed", trigger="post_executor")
                except Exception as exc:
                    _verbose("km_failed", error=str(exc))
                    log.warning(
                        "Knowledge Manager post-executor run failed for %s: %s",
                        executor_name,
                        exc,
                        exc_info=True,
                    )

            # Executor → planner handoff: new items may have been persisted
            # and the next planner turn needs fresh role-specific guidance.
            _verbose("handoff_to_planner", executor_name=executor_name)
            _verbose("advise_cache_invalidated", reason="handoff", role="both")
            invalidate_advise_cache(self._conversation_id, reason="handoff", role="both")

            # Try to extract structured handoff fields from executor output.
            planner_result = executor_output
            messages_sent: list[str] = []
            planner_questions: list[str] = []
            result_files: list[str] = []
            key_findings: list[str] = []
            open_decisions: list[str] = []
            suggested_next_delegations: list[str] = []
            try:
                parsed = ExecutorResult.model_validate_json(executor_output)
                messages_sent = parsed.messages_sent_to_user
                planner_questions = parsed.planner_questions
                result_files = parsed.result_files
                key_findings = parsed.key_findings
                open_decisions = parsed.open_decisions
                suggested_next_delegations = parsed.suggested_next_delegations
                planner_result = (parsed.summary or parsed.result or "").strip() or executor_output
            except Exception:
                pass  # output may not be valid JSON (truncated, error, etc.)

            # Hard backstop for the summary/result string passed back to the
            # planner. Stated cap in prompts/contract is 512 words (~3 KB);
            # this backstop at 16 KB leaves ~5x headroom for LLM overshoot
            # before truncation kicks in. Keep this loose — the stated cap
            # does the calibration; this only protects against runaway dumps.
            if len(planner_result) > 16_000:
                planner_result = planner_result[:16_000] + "\n...[truncated]"

            # Record result for next planner iteration
            execution_results.append(
                {
                    "task": signal.task,
                    "executor": executor_name,
                    "result": planner_result,
                    "planner_questions": planner_questions,
                    "result_files": result_files,
                    "messages_sent": messages_sent,
                    "key_findings": key_findings,
                    "open_decisions": open_decisions,
                    "suggested_next_delegations": suggested_next_delegations,
                }
            )

        if stop_reason == "max_iterations":
            _verbose("orchestrator_max_iterations", max_iterations=MAX_DELEGATION_ITERATIONS)
            log.warning(
                "Orchestrator reached MAX_DELEGATION_ITERATIONS=%d. "
                "This may indicate a planner loop or overly complex task.",
                MAX_DELEGATION_ITERATIONS,
            )

        _verbose(
            "orchestrator_completed",
            reason=stop_reason,
            planner_turns=planner_turn_count,
            delegations=len(execution_results),
        )
        log.info(
            "Orchestrator completed: reason=%s planner_turns=%d delegations=%d",
            stop_reason,
            planner_turn_count,
            len(execution_results),
        )

        # Final emit
        yield ctx.emit(
            "orchestrator_completed",
            planner_turns=planner_turn_count,
            delegations=len(execution_results),
            run_id=self._run_id,
            stop_reason=stop_reason,
        )


# ---------------------------------------------------------------------------
# Factory function for server.py integration
# ---------------------------------------------------------------------------


def build_orchestrator_harness(
    *,
    planner_model: str,
    planner_instructions: str,
    all_native_tools: list,
    memory_store: Any,
    skill_registry: Any | None = None,
    skill_tool_resolver: Any | None = None,
    hitl_tool: Any | None = None,
    run_id: str,
    conversation_id: str,
    provider: Any,
    max_steps: int = 200,
    hooks: list[tuple] | None = None,
    injected_tool_args: dict[str, str] | None = None,
    context_config: Any | None = None,
    budget_awareness: str = "per-message",
    guardrail_fn: callable | None = None,
    executor_ptc: bool = False,
    executor_ptc_timeout: int = 600,
    executor_max_steps: int = 250,
    cli_tool_catalog: str = "",
    ctx_engine_config: ContextEngineConfig | None = None,
    km_enabled: bool = True,
    user_prefs: dict | None = None,
    is_project_run: bool = False,
    project_title: str = "",
    project_files: list[dict] | None = None,
) -> OrchestratorHarness:
    """Build an OrchestratorHarness with automatic tool partitioning.

    ``all_native_tools`` is the full list from the registry.  This function
    splits them into planner tools (plan/message/delegate) and
    executor tools (everything except plan and delegate).

    PTC (Programmatic Tool Calling) is disabled on executor agents by default.
    Tools are exposed directly unless explicit wiring enables PTC.
    """
    planner_tools = [t for t in all_native_tools if t.name in PLANNER_TOOL_NAMES]
    executor_tools = [t for t in all_native_tools if t.name not in EXECUTOR_EXCLUDED_TOOLS]

    return OrchestratorHarness(
        planner_model=planner_model,
        planner_instructions=planner_instructions,
        planner_tools=planner_tools,
        executor_tools=executor_tools,
        memory_store=memory_store,
        skill_registry=skill_registry,
        skill_tool_resolver=skill_tool_resolver,
        hitl_tool=hitl_tool,
        run_id=run_id,
        conversation_id=conversation_id,
        provider=provider,
        max_steps=max_steps,
        hooks=hooks,
        injected_tool_args=injected_tool_args,
        context_config=context_config,
        budget_awareness=budget_awareness,
        guardrail_fn=guardrail_fn,
        executor_ptc=executor_ptc,
        executor_ptc_timeout=executor_ptc_timeout,
        executor_max_steps=executor_max_steps,
        cli_tool_catalog=cli_tool_catalog,
        ctx_engine_config=ctx_engine_config,
        km_enabled=km_enabled,
        user_prefs=user_prefs,
        is_project_run=is_project_run,
        project_title=project_title,
        project_files=project_files,
    )
