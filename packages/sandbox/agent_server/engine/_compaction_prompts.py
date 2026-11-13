"""Shared LLM-facing descriptions for context compaction fields.

PTC (Programmatic Tool Calling) calls carry a ``code`` field that can
grow to many KB.  When a stale PTC call is compacted, ``code`` is
dropped and replaced with the ``_compact_intent`` one-liner so the
agent still remembers what it accomplished.
"""

from __future__ import annotations

# Added to the outer ``__exo_ptc__`` schema via ``Agent.ptc_extra_args``.
# When a stale PTC call is compacted the ``code`` field is dropped
# entirely and replaced with the intent string so the agent still
# remembers what it accomplished.
PTC_EXTRA_COMPACTION_ARGS: dict[str, str] = {
    "_compact_intent": (
        "A one-sentence description of what this code block accomplishes. "
        "When this tool call ages out of recent history, the full `code` "
        "will be dropped and replaced with this intent string. Write it "
        "as a note to your future self: 'Fetched Q3 expenses and filtered "
        "for travel overages.' or 'Searched and deduplicated web results "
        "for topic X.' If you omit this, the verbose code will stay in "
        "context and eat tokens unnecessarily."
    ),
}
