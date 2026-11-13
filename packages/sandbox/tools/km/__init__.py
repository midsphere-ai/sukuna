"""Knowledge Manager tools — constrained file access for the
``.sukuna/km/`` storage area.

These tools are **not** registered with the general tool registry; they are
passed directly to the knowledge manager agent by ``agent_server.engine.knowledge``
so they never leak to the planner or executor.  Every operation is scoped
by the ``_km_conversation_id`` ContextVar which the knowledge manager runner sets
before invoking the agent.
"""

from .ops import (
    KM_TOOLS,
    clear_km_conversation,
    km_delete,
    km_list,
    km_nudge,
    km_read,
    km_write,
    set_km_conversation,
)

__all__ = [
    "KM_TOOLS",
    "km_read",
    "km_write",
    "km_list",
    "km_delete",
    "km_nudge",
    "set_km_conversation",
    "clear_km_conversation",
]
