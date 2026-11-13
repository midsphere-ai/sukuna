"""Knowledge Manager injection helpers.

Pure helpers the KM hook factories consume.  After the hook
centralisation, the factories (``make_vital_info_hook``,
``make_km_prefetch_hook``) live in ``agent_server.engine.hooks``; this
module now just exposes:

1. ``detect_role``     — classify an agent as ``planner`` /
                         ``executor`` / ``other`` from its name.
2. ``format_injection`` — pure formatter.  Composes the bare-bullets
                          ephemeral block (no envelope, no headers,
                          no attribution) that the injection hook
                          writes.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from .models import KMAdvice, KMNudge

log = logging.getLogger("knowledge_manager.advise")


Role = Literal["planner", "executor"]


# ─────────────────────────────────────────────────────────────────────────
# Role detection
# ─────────────────────────────────────────────────────────────────────────


def detect_role(agent: Any) -> Literal["planner", "executor", "other"]:
    """Classify the calling agent as ``planner`` / ``executor`` / ``other``.

    Executors are named ``executor_<uuid>`` and ralph workers are
    named ``ralph-worker-<iteration>``.  Both classify as ``executor``
    because they receive identical treatment from the KM (same cache
    slot, same nudge target, same worker-scope KM runs).

    The KM itself is named ``knowledge_manager`` and maps to ``other``
    so its own POST_LLM_CALL firings cannot recursively schedule
    more KM runs.
    """
    name = getattr(agent, "name", "") or ""
    if name == "planner":
        return "planner"
    if name.startswith("executor") or name.startswith("ralph-worker"):
        return "executor"
    return "other"


# ─────────────────────────────────────────────────────────────────────────
# Injection formatting
# ─────────────────────────────────────────────────────────────────────────
#
# The planner and executor do NOT know the Knowledge Manager exists.
# The output of this function must be indistinguishable from notes the
# target agent might have written to itself.  That means:
#   - no ``<knowledge-manager>`` / ``<vital-information>`` envelope
#   - no ``## Steering`` / ``## Guidance`` section headers
#   - no "KM says" / "according to the KM" attribution
#   - no comment markers that hint at a separate subsystem
#
# What we emit: bare markdown bullets and nothing else.  Nudges are
# prepended (they are time-sensitive) and mixed into the same flat
# bullet list as the advice block so the reader cannot tell which came
# from where.


_URGENCY_RANK = {"high": 0, "medium": 1, "low": 2}


def format_injection(
    *,
    role: Role,
    advice: KMAdvice | None,
    nudges: list[KMNudge],
) -> str:
    """Compose the ephemeral injection block for a given role.

    Returns an empty string when there is nothing to inject.  Nudges
    are ordered high → medium → low and appear above the advice
    bullets.  Neither the surrounding agent nor the returned text
    mentions the Knowledge Manager.
    """
    advice_block = ""
    if advice is not None:
        raw = advice.for_planner if role == "planner" else advice.for_executor
        advice_block = (raw or "").strip()

    if not advice_block and not nudges:
        return ""

    lines: list[str] = []

    # Nudges as bare bullets. No prefix markers, no titles — just the
    # message text itself so it reads like a note the agent left for
    # itself.
    for nudge in sorted(nudges, key=lambda n: _URGENCY_RANK.get(n.urgency, 1)):
        msg = nudge.message.strip()
        if not msg:
            continue
        lines.append(msg if msg.startswith("- ") else f"- {msg}")

    # Advice block is already ≤6 lines of bullet markdown (enforced by
    # the KM prompt).  Append it verbatim.
    if advice_block:
        lines.append(advice_block)

    return "\n".join(lines)


# The KM hook factories that wrap ``format_injection`` and schedule
# background ``run_km`` invocations (``make_vital_info_hook``,
# ``make_km_prefetch_hook``) live in ``agent_server.engine.hooks``
# alongside every other agent hook.
