"""Unified Knowledge Manager runner.

One runner, one LLM call per invocation, one ``KMOutput``.  Replaces
the old ``run_km_write`` + ``run_km_advise`` split:

- ``run_km`` builds a single agent with a stable system prompt
  (``KM_BASE_INSTRUCTIONS + KM_TASK_SUFFIX``), runs it once, and
  dispatches the three-way output (files + nudges + guidance blocks)
  to the right downstream sinks:
    * ``files_*``    → already written to disk by the ``km_*`` tools
                       during the run; the runner bumps bookkeeping
                       (mark_wrote, bump_active_items_version, invalidate
                       advise cache).
    * ``nudges``     → ``push_nudge`` per entry
    * ``for_planner`` / ``for_executor`` → ``store_advice`` as a
                       ``KMAdvice`` so the PRE_LLM_CALL injection hook
                       picks it up on the next turn.

Two scopes:

- ``scope="worker"``  — the caller is inside an executor or ralph
                         worker context. The runner prepends a
                         synthesised vital frame (goal + plan + phase +
                         delegated task) to the trajectory so the KM
                         has the *why* front-and-centre without reading
                         the whole planner history.
- ``scope="overall"`` — the caller is at planner / orchestration level.
                         The trajectory is passed through as-is.

KV-cache discipline: the system prompt is a constant, the tool list is
a constant, the ``output_type`` is a constant, and per-call variation
lives in the ``input`` argument to ``exo.run`` which is appended as the
final user message. Everything before the tail caches across runs on
the same conversation.
"""

from __future__ import annotations

import logging
from typing import Any

from agent_server.config import AGENT_KM_ENABLED
from agent_server.engine.context import ContextEngineConfig

from .models import KMAdvice, KMNudge, KMOutput, KMScope, KMTrigger
from .prompts import KM_BASE_INSTRUCTIONS, KM_TASK_SUFFIX
from .state import (
    _in_km_run,
    bump_active_items_version,
    get_active_items_version,
    get_km_lock,
    invalidate_advise_cache,
    is_trivial_window,
    km_run_rate_limited,
    mark_km_ran,
    mark_wrote,
    push_nudge,
    should_run_km,
    store_advice,
    trajectory_hash,
)

log = logging.getLogger("knowledge_manager.runner")


async def _record_km_usage(run_id: str, result: Any) -> None:
    """Fold a KM ``RunResult``'s token usage into the parent run's billing.

    Looks up the shared ``UsageTotals`` registered by ``engine/run.py``
    under ``run_id`` and merges the KM's input/output tokens into it,
    then triggers a backend sync. No-op if the parent run did not
    register a context (e.g. tests calling ``run_km`` standalone).
    """
    usage = getattr(result, "usage", None)
    if usage is None:
        return

    from agent_server.infra import (  # noqa: C0415
        get_run_usage_context,
        sync_run_usage,
        update_usage_totals,
    )

    ctx = get_run_usage_context(run_id)
    if ctx is None:
        return

    payload: dict[str, Any] = {
        "type": "usage",
        "usage": {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        },
    }
    update_usage_totals(ctx.usage_totals, payload)

    try:
        await sync_run_usage(run_id, ctx.usage_totals, sandbox_id=ctx.sandbox_id)
    except Exception:
        log.warning("run_km: sync_run_usage failed for run_id=%s", run_id, exc_info=True)


# Agent budget.  The run is multi-step (km_list → km_read → km_write /
# km_delete / km_nudge → emit KMOutput), and each step is a tool round
# trip, not a full LLM turn, so 8 is comfortable for the common cases.
KM_MAX_STEPS = 8


# Concatenated once at import time; passed verbatim as the Agent's
# ``instructions`` on every call so KV-cache prefixes reuse across runs.
_KM_SYSTEM_PROMPT: str = KM_BASE_INSTRUCTIONS + "\n\n" + KM_TASK_SUFFIX


# ─────────────────────────────────────────────────────────────────────────
# Prompt builders
# ─────────────────────────────────────────────────────────────────────────


def _build_tail_instruction(
    *,
    conversation_id: str,
    scope: KMScope,
    trigger: KMTrigger,
) -> str:
    """Build the per-call tail instruction passed as ``exo.run(input=…)``.

    This is the only prompt byte that varies between runs on the same
    conversation.  It is appended as the final user message, so
    everything before it (system prompt, tools, trajectory prefix)
    stays cacheable.
    """
    return (
        f"A Knowledge Manager sweep has been invoked (scope={scope}, "
        f"trigger={trigger}). Follow the <workflow> in your instructions. "
        f"Most invocations produce no output — if the window above has "
        f"nothing new worth persisting, no nudge-worthy behaviour, and "
        f"nothing step-critical to inject, return "
        f"`KMOutput(nothing_to_do=True)` and stop.\n"
        f"\n"
        f"conversation_id: {conversation_id}"
    )


def _build_worker_frame(
    *,
    conversation_id: str,
    worker_task: str,
) -> str | None:
    """Synthesise the vital frame prepended to worker-scope trajectories.

    Returns ``None`` if no plan exists and no task was provided (in
    which case the runner falls back to just the trajectory).  Reuses
    the existing helper in ``tools/plan.py`` so the frame content is
    identical to what the executor's own plan-context hook would see.
    """
    try:
        from agent_server.engine.hooks import format_executor_plan_context  # noqa: C0415
    except Exception:
        return None

    try:
        frame = format_executor_plan_context(
            conversation_id=conversation_id,
            task=worker_task,
        )
    except Exception:
        log.debug("worker frame build failed", exc_info=True)
        return None
    return frame


# ─────────────────────────────────────────────────────────────────────────
# Output dispatch
# ─────────────────────────────────────────────────────────────────────────


def _dispatch_output(
    output: KMOutput,
    *,
    conversation_id: str,
    trigger: KMTrigger,
    scope: KMScope,
    messages: list,
) -> None:
    """Route a KMOutput to its downstream sinks.

    - File lists: the ``km_*`` tools already wrote to disk during the
      run; the runner's job is to update bookkeeping (mark_wrote,
      bump_active_items_version, invalidate the advise cache).
    - Nudges: push each into the per-conversation nudge queue.
    - Guidance blocks: wrap in a ``KMAdvice`` and store in the advise
      cache so the PRE_LLM_CALL injection hook picks them up.
    """
    for nudge in output.nudges:
        if not isinstance(nudge, KMNudge):
            continue
        push_nudge(conversation_id, nudge)

    if output.touched_files():
        mark_wrote(conversation_id)
        version = bump_active_items_version(conversation_id)
        invalidate_advise_cache(conversation_id, reason="write_persisted")
        log.info(
            "km_run: conv=%s scope=%s trigger=%s wrote=%d updated=%d superseded=%d nudges=%d version=%d summary=%s",
            conversation_id[:8],
            scope,
            trigger,
            len(output.files_written),
            len(output.files_updated),
            len(output.files_superseded),
            len(output.nudges),
            version,
            output.summary or "(no summary)",
        )

    if output.has_guidance():
        advice = KMAdvice(
            for_planner=output.for_planner,
            for_executor=output.for_executor,
            trajectory_hash=trajectory_hash(messages),
            active_items_version=get_active_items_version(conversation_id),
        )
        store_advice(conversation_id, advice)
        if not output.touched_files():
            # Non-file runs that still produced guidance — worth one
            # info line for observability.
            log.info(
                "km_run: conv=%s scope=%s trigger=%s planner=%d chars executor=%d chars nudges=%d",
                conversation_id[:8],
                scope,
                trigger,
                len(output.for_planner),
                len(output.for_executor),
                len(output.nudges),
            )

    if output.is_silent():
        # Silent runs are the expected common case — debug only so
        # production logs do not fill with no-op notices.
        log.debug(
            "km_run: conv=%s scope=%s trigger=%s silent",
            conversation_id[:8],
            scope,
            trigger,
        )


import json as _json
import re as _re

# Strip ```json ... ``` or ``` ... ``` code fences while preserving the
# inner content.  Some models wrap structured output in a code block
# even when the schema asks for raw JSON.
_CODE_FENCE_RE = _re.compile(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", _re.DOTALL)

# Heuristic: grab the first {...} balanced object from a freeform string.
# Cheap — relies on the fact that the model rarely emits multiple
# top-level JSON objects.
_FIRST_OBJECT_RE = _re.compile(r"\{.*\}", _re.DOTALL)


def _coerce_output(
    raw_output: Any,
    *,
    conversation_id: str,
    scope: KMScope,
    trigger: KMTrigger,
) -> KMOutput:
    """Best-effort conversion of a run result into a ``KMOutput``.

    Small / local models sometimes drop the structured-output schema
    and return freeform text instead.  Rather than warning and
    erroring out on every such run, this function tries progressively
    looser parses:

    1. Already a ``KMOutput`` instance → pass through.
    2. Raw pydantic JSON validate on the stringified output.
    3. Strip markdown code fences, then validate.
    4. Extract the first ``{...}`` balanced object from the text and
       validate.

    If all four fail, return a silent ``nothing_to_do`` output and log
    at debug (NOT warning) — a small model returning prose is an
    expected failure mode under the silence-is-default policy, not a
    bug to flag loudly.
    """
    if isinstance(raw_output, KMOutput):
        return raw_output

    text = _stringify_output(raw_output)
    if not text:
        log.debug(
            "km_run: empty agent output (conv=%s scope=%s trigger=%s) — silent",
            conversation_id[:8],
            scope,
            trigger,
        )
        return KMOutput(nothing_to_do=True, summary="empty agent output")

    # Pass 1: straight JSON validate.
    try:
        return KMOutput.model_validate_json(text)
    except Exception:
        pass

    # Pass 2: strip markdown code fences, try again.
    fence = _CODE_FENCE_RE.search(text)
    if fence is not None:
        inner = fence.group(1).strip()
        try:
            return KMOutput.model_validate_json(inner)
        except Exception:
            pass

    # Pass 3: extract the first balanced {...} and try again.
    match = _FIRST_OBJECT_RE.search(text)
    if match is not None:
        candidate = match.group(0)
        try:
            return KMOutput.model_validate_json(candidate)
        except Exception:
            # Last resort: loose json.loads → construct from dict, in
            # case the candidate is valid JSON but doesn't match the
            # schema strictly.
            try:
                raw = _json.loads(candidate)
                if isinstance(raw, dict):
                    return KMOutput.model_validate(raw)
            except Exception:
                pass

    log.debug(
        "km_run: agent returned unstructured output (conv=%s scope=%s trigger=%s) — treating as silent. head=%r",
        conversation_id[:8],
        scope,
        trigger,
        text[:160],
    )
    return KMOutput(
        nothing_to_do=True,
        summary="agent returned unstructured output",
    )


def _stringify_output(raw_output: Any) -> str:
    """Convert an agent output into a string we can try to parse.

    Exo's ``AgentOutput`` may be a pydantic model, a dict, a string,
    or something else.  Probe a few common attributes before falling
    back to ``str()``.
    """
    if raw_output is None:
        return ""
    if isinstance(raw_output, str):
        return raw_output
    for attr in ("content", "text", "message", "output"):
        value = getattr(raw_output, attr, None)
        if isinstance(value, str) and value.strip():
            return value
    try:
        return str(raw_output)
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────
# The unified runner
# ─────────────────────────────────────────────────────────────────────────


async def run_km(
    *,
    conversation_id: str,
    run_id: str,
    messages: list,
    provider: Any,
    model: str,
    trigger: KMTrigger,
    scope: KMScope = "overall",
    ctx_engine_config: ContextEngineConfig | None = None,
    worker_task: str = "",
    force: bool = False,
) -> KMOutput:
    """Run the Knowledge Manager.

    Fire-and-forget safe: catches every exception internally and
    returns a neutral ``KMOutput(nothing_to_do=True)`` on failure.

    Args:
        conversation_id: Conversation scope for the KM store.
        run_id: Current run ID; recorded as ``source_run_id`` on new
            files written during this run.
        messages: Trajectory snapshot. The caller is responsible for
            passing a sensible list — for worker scope, this is the
            worker's own ``msg_list`` captured at PRE_LLM_CALL time;
            for overall scope, this is the planner's ``ctx.messages``.
        provider: LLM provider instance (already resolved by the
            runner in ``run.py``).
        model: Model id to use for the KM agent.
        trigger: Which event caused this run. Logged and included in
            the tail instruction.
        scope: ``"worker"`` or ``"overall"``. Determines whether a
            vital frame is prepended and which in-flight lock / rate
            limit key is used.
        ctx_engine_config: Context engine config for the shared KM
            context hook. When ``None``, no CONTEXT_WINDOW hook is
            installed on the KM agent (used by tests).
        worker_task: Delegated task string. Used only when
            ``scope="worker"`` to populate the vital frame.
        force: If True, skip the gate checks (``should_run_km``,
            ``is_trivial_window``, ``km_run_rate_limited``). Used by
            ``pre_compression`` and ``force_error_strike``.

    Returns:
        The ``KMOutput`` produced by the agent (or a neutral one on
        early return / failure).
    """
    if not AGENT_KM_ENABLED:
        return KMOutput(nothing_to_do=True, summary="km disabled")

    # ── Guard: no re-entry inside the KM's own context hook path ──
    if _in_km_run.get(False):
        log.debug(
            "run_km: re-entry blocked (conv=%s scope=%s)",
            conversation_id[:8],
            scope,
        )
        return KMOutput(nothing_to_do=True, summary="re-entry blocked")

    # ── Guard: single run per (conv, scope) at a time ──
    lock = await get_km_lock(conversation_id, scope)
    if lock.locked():
        log.debug(
            "run_km: already in flight (conv=%s scope=%s trigger=%s) — skipping",
            conversation_id[:8],
            scope,
            trigger,
        )
        return KMOutput(nothing_to_do=True, summary="in flight")

    async with lock:
        # ── Gates (bypassed when force=True) ──
        if not force:
            if not should_run_km(conversation_id, len(messages)):
                return KMOutput(nothing_to_do=True, summary="threshold not met")
            if is_trivial_window(messages):
                return KMOutput(nothing_to_do=True, summary="trivial window")
            if km_run_rate_limited(conversation_id, scope):
                return KMOutput(nothing_to_do=True, summary="rate limited")

        # Lazy imports: avoid circulars and defer Django-touching code
        # until we are actually about to run.
        from exo import Agent, run  # noqa: C0415
        from exo.hooks import HookPoint  # noqa: C0415
        from exo.types import AssistantMessage  # noqa: C0415

        from agent_server.engine.hooks import (  # noqa: C0415
            billing_estimate_fallback_hook,
            get_km_context_hook,
        )
        from tools.km import (  # noqa: C0415
            KM_TOOLS,
            clear_km_conversation,
            set_km_conversation,
        )

        # ── Shared KM context hook — one per conversation, reused ──
        km_hooks: list[tuple] = []
        ctx_pair = await get_km_context_hook(conversation_id, ctx_engine_config)
        if ctx_pair is not None:
            ctx_hook, _state = ctx_pair
            km_hooks.append((HookPoint.CONTEXT_WINDOW, ctx_hook))

        # KM runs against the same provider as the planner — install the
        # zero-usage billing fallback so local-model KM steps still get
        # billed via estimated tokens × pricing table.
        km_hooks.append((HookPoint.POST_LLM_CALL, billing_estimate_fallback_hook))

        # ── Build the KM message list ──
        prior_messages: list[Any] = []
        if scope == "worker":
            frame = _build_worker_frame(
                conversation_id=conversation_id,
                worker_task=worker_task,
            )
            if frame:
                prior_messages.append(AssistantMessage(content=frame))
        prior_messages.extend(messages)

        tail_instruction = _build_tail_instruction(
            conversation_id=conversation_id,
            scope=scope,
            trigger=trigger,
        )

        # ── Run the agent ──
        #
        # ``model`` and ``provider`` are the SAME values the planner,
        # executor, and ralph workers are using on this run: they
        # originate from the single ``model`` / ``provider`` pair
        # resolved in ``run.py`` and are threaded through every caller
        # unchanged (harness ``self._planner_model`` / ``self._provider``
        # for harness-side triggers; the hook factory closures for
        # prefetch / content-burst / pre-compress / periodic).  The KM
        # deliberately does NOT resolve its own model — one unified LLM
        # config is the whole point.
        token_run = _in_km_run.set(True)
        token_conv = set_km_conversation(conversation_id)
        try:
            agent = Agent(
                name="knowledge_manager",
                model=model,
                instructions=_KM_SYSTEM_PROMPT,  # stable across calls
                tools=list(KM_TOOLS),  # stable order
                output_type=KMOutput,
                max_steps=KM_MAX_STEPS,
                overflow="hook",
                hooks=km_hooks,
                injected_tool_args={
                    "brief": "A one-sentence preamble describing the purpose of this operation.",
                },
                bare_tools=True,
                allow_self_spawn=False,
            )

            result = await run(
                agent,
                tail_instruction,
                messages=prior_messages,
                provider=provider,
            )

            # Bill the KM's token usage against the parent run. The KM
            # runs outside the main event loop in ``engine/run.py`` so
            # its UsageEvents are not observed there. We fold them into
            # the shared ``UsageTotals`` registered by the parent and
            # trigger a backend sync so credits settle correctly.
            await _record_km_usage(run_id, result)

            output = _coerce_output(
                getattr(result, "output", None),
                conversation_id=conversation_id,
                scope=scope,
                trigger=trigger,
            )

            _dispatch_output(
                output,
                conversation_id=conversation_id,
                trigger=trigger,
                scope=scope,
                messages=messages,
            )

            mark_km_ran(conversation_id, scope)
            return output

        except Exception:
            log.warning(
                "run_km: failed (conv=%s scope=%s trigger=%s)",
                conversation_id[:8],
                scope,
                trigger,
                exc_info=True,
            )
            return KMOutput(nothing_to_do=True, summary="km run failed")
        finally:
            clear_km_conversation(token_conv)
            _in_km_run.reset(token_run)
