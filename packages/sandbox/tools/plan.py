"""Plan management tool — create, update, and track structured execution plans."""

__version__ = "0.1.0"

import asyncio
import contextvars
import json
import logging
import os
import traceback
from datetime import UTC, datetime
from typing import Annotated, Literal

from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool

# ========================
# THIRD PARTY IMPORTS
# ========================
from pydantic import BaseModel

log = logging.getLogger("plan")

CURRENT_SCHEDULED_TASKS_LENGTH = os.getenv("CURRENT_SCHEDULED_TASKS_LENGTH")
MAX_ALLOWED_SCHEDULED_TASKS = os.getenv("MAX_ALLOWED_SCHEDULED_TASKS")


def get_tool_env():
    global CURRENT_SCHEDULED_TASKS_LENGTH, MAX_ALLOWED_SCHEDULED_TASKS
    CURRENT_SCHEDULED_TASKS_LENGTH = os.getenv("CURRENT_SCHEDULED_TASKS_LENGTH")
    MAX_ALLOWED_SCHEDULED_TASKS = os.getenv("MAX_ALLOWED_SCHEDULED_TASKS")
    return {
        "CURRENT_SCHEDULED_TASKS_LENGTH": CURRENT_SCHEDULED_TASKS_LENGTH,
        "MAX_ALLOWED_SCHEDULED_TASKS": MAX_ALLOWED_SCHEDULED_TASKS,
    }


# ========================
# PER-CONVERSATION PLAN STATE
# ========================
# Each conversation gets its own plan and history, keyed by conversation_id.
# The active conversation is tracked via a contextvars.ContextVar so that
# concurrent asyncio tasks (each run is a separate task) are isolated.

_active_conversation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_active_conversation_id", default=None
)

_plans: dict[str, "Plan | None"] = {}
_plan_histories: dict[str, list] = {}
_MAX_HISTORY_SIZE = 50


# ========================
# CAPABILITY → SKILL MAPPING
# ========================
# Each capability flag maps to a set of bundled skills whose SKILL.md
# metadata is injected into the LLM context when the flag is True.
CAPABILITY_SKILL_MAP: dict[str, list[str]] = {
    "web_development": ["frontend-dev", "fullstack-dev", "webdev"],
    "mobile_development": [
        "mobiledev",
        "react-native-dev",
    ],
    "documents": ["officecli-docx", "officecli-academic-paper", "exo-pdf"],
    "spreadsheets": ["officecli-xlsx", "officecli-financial-model", "officecli-data-dashboard"],
    "presentations": ["officecli-pptx", "officecli-pitch-deck", "morph-ppt"],
    "shader_graphics": ["shader-dev"],
    "complex_orchestration": ["prd", "ralph"],
}


# Models
class PhaseCapabilities(BaseModel):
    """Boolean flags that determine which skill metadata is injected into context.

    Each flag maps to a group of bundled skills (see CAPABILITY_SKILL_MAP).
    When a flag is True for the active phase, the corresponding skills'
    SKILL.md content is loaded into the LLM context window.
    """

    web_development: bool = False
    mobile_development: bool = False
    documents: bool = False
    spreadsheets: bool = False
    presentations: bool = False
    shader_graphics: bool = False
    complex_orchestration: bool = False

    def active_skills(self) -> list[str]:
        """Return the list of skill names that should be injected for this phase."""
        skills: list[str] = []
        for cap, skill_names in CAPABILITY_SKILL_MAP.items():
            if getattr(self, cap, False):
                skills.extend(skill_names)
        return skills


class Phase(BaseModel):
    """Represents a single phase in the plan"""

    id: int
    title: str
    capabilities: PhaseCapabilities = PhaseCapabilities()
    status: str = "pending"
    started_at: str | None = None
    completed_at: str | None = None


class Plan(BaseModel):
    """Represents the complete plan structure"""

    goal: str
    phases: list[Phase]
    current_phase_id: int
    created_at: str
    updated_at: str


# ========================
# PLAN-MAP STATUS GLYPHS
# ========================
#
# Status glyphs used in the plan map.  Kept terse on purpose so the
# full phase line stays readable without wrapping.  Consumed by the
# plan-context formatters in ``agent_server.engine.hooks``.
_PHASE_STATUS_GLYPH = {
    "completed": "✓ done",
    "in_progress": "→ in progress",
    "pending": "· pending",
}


# The injection markers and plan-context formatters
# (``_PLAN_CONTEXT_MARKER``, ``format_plan_markdown``,
# ``format_executor_plan_context``, ``format_message_discipline_markdown``)
# now live in ``agent_server.engine.hooks`` next to the hook factories
# that consume them.


# ========================
# LIFECYCLE & PERSISTENCE
# ========================


def set_plan_conversation(conversation_id: str) -> None:
    """Set the active conversation for the current asyncio task.

    Called at the start of each agent run in server.py.
    """
    _active_conversation_id.set(conversation_id)


def _cid() -> str | None:
    """Return the active conversation_id for the current async context."""
    return _active_conversation_id.get()


def _get_current_plan(cid: str | None = None) -> "Plan | None":
    """Get plan for a conversation (defaults to the active one)."""
    cid = cid or _cid()
    return _plans.get(cid) if cid else None


def _set_current_plan(plan: "Plan | None", cid: str | None = None) -> None:
    """Set plan for a conversation (defaults to the active one)."""
    cid = cid or _cid()
    if cid:
        _plans[cid] = plan
    else:
        log.warning("_set_current_plan: no conversation_id — plan discarded")


def _get_history(cid: str | None = None) -> list:
    """Get plan history for a conversation (defaults to the active one)."""
    cid = cid or _cid()
    if cid and cid not in _plan_histories:
        _plan_histories[cid] = []
    return _plan_histories.get(cid, []) if cid else []


# ========================
# FILE PERSISTENCE
# ========================


def _plan_file_path(cid: str) -> "pathlib.Path":
    """Return the filesystem path for a conversation's plan JSON file."""
    import pathlib

    workspace = (
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(pathlib.Path.home())
    )
    return pathlib.Path(workspace) / ".agent" / "plans" / f"{cid}.json"


def _save_plan_to_file(cid: str | None = None) -> None:
    """Persist the current plan to a local JSON file (atomic write)."""
    cid = cid or _cid()
    if not cid:
        return
    plan = _plans.get(cid)
    if plan is None:
        # Keep last known state on disk — do not delete the file.
        return
    try:
        path = _plan_file_path(cid)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = plan.model_dump()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.rename(path)
        log.info("Saved plan to file for cid=%s", cid[:8])
    except Exception:
        log.warning("Failed to save plan to file for cid=%s", cid[:8] if cid else None, exc_info=True)


def _load_plan_from_file(cid: str) -> "Plan | None":
    """Load a plan from the local JSON file, or return None."""
    try:
        path = _plan_file_path(cid)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        phases = []
        for p in data.get("phases", []):
            if isinstance(p, dict):
                caps_data = p.get("capabilities", {})
                caps = PhaseCapabilities(**caps_data) if isinstance(caps_data, dict) else PhaseCapabilities()
                phases.append(
                    Phase(
                        id=p.get("id", 0),
                        title=p.get("title", ""),
                        capabilities=caps,
                        status=p.get("status", "pending"),
                        started_at=p.get("started_at"),
                        completed_at=p.get("completed_at"),
                    )
                )
        if not phases:
            return None
        return Plan(
            goal=data.get("goal", ""),
            phases=phases,
            current_phase_id=int(data.get("current_phase_id", 1)),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )
    except Exception:
        log.warning("Failed to load plan from file for cid=%s", cid[:8] if cid else None, exc_info=True)
        return None


# ========================
# DB HELPERS
# ========================


def _ensure_conversation_exists(cid: str) -> bool:
    """Ensure a storage_conversation row exists before writing the plan FK.

    Returns True if the row exists (already or just created), False on failure.
    """
    try:
        from django.db import IntegrityError  # noqa: C0415
        from django.utils import timezone  # noqa: C0415

        from agent_server.models import DjangoAgentRun, DjangoConversation  # noqa: C0415

        if DjangoConversation.objects.filter(pk=cid).exists():
            return True

        agent_run = DjangoAgentRun.objects.filter(conversation_id=cid).first()
        if agent_run is None or agent_run.user_id is None:
            log.warning(
                "_ensure_conversation_exists: no agent run or user_id for cid=%s, skipping DB plan sync",
                cid[:8] if cid else None,
            )
            return False

        now = timezone.now()
        try:
            DjangoConversation.objects.create(
                id=cid,
                user_id=agent_run.user_id,
                title="New chat",
                date_created=now,
                date_updated=now,
            )
            log.info("_ensure_conversation_exists: created conversation row for cid=%s", cid[:8] if cid else None)
        except IntegrityError:
            # Row was created concurrently (e.g. by backend) — that's fine.
            log.debug("_ensure_conversation_exists: row already exists (race) for cid=%s", cid[:8] if cid else None)
        return True
    except Exception:
        log.warning("_ensure_conversation_exists: failed for cid=%s", cid[:8] if cid else None, exc_info=True)
        return False


def init_plan_state(conversation_id: str) -> None:
    """Load plan for a conversation at run start.

    Priority: local file (primary) → DB (fallback).
    Called from server.py when an agent run begins.
    """
    set_plan_conversation(conversation_id)
    if conversation_id not in _plans:
        _plans[conversation_id] = None
        _plan_histories[conversation_id] = []

    # Primary: load from local file (survives sandbox restarts).
    file_plan = _load_plan_from_file(conversation_id)
    if file_plan is not None:
        _plans[conversation_id] = file_plan
        log.info("Loaded plan from file for conversation %s", conversation_id)
        return

    # Fallback: load from DB.
    try:
        from agent_server.models import DjangoConversationPlan  # noqa: C0415

        db_plan = DjangoConversationPlan.objects.filter(conversation_id=conversation_id).first()
        if db_plan and db_plan.phases:
            phases = db_plan.phases if isinstance(db_plan.phases, list) else []
            phase_objects = []
            for p in phases:
                if isinstance(p, dict):
                    caps_data = p.get("capabilities", {})
                    caps = PhaseCapabilities(**caps_data) if isinstance(caps_data, dict) else PhaseCapabilities()
                    phase_objects.append(
                        Phase(
                            id=p.get("id", 0),
                            title=p.get("title", ""),
                            capabilities=caps,
                            status=p.get("status", "pending"),
                            started_at=p.get("started_at"),
                            completed_at=p.get("completed_at"),
                        )
                    )
            if phase_objects:
                _plans[conversation_id] = Plan(
                    goal=db_plan.goal or "",
                    phases=phase_objects,
                    current_phase_id=int(db_plan.current_phase_id) if db_plan.current_phase_id else 1,
                    created_at=db_plan.created_at.isoformat() if db_plan.created_at else datetime.now().isoformat(),
                    updated_at=db_plan.updated_at.isoformat() if db_plan.updated_at else datetime.now().isoformat(),
                )
                log.info("Loaded plan from DB for conversation %s", conversation_id)
    except Exception:
        log.debug("Could not load plan from DB for conversation %s", conversation_id, exc_info=True)


def cleanup_plan_state(conversation_id: str) -> None:
    """Remove in-memory plan state for a conversation on run end."""
    _plans.pop(conversation_id, None)
    _plan_histories.pop(conversation_id, None)


def _sync_plan_to_db(cid: str | None = None) -> None:
    """Persist the current plan state to file and database.

    File write is always attempted first (primary persistence layer).
    When called from the event loop thread, schedules a fire-and-forget
    async task for DB.  When called from a worker thread (no running event
    loop), falls back to synchronous Django ORM directly.
    """
    cid = cid or _cid()
    plan = _plans.get(cid) if cid else None
    if not cid:
        log.warning("_sync_plan_to_db: no cid, skipping sync")
        return
    log.info("_sync_plan_to_db: cid=%s plan=%s", cid[:8] if cid else None, plan is not None)

    # Always persist to local file first (fast, survives sandbox restarts).
    _save_plan_to_file(cid)

    def _persist_sync() -> None:
        """Synchronous DB write — safe to call from any thread."""
        try:
            import uuid as _uuid  # noqa: C0415

            from django.utils import timezone  # noqa: C0415

            from agent_server.models import DjangoConversationPlan  # noqa: C0415

            now = timezone.now()
            if plan is None:
                DjangoConversationPlan.objects.filter(conversation_id=cid).delete()
                return

            # Ensure parent conversation row exists (FK constraint).
            if not _ensure_conversation_exists(cid):
                log.warning(
                    "_persist_sync: skipping DB write, conversation row unavailable for cid=%s",
                    cid[:8] if cid else None,
                )
                return

            existing = DjangoConversationPlan.objects.filter(conversation_id=cid).first()
            phases_data = [p.model_dump() for p in plan.phases]
            if existing:
                existing.goal = plan.goal
                existing.phases = phases_data
                existing.current_phase_id = str(plan.current_phase_id)
                existing.updated_at = now
                existing.save(update_fields=["goal", "phases", "current_phase_id", "updated_at"])
            else:
                DjangoConversationPlan.objects.create(
                    id=_uuid.uuid4(),
                    conversation_id=cid,
                    goal=plan.goal,
                    phases=phases_data,
                    current_phase_id=str(plan.current_phase_id),
                    sandbox_id="",
                    created_at=now,
                    updated_at=now,
                )
            log.info("_persist_sync: wrote plan to DB for cid=%s", cid[:8] if cid else None)
        except Exception:
            log.warning("Plan DB sync failed for conversation %s", cid, exc_info=True)

    try:
        loop = asyncio.get_running_loop()

        async def _do_sync() -> None:
            from asgiref.sync import sync_to_async  # noqa: C0415

            await sync_to_async(_persist_sync)()

        loop.create_task(_do_sync(), name=f"plan-sync-{cid[:8] if cid else 'unknown'}")
    except RuntimeError:
        # No running event loop (e.g. called from asyncio.to_thread).
        # Fall back to synchronous ORM — we're already in a thread so
        # blocking is fine.
        log.info("_sync_plan_to_db: no event loop, using sync fallback for cid=%s", cid[:8] if cid else None)
        _persist_sync()


# ========================
# HELPER FUNCTIONS
# ========================


def _get_phase_by_id(phase_id: int) -> Phase | None:
    """Helper to find a phase by ID"""
    plan = _get_current_plan()
    if not plan:
        return None
    for phase in plan.phases:
        if phase.id == phase_id:
            return phase
    return None


def _validate_phase_sequence(current_id: int, next_id: int) -> tuple[bool, str]:
    """Validate that next_id is the sequential next phase after current_id"""
    plan = _get_current_plan()
    if not plan:
        return False, "No plan exists"

    phase_ids = [p.id for p in plan.phases]

    try:
        current_idx = phase_ids.index(current_id)
        next_idx = phase_ids.index(next_id)

        if next_idx == current_idx + 1:
            return True, ""
        else:
            expected = phase_ids[current_idx + 1] if current_idx + 1 < len(phase_ids) else "none"
            return False, f"Cannot skip phases. Next phase after '{current_id}' must be '{expected}'"
    except ValueError as e:
        return False, f"Invalid phase ID: {str(e)}"


def _add_to_history(action: str, data: dict):
    """Add an action to the plan history"""
    history_entry = {"timestamp": datetime.now().isoformat(), "action": action, "data": data}
    history = _get_history()
    history.append(history_entry)

    # Trim history if it exceeds max size
    if len(history) > _MAX_HISTORY_SIZE:
        cid = _cid()
        if cid:
            _plan_histories[cid] = history[-_MAX_HISTORY_SIZE:]


# ========================
# INTERNAL PLAN ACTIONS
# ========================


def _advance_plan(
    current_phase_id: int | None = None,
    next_phase_id: int | None = None,
) -> dict:
    """Advance from the current phase to the next sequential phase in the plan."""
    get_tool_env()
    try:
        plan = _get_current_plan()
        # Validate plan exists
        if not plan:
            return {
                "success": False,
                "message": "No plan exists. Please use update_plan to create a plan first.",
                "hint": "Create a plan first with action='update', providing goal, phases, and current_phase_id.",
            }

        # Validate current phase
        current_phase = _get_phase_by_id(current_phase_id)
        if not current_phase:
            available = [p.id for p in plan.phases]
            return {
                "success": False,
                "message": f"Current phase '{current_phase_id}' not found in plan.",
                "hint": f"Use one of the existing phase IDs: {available}. Use action='get' to view the full plan.",
                "metadata": {"available_phases": available},
            }

        # Validate next phase exists
        next_phase = _get_phase_by_id(next_phase_id)
        if not next_phase:
            available = [p.id for p in plan.phases]
            return {
                "success": False,
                "message": f"Next phase '{next_phase_id}' not found in plan.",
                "hint": f"Use one of the existing phase IDs: {available}. Use action='get' to view the full plan.",
                "metadata": {"available_phases": available},
            }

        # Validate sequence
        is_valid, error_msg = _validate_phase_sequence(current_phase_id, next_phase_id)
        if not is_valid:
            return {
                "success": False,
                "message": f"Invalid phase transition: {error_msg}",
                "hint": "Phases must be advanced sequentially. You cannot skip phases. Use action='get' to see the phase order.",
                "metadata": {"current_phase": current_phase_id, "next_phase": next_phase_id},
            }

        # Mark current phase as completed
        current_phase.status = "completed"
        current_phase.completed_at = datetime.now().isoformat()

        # Mark next phase as in progress
        next_phase.status = "in_progress"
        next_phase.started_at = datetime.now().isoformat()

        # Update plan
        plan.current_phase_id = next_phase_id
        plan.updated_at = datetime.now().isoformat()

        # Add to history
        _add_to_history("advance", {"from_phase": current_phase_id, "to_phase": next_phase_id})

        _sync_plan_to_db()

        return {
            "success": True,
            "message": f"Successfully advanced from phase '{current_phase_id}' to '{next_phase_id}'",
            "metadata": {
                "previous_phase": current_phase_id,
                "current_phase": next_phase_id,
                "remaining_phases": len([p for p in plan.phases if p.status == "pending"]),
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error advancing plan: {str(e)}",
            "hint": "An unexpected error occurred. Use action='get' to check the current plan state, then retry.",
            "metadata": {"error": str(e), "traceback": traceback.format_exc()},
        }


def _update_plan(
    goal: str | None = None,
    phases: list | None = None,
    current_phase_id: int | None = None,
) -> dict:
    """Create or revise the structured task plan with goal and phases."""
    get_tool_env()
    try:
        # Defensive: parse JSON string if LLM passed phases as a string
        if isinstance(phases, str):
            try:
                phases = json.loads(phases)
            except (json.JSONDecodeError, TypeError):
                pass

        # Validate phases is a list
        if not isinstance(phases, list):
            return {
                "success": False,
                "message": "Missing or invalid 'phases' parameter. Must be a list of phase dicts.",
                "metadata": {
                    "hint": "Provide phases as a list of dicts: phases=[{'id': 1, 'title': 'Design', 'capabilities': {'deep_research': true}}]. "
                    "Also provide goal and current_phase_id."
                },
            }

        # Normalize: if LLM passed plain strings instead of dicts, convert them
        normalized = []
        for idx, item in enumerate(phases):
            if isinstance(item, str):
                normalized.append({"id": idx + 1, "title": item, "capabilities": {}})
            elif isinstance(item, dict):
                normalized.append(item)
            else:
                normalized.append({"id": idx + 1, "title": str(item), "capabilities": {}})
        phases = normalized

        # Create Phase objects
        phase_objects = []
        for idx, phase_data in enumerate(phases):
            if isinstance(phase_data, dict):
                caps_data = phase_data.get("capabilities", {})
                capabilities = PhaseCapabilities(**caps_data) if isinstance(caps_data, dict) else PhaseCapabilities()
                phase_objects.append(
                    Phase(
                        id=phase_data.get("id", idx + 1),
                        title=phase_data.get("title", ""),
                        capabilities=capabilities,
                        status=phase_data.get("status", "pending"),
                        started_at=phase_data.get("started_at"),
                        completed_at=phase_data.get("completed_at"),
                    )
                )
            else:
                return {
                    "success": False,
                    "message": f"Invalid phase format at index {idx}",
                    "hint": "Each phase must be a dict with 'id' (int), 'title' (str), and optionally 'capabilities' (dict of bool flags).",
                }

        # Validate current_phase_id exists in phases
        phase_ids = [p.id for p in phase_objects]
        if current_phase_id not in phase_ids:
            return {
                "success": False,
                "message": f"current_phase_id '{current_phase_id}' not found in phases",
                "hint": f"current_phase_id must match one of the phase IDs: {phase_ids}.",
                "metadata": {"available_phases": phase_ids},
            }

        # Set the current phase as in_progress if it's pending
        for phase in phase_objects:
            if phase.id == current_phase_id and phase.status == "pending":
                phase.status = "in_progress"
                phase.started_at = datetime.now().isoformat()

        # Create or update the plan
        now = datetime.now().isoformat()
        existing_plan = _get_current_plan()
        is_new_plan = existing_plan is None

        new_plan = Plan(
            goal=goal,
            phases=phase_objects,
            current_phase_id=current_phase_id,
            created_at=existing_plan.created_at if existing_plan else now,
            updated_at=now,
        )
        _set_current_plan(new_plan)

        # Add to history
        _add_to_history(
            "update",
            {
                "goal": goal,
                "phases": [p.model_dump() for p in phase_objects],
                "current_phase_id": current_phase_id,
                "is_new_plan": is_new_plan,
            },
        )

        _sync_plan_to_db()

        action_verb = "Created" if is_new_plan else "Updated"

        return {
            "success": True,
            "message": f"{action_verb} plan successfully",
            "metadata": {
                "goal": goal,
                "total_phases": len(phase_objects),
                "current_phase": current_phase_id,
                "is_new_plan": is_new_plan,
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error updating plan: {str(e)}",
            "hint": "An unexpected error occurred during plan update. Verify your phases parameter is a list of dicts with 'id' (int), 'title' (str), and 'capabilities' (dict) keys.",
            "metadata": {"error": str(e), "traceback": traceback.format_exc()},
        }


def _get_plan_action() -> dict:
    """Return the current plan as structured data."""
    get_tool_env()
    try:
        plan = _get_current_plan()
        if not plan:
            return {
                "success": False,
                "message": "No plan exists. Please use update_plan to create a plan first.",
                "hint": "Create a plan first with action='update', providing goal, phases, and current_phase_id.",
            }

        return {
            "success": True,
            "message": plan.model_dump(),
            "metadata": {
                "total_phases": len(plan.phases),
                "current_phase": plan.current_phase_id,
                "completed_phases": len([p for p in plan.phases if p.status == "completed"]),
                "pending_phases": len([p for p in plan.phases if p.status == "pending"]),
            },
        }

    except Exception as e:
        return {
            "success": False,
            "message": f"Error getting plan: {str(e)}",
            "hint": "The plan state may be corrupted. Try creating a new plan with action='update'.",
            "metadata": {"error": str(e)},
        }


# ========================
# TOOLS
# ========================

_PLAN_ALIASES: dict[str, str] = {
    "create": "update",
    "new": "update",
    "init": "update",
    "initialize": "update",
    "setup": "update",
    "make": "update",
    "build": "update",
    "define": "update",
    "set": "update",
    "next": "advance",
    "progress": "advance",
    "step": "advance",
    "forward": "advance",
    "move": "advance",
    "proceed": "advance",
    "continue": "advance",
    "complete_phase": "advance",
    "finish": "advance",
    "bump": "advance",
    "view": "get",
    "show": "get",
    "display": "get",
    "retrieve": "get",
    "fetch": "get",
    "read": "get",
    "check": "get",
    "current": "get",
    "status": "get",
    "inspect": "get",
}

_SCHEDULE_ALIASES: dict[str, str] = {
    "recurring": "cron",
    "scheduled": "cron",
    "crontab": "cron",
    "timer": "interval",
    "periodic": "interval",
    "every": "interval",
    "repeat": "interval",
}


@tool(name="plan")
def plan_tool(
    action: Annotated[Literal["update", "advance", "get"], "The plan action to perform."],
    current_phase_id: Annotated[
        int, "ID of the current phase (auto-incrementing int starting from 1). Use 1 when creating a new plan."
    ] = 1,
    goal: Annotated[str | None, "The overall goal of the plan."] = None,
    next_phase_id: Annotated[int | None, "ID of the next phase to advance to."] = None,
    phases: Annotated[
        list | None,
        "List of phase dicts. Each dict has: "
        "'id' (int, auto-incrementing from 1), "
        "'title' (str, concise human-readable name), "
        "'capabilities' (dict of bool flags that determine which skill metadata "
        "is injected into context: web_development, mobile_development, documents, "
        "spreadsheets, presentations, shader_graphics, complex_orchestration).",
    ] = None,
) -> dict:
    """Create, update, and advance the structured task plan.

    <instructions>
    - This tool helps plan tasks and break down complex work into manageable phases.
    - Before execution, create a task plan using the `update` action.
    - MUST `update` the task plan when user makes new requests or changes requirements.
    - A task plan includes one goal and multiple phases to guide the task.
    - Phase count scales with task complexity: simple (2), typical (4-6), complex (10+).
    - Required capabilities only guide optimization; all tools remain available in every phase.
    - Each phase may require multiple iterations of thinking and tool use.
    - Phases should be high-level units of work, not implementation details.
    - Make delivering results to the user a separate phase, typically the final phase.
    - Set `current_phase_id` to one of the new phase IDs on plan `update`; no need to `advance` separately.
    - When confident a phase is complete, MUST advance using the `advance` action.
    - `next_phase_id` MUST be the next sequential ID after `current_phase_id`.
    - Skipping phases or going backward is NOT allowed, as it indicates the plan needs to be revised using the `update` action.
    - Relevant best practices and knowledge will be provided for each phase.
    - Phases MUST be completed in order, DO NOT skip phases; to revise the plan, use the `update` action.
    - Actively update the task plan when significant new information emerges.
    - DO NOT end the task early unless explicitly requested by the user.
    - When users request to edit, modify, or refine existing images, MUST use generate instead of perception.
    </instructions>

    <recommended_usage>
    - Use `get` to retrieve the current plan with all phases and their statuses.
    - Use `update` to create the initial task plan at the start of a new task.
    - Use `update` to update the task plan when user makes a new request.
    - Use `update` to revise the task plan when new information is discovered.
    - Use `update` when the current task plan is inefficient or fails repeatedly.
    - Use `advance` when the current phase is complete and the next phase is ready to start.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _PLAN_ALIASES)

    try:
        if action == "get":
            return alias_hint(_get_plan_action(), _alias, action)
        elif action == "update":
            missing = []
            if not goal:
                missing.append("goal")
            if not phases:
                missing.append("phases")
            if missing:
                return {
                    "success": False,
                    "message": f"Missing required parameters for update: {', '.join(missing)}.",
                    "metadata": {
                        "hint": "Provide goal='objective', phases=[{'id': 1, 'title': 'Step 1', 'capabilities': {'deep_research': true}}], "
                        "current_phase_id=1."
                    },
                }
            return alias_hint(_update_plan(goal=goal, phases=phases, current_phase_id=current_phase_id), _alias, action)
        elif action == "advance":
            if not current_phase_id or not next_phase_id:
                return {
                    "success": False,
                    "message": "Missing required parameters for advance action.",
                    "metadata": {
                        "hint": "Provide both current_phase_id and next_phase_id. Use action='get' to see current plan phases."
                    },
                }
            return alias_hint(
                _advance_plan(current_phase_id=current_phase_id, next_phase_id=next_phase_id), _alias, action
            )
        else:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
                "metadata": {"hint": "Use one of: get, update, advance."},
            }
    except Exception as e:
        log.exception("plan_tool error: %s", e)
        return {
            "success": False,
            "message": f"Plan operation failed: {e}",
            "metadata": {"hint": "An unexpected error occurred. Try action='get' to check current state."},
        }


@tool(name="schedule")
def schedule_tool(
    type: Annotated[Literal["cron", "interval"], "Type of schedule for the task. Supported values: cron, interval."],
    repeat: Annotated[bool, "Whether to repeat the task after execution. If false, the task runs only once."],
    name: Annotated[str, "Concise human-readable name of the task for easy identification."],
    prompt: Annotated[
        str,
        "Natural language description of the task to perform at execution time. "
        "Phrase it as if executing immediately, without repeating scheduling details.",
    ],
    cron: Annotated[
        str | None,
        "Crontab schedule expression defining when to run the task. Required for cron type. "
        "Format: 'minute hour day_of_month month day_of_week' (5-field, UTC timezone). "
        "Examples: '0 8 * * *' = daily at 8:00 AM UTC, '0 */6 * * *' = every 6 hours, "
        "'0 9 * * 1' = every Monday at 9:00 AM UTC, '30 14 1 * *' = 1st of each month at 2:30 PM UTC",
    ] = None,
    expire: Annotated[
        str | None,
        "Optional datetime string (yyyy-MM-dd HH:mm:ss) specifying when the task should expire. "
        "If no expiration time is required, do not set this field.",
    ] = None,
    interval: Annotated[int | None, "Time interval in seconds between executions. Required for interval type."] = None,
    playbook: Annotated[
        str | None,
        "Summary of process and best practices learned from the current task, "
        "to ensure repeatability and consistency when executing the scheduled task in the future. "
        "Optional and only used when the scheduled task is exactly the same as the current task.",
    ] = None,
):
    """Schedule a task to run at a specific time or interval.

    <instructions>
    - This tool is primarily for scheduling task execution, not for setting reminders or alarms.
    - For reminders or alarms, prioritize calendar/reminder tools or MCP servers if available.
    - Only one scheduled task can exist at a time; the first call creates it, and subsequent calls modify the existing task.
    - Execution of `cron` tasks is based on UTC timezone.
    - Always prefer a single cron expression over multiple separate schedules when possible.
    - The first run of `interval` tasks is relative to the current time.
    - Minimum interval for recurring tasks is 5 minutes (300 seconds); this restriction does not apply to one-time tasks.
    - Use `cron` with `repeat` set to true for recurring tasks based on a cron schedule.
    - Use `cron` with `repeat` set to false for one-time execution at a specific time.
    - Use `interval` with `repeat` set to false for delayed one-time execution.
    - Use `interval` with `repeat` set to true for periodic tasks at fixed intervals.
    - The `prompt` field describes what to do at execution time, so DO NOT restate scheduling details.
    - Users can manage scheduled tasks from their settings page.
    </instructions>

    <recommended_usage>
    - Use this tool when the user requests a task to be scheduled for future execution.
    - Use this tool when the user requests to repeat the current task at regular intervals.
    - Use this tool when the user wants to modify the previously created task.
    </recommended_usage>
    """
    type, _alias = resolve_alias(type, _SCHEDULE_ALIASES)
    get_tool_env()

    # ── Validate inputs ──────────────────────────────────────────────────
    if not prompt or not str(prompt).strip():
        return error_result(
            "Missing required parameter: prompt.",
            hint="Provide a natural language description of the task to perform at execution time.",
        )

    if type == "cron":
        if not cron or not str(cron).strip():
            return error_result(
                "Missing required parameter: cron.",
                hint="Provide a 5-field cron expression in UTC, e.g. cron='0 8 * * *' for daily at 8am UTC.",
            )
        cron_parts = cron.strip().split()
        if len(cron_parts) != 5:
            return error_result(
                f"Invalid cron format: expected 5 fields, got {len(cron_parts)}.",
                hint="Use 5-field format: minute(0-59) hour(0-23) day-of-month(1-31) month(1-12) day-of-week(0-6).",
            )
    elif type == "interval":
        if interval is None or interval <= 0:
            return error_result(
                "Missing or invalid parameter: interval.",
                hint="Provide a positive number of seconds for the interval.",
            )
        if repeat and interval < 300:
            return error_result(
                "Interval too short for recurring tasks.",
                hint="Minimum interval for recurring tasks is 300 seconds (5 minutes). "
                "Set repeat=false for a one-time delayed execution with shorter intervals.",
            )

    # ── Check scheduling limits ──────────────────────────────────────────
    try:
        current = int(CURRENT_SCHEDULED_TASKS_LENGTH or 0)
        max_allowed = int(MAX_ALLOWED_SCHEDULED_TASKS or 10)
    except (TypeError, ValueError):
        current, max_allowed = 0, 10

    if current >= max_allowed:
        return error_result(
            "Task scheduling failed",
            error="User has exceeded the maximum number of scheduled tasks",
            hint="Delete an existing scheduled task from settings before creating a new one, or upgrade your plan.",
        )

    # ── Create the schedule in the database ──────────────────────────────
    try:
        import json as _json
        import uuid as _uuid
        from datetime import datetime as _dt

        from django.utils import timezone as _tz

        from agent_server.models import (
            DjangoAgentRun,
            DjangoCeleryCrontabSchedule,
            DjangoCeleryIntervalSchedule,
            DjangoCeleryPeriodicTask,
            DjangoScheduledTask,
        )

        # Resolve user_id from the current conversation
        cid = _cid()
        if not cid:
            return error_result("No active conversation", hint="Schedule tool requires an active agent run context.")

        agent_run = DjangoAgentRun.objects.filter(conversation_id=cid).first()
        if not agent_run or not agent_run.user_id:
            return error_result("Cannot determine user", hint="No agent run found for this conversation.")

        user_id = agent_run.user_id
        task_id = _uuid.uuid4()
        now = _tz.now()

        # Parse expiration datetime if provided
        expires_at = None
        if expire:
            try:
                expires_at = _dt.fromisoformat(expire.strip())
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
            except ValueError:
                return error_result(
                    "Invalid expire format.",
                    hint="Use ISO 8601 datetime format, e.g. '2025-12-31 23:59:59'.",
                )

        # Create Celery Beat schedule entry
        periodic_kwargs = {
            "name": f"scheduled_task_{task_id}",
            "task": "apps.agents.tasks.execute_scheduled_task",
            "args": _json.dumps([str(task_id)]),
            "enabled": True,
            "one_off": not repeat,
        }

        if expires_at:
            periodic_kwargs["expires"] = expires_at

        if type == "interval":
            schedule_obj, _ = DjangoCeleryIntervalSchedule.objects.get_or_create(
                every=interval,
                period="seconds",
            )
            periodic_kwargs["interval"] = schedule_obj
        else:
            parts = cron.strip().split()
            minute, hour, day_of_month, month_of_year, day_of_week = parts
            schedule_obj, _ = DjangoCeleryCrontabSchedule.objects.get_or_create(
                minute=minute,
                hour=hour,
                day_of_week=day_of_week,
                day_of_month=day_of_month,
                month_of_year=month_of_year,
            )
            periodic_kwargs["crontab"] = schedule_obj

        periodic_task = DjangoCeleryPeriodicTask.objects.create(**periodic_kwargs)

        # Create the scheduled task record
        DjangoScheduledTask.objects.create(
            id=task_id,
            prompt=prompt.strip(),
            name=name.strip() if name else "",
            user_id=user_id,
            schedule_type=type,
            crontab=cron.strip() if cron else "",
            interval_seconds=interval if type == "interval" else None,
            is_recurring=repeat,
            is_paused=False,
            expires_at=expires_at,
            playbook=playbook.strip() if playbook else "",
            celery_task=periodic_task,
            created_at=now,
            updated_at=now,
        )

        # Build human-readable schedule description
        if type == "interval":
            if interval >= 3600:
                desc = f"every {interval // 3600} hour(s)"
            elif interval >= 60:
                desc = f"every {interval // 60} minute(s)"
            else:
                desc = f"every {interval} second(s)"
        else:
            desc = f"cron: {cron.strip()}"

        recurrence = "recurring" if repeat else "one-time"
        expire_note = f", expires {expire}" if expire else ""

        return alias_hint(
            success_result(
                f"Task '{name or prompt[:50]}' has been successfully scheduled ({recurrence}, {desc}{expire_note}). "
                f"User can manage scheduled tasks from their settings.",
                task_id=str(task_id),
                schedule=desc,
            ),
            _alias,
            type,
            param_name="type",
        )

    except Exception as e:
        log.error("schedule_tool: failed to create scheduled task: %s", e, exc_info=True)
        return error_result(
            "Failed to create scheduled task",
            error=str(e),
            hint="An internal error occurred while scheduling. Try again or contact support.",
        )


def make_plan_tool(conversation_id: str):
    """Create a plan tool bound to a specific conversation_id.

    Eliminates dependency on ContextVar propagation through the async
    execution chain (TaskGroup → asyncio.to_thread).  The conversation_id
    is captured in the closure and force-set at the start of every
    invocation so all downstream helpers see the correct cid.

    The wrapper is async so exo calls ``await fn()`` directly on the
    event loop thread instead of ``asyncio.to_thread(fn)``.  This is
    critical because ``_sync_plan_to_db()`` needs a running event loop
    to schedule its fire-and-forget DB write task.
    """

    @tool(name="plan")
    async def _bound_plan_tool(
        action: Annotated[Literal["update", "advance", "get"], "The plan action to perform."],
        current_phase_id: Annotated[
            int, "ID of the current phase (auto-incrementing int starting from 1). Use 1 when creating a new plan."
        ] = 1,
        goal: Annotated[str | None, "The overall goal of the plan."] = None,
        next_phase_id: Annotated[int | None, "ID of the next phase to advance to."] = None,
        phases: Annotated[
            list | None,
            "List of phase dicts. Each dict has: "
            "'id' (int, auto-incrementing from 1), "
            "'title' (str, concise human-readable name), "
            "'capabilities' (dict of bool flags that determine which skill metadata "
            "is injected into context: web_development, mobile_development, documents, "
            "spreadsheets, presentations, shader_graphics, complex_orchestration).",
        ] = None,
    ) -> dict:
        """Create, view, and advance through a structured task plan.

        <instructions>
        - This tool helps plan tasks and break down complex work into manageable phases.
        - Before execution, create a task plan using the `update` action.
        - MUST `update` the task plan when user makes new requests or changes requirements.
        - A task plan includes one goal and multiple phases to guide the task.
        - Phase count scales with task complexity: simple (2), typical (4-6), complex (10+).
        - Required capabilities only guide optimization; all tools remain available in every phase.
        - Each phase may require multiple iterations of thinking and tool use.
        - Phases should be high-level units of work, not implementation details.
        - Make delivering results to the user a separate phase, typically the final phase.
        - Set `current_phase_id` to one of the new phase IDs on plan `update`; no need to `advance` separately.
        - When confident a phase is complete, MUST advance using the `advance` action.
        - `next_phase_id` MUST be the next sequential ID after `current_phase_id`.
        - Skipping phases or going backward is NOT allowed, as it indicates the plan needs to be revised using the `update` action.
        - Relevant best practices and knowledge will be provided for each phase.
        - Phases MUST be completed in order, DO NOT skip phases; to revise the plan, use the `update` action.
        - Actively update the task plan when significant new information emerges.
        - DO NOT end the task early unless explicitly requested by the user.
        - When users request to edit, modify, or refine existing images, MUST use generate instead of perception.
        </instructions>

        <recommended_usage>
        - Use `get` to retrieve the current plan with all phases and their statuses.
        - Use `update` to create the initial task plan at the start of a new task.
        - Use `update` to update the task plan when user makes a new request.
        - Use `update` to revise the task plan when new information is discovered.
        - Use `update` when the current task plan is inefficient or fails repeatedly.
        - Use `advance` when the current phase is complete and the next phase is ready to start.
        </recommended_usage>

        """
        # Force-set the ContextVar so all internal helpers see the right cid,
        # regardless of how this thread/task was spawned.
        _active_conversation_id.set(conversation_id)
        action, _alias = resolve_alias(action, _PLAN_ALIASES)
        result = plan_tool._fn(
            action=action,
            current_phase_id=current_phase_id,
            goal=goal,
            next_phase_id=next_phase_id,
            phases=phases,
        )
        return alias_hint(result, _alias, action) if isinstance(result, dict) else result

    return _bound_plan_tool


def make_schedule_tool(conversation_id: str):
    """Create a schedule tool bound to a specific conversation_id.

    Same pattern as ``make_plan_tool`` — captures conversation_id in a closure
    so the schedule tool can resolve user_id from the current agent run.
    """

    @tool(name="schedule")
    async def _bound_schedule_tool(
        type: Annotated[
            Literal["cron", "interval"], "Type of schedule for the task. Supported values: cron, interval."
        ],
        repeat: Annotated[bool, "Whether to repeat the task after execution. If false, the task runs only once."],
        name: Annotated[str, "Concise human-readable name of the task for easy identification."],
        prompt: Annotated[
            str,
            "Natural language description of the task to perform at execution time. Phrase it as if executing immediately, without repeating scheduling details.",
        ],
        cron: Annotated[
            str | None,
            "Crontab schedule expression defining when to run the task. Required for cron type. Format: 'minute hour day_of_month month day_of_week' (5-field, UTC timezone). Examples: '0 8 * * *' = daily at 8:00 AM UTC, '0 */6 * * *' = every 6 hours, '0 9 * * 1' = every Monday at 9:00 AM UTC",
        ] = None,
        expire: Annotated[
            str | None,
            "Optional datetime string (yyyy-MM-dd HH:mm:ss) specifying when the task should expire. If no expiration time is required, do not set this field.",
        ] = None,
        interval: Annotated[
            int | None, "Time interval in seconds between executions. Required for interval type."
        ] = None,
        playbook: Annotated[
            str | None,
            "Summary of process and best practices learned from the current task, to ensure repeatability and consistency when executing the scheduled task in the future.",
        ] = None,
    ) -> dict:
        """Schedule a task to run at a specific time or interval.

        <instructions>
        - This tool is primarily for scheduling task execution, not for setting reminders or alarms.
        - For reminders or alarms, prioritize calendar/reminder tools or MCP servers if available.
        - Only one scheduled task can exist at a time; the first call creates it, and subsequent calls modify the existing task.
        - Execution of `cron` tasks is based on UTC timezone.
        - Always prefer a single cron expression over multiple separate schedules when possible.
        - The first run of `interval` tasks is relative to the current time.
        - Minimum interval for recurring tasks is 5 minutes (300 seconds); this restriction does not apply to one-time tasks.
        - Use `cron` with `repeat` set to true for recurring tasks based on a cron schedule.
        - Use `cron` with `repeat` set to false for one-time execution at a specific time.
        - Use `interval` with `repeat` set to false for delayed one-time execution.
        - Use `interval` with `repeat` set to true for periodic tasks at fixed intervals.
        - The `prompt` field describes what to do at execution time, so DO NOT restate scheduling details.
        - Users can manage scheduled tasks from their settings page.
        </instructions>

        <recommended_usage>
        - Use this tool when the user requests a task to be scheduled for future execution.
        - Use this tool when the user requests to repeat the current task at regular intervals.
        - Use this tool when the user wants to modify the previously created task.
        </recommended_usage>
        """
        _active_conversation_id.set(conversation_id)
        type, _alias = resolve_alias(type, _SCHEDULE_ALIASES)
        result = schedule_tool._fn(
            type=type,
            repeat=repeat,
            name=name,
            prompt=prompt,
            cron=cron,
            expire=expire,
            interval=interval,
            playbook=playbook,
        )
        return alias_hint(result, _alias, type, param_name="type") if isinstance(result, dict) else result

    return _bound_schedule_tool


PLAN_TOOLS = [plan_tool, schedule_tool]
