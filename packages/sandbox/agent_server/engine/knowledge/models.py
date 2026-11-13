"""Pydantic output types and type literals for the Knowledge Manager.

A single unified runner (``run_km``) emits one ``KMOutput`` per
invocation, carrying file writes, nudges, and role-scoped guidance
blocks all at once.  Each of those three pieces is optional — most
runs should return ``nothing_to_do=True`` with empty collections.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

# Where a KM run was fired from — used only for logging and dedup.
KMTrigger = Literal[
    "post_executor",  # fire-and-await after an executor finishes
    "pre_compression",  # fired from the context engine right before summarize/compact
    "content_burst",  # 3+ consecutive content-heavy tool calls
    "prefetch",  # POST_LLM_CALL cache-warming after a turn
    "periodic",  # continuous background loop tick
    "turn_fallback",  # every-N-turns safety net
    "force_error_strike",  # 3+ consecutive same-error strikes
    "manual",  # test / REPL / explicit user trigger
]


# Scope of the trajectory the KM sees on this run.
#
# - ``worker``  — the executor or ralph worker's own context window,
#                 preceded by a synthesised vital frame (goal, plan,
#                 phase, current task).  Window is small; overflow is
#                 rare.
# - ``overall`` — the planner's full orchestration view, which already
#                 includes the plan hook injection and executor result
#                 summaries.  Window is larger.
KMScope = Literal["worker", "overall"]


TargetRole = Literal["planner", "executor", "both"]
NudgeUrgency = Literal["low", "medium", "high"]


class KMNudge(BaseModel):
    """A short steering message the KM wants injected into a target
    agent's next LLM call.

    Nudges are ephemeral — they live in memory, are consumed on the
    first matching injection, and never persist to disk.  Use them for
    missed persistence, goal drift, repeated failure, forgotten
    actions, or expensive redos.
    """

    title: str = Field(
        ...,
        description="Short internal label (logged, not injected).",
    )
    target_role: TargetRole = Field(
        ...,
        description="Which agent role should see this nudge on its next "
        "LLM call. 'both' fires for the next planner AND the next "
        "executor call.",
    )
    urgency: NudgeUrgency = Field(
        default="medium",
        description="Relative priority. 'high' sorts to the top of the injected block.",
    )
    message: str = Field(
        ...,
        description="The nudge text itself. 1–3 sentences, specific and "
        "actionable.  Injected verbatim into the target agent's next "
        "context with no header, label, or attribution.",
    )
    reason: str = Field(
        default="",
        description="Why the KM emitted this nudge. Logged for audit; not injected.",
    )
    created_at: float = Field(default_factory=time.time)


class KMAdvice(BaseModel):
    """Structured value the runner stores in the advise cache.

    Constructed by ``run_km`` when the unified output has a non-empty
    ``for_planner`` or ``for_executor`` block.  Read by the
    PRE_LLM_CALL injection hook.
    """

    for_planner: str = Field(
        default="",
        description="Markdown block (≤6 lines) for the planner's next "
        "LLM call. Scoped to the exact current step, not the whole plan.",
    )
    for_executor: str = Field(
        default="",
        description="Markdown block (≤6 lines) for the executor's next "
        "LLM call. Scoped to the exact current tool call, not the whole "
        "task.",
    )
    trajectory_hash: str = Field(
        default="",
        description="Hash of the trajectory window this advice was "
        "generated for. Used for debug / freshness inspection, not as a "
        "strict cache key.",
    )
    generated_at: float = Field(default_factory=time.time)
    active_items_version: int = Field(
        default=0,
        description="`active_items_version` at generation time. Used to "
        "detect stale advice after a run persists new content.",
    )


class KMOutput(BaseModel):
    """Terminal structured output of a unified ``run_km`` call.

    Every field is optional.  The most common outcome is
    ``nothing_to_do=True`` with every collection empty and every string
    empty — the KM looked at the window, confirmed there was nothing
    new worth persisting, nothing worth nudging, and nothing step-
    critical to inject, and exited cleanly.
    """

    # ── Write side ──
    files_written: list[str] = Field(
        default_factory=list,
        description="Relative paths under `.sukuna/km/` of newly created files.",
    )
    files_updated: list[str] = Field(
        default_factory=list,
        description="Relative paths of files updated in place.",
    )
    files_superseded: list[str] = Field(
        default_factory=list,
        description="Relative paths of files deleted or marked replaced.",
    )

    # ── Steering side ──
    nudges: list[KMNudge] = Field(
        default_factory=list,
        description="Nudges the KM emitted during this run. The runner forwards each one to ``push_nudge``.",
    )

    # ── Injection side ──
    for_planner: str = Field(
        default="",
        description="Trusted, pre-computed injection block for the "
        "planner's next LLM call. ≤6 lines. Bare bullets only. May be "
        "empty (and usually is).",
    )
    for_executor: str = Field(
        default="",
        description="Trusted, pre-computed injection block for the "
        "executor's next LLM call. ≤6 lines. Bare bullets only. May be "
        "empty (and usually is).",
    )

    # ── Status ──
    summary: str = Field(
        default="",
        description="One-line natural-language summary of what this run did. Logged; not injected.",
    )
    nothing_to_do: bool = Field(
        default=False,
        description="True if the KM looked at the window and decided no "
        "action was warranted. This is the expected common outcome on "
        "the majority of invocations.",
    )

    # Convenience
    def is_silent(self) -> bool:
        """True if the run produced no files, no nudges, no blocks."""
        return not (
            self.files_written
            or self.files_updated
            or self.files_superseded
            or self.nudges
            or self.for_planner
            or self.for_executor
        )

    def has_guidance(self) -> bool:
        return bool(self.for_planner or self.for_executor)

    def touched_files(self) -> bool:
        return bool(self.files_written or self.files_updated or self.files_superseded)
