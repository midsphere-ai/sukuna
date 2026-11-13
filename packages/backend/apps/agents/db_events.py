"""
Read persisted agent events directly from the shared PostgreSQL database.

The sandbox agent server writes every SSE event to the `agent_events`
table.  Django shares this database, so we can read events directly without
needing the sandbox to be online.  This is used for shared conversation
replay and as the primary path for authenticated event replay.
"""

import logging
from datetime import datetime
from typing import Optional

from asgiref.sync import sync_to_async
from django.db import OperationalError, ProgrammingError
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.storage.models import AgentRun, AgentServerEvent

logger = logging.getLogger(__name__)


def _consolidate_text_events(events: list[dict]) -> list[dict]:
    """Merge consecutive ``text`` events (same run_id) into single events.

    During live streaming every token is persisted as a separate row.  For
    replay / pagination this is wasteful — 2 000 text rows produce just one
    visible message.  Consolidating them here means ``limit=500`` returns
    ~500 *logical* events instead of ~496 text deltas.

    Non-text events (tool_call, step, status, …) are never merged and act
    as natural flush boundaries, preserving message structure.
    """
    if not events:
        return events

    consolidated: list[dict] = []
    pending_text = ""
    pending_evt: dict | None = None

    def _flush() -> None:
        nonlocal pending_text, pending_evt
        if pending_evt is None:
            return
        # Build a single consolidated text event, keeping the *first*
        # event's sequence / created_at so cursors remain stable.
        flushed = {
            **pending_evt,
            "data": {
                **pending_evt["data"],
                "text": pending_text,
                "content": pending_text,
            },
        }
        consolidated.append(flushed)
        pending_text = ""
        pending_evt = None

    for evt in events:
        if evt.get("event_type") == "text":
            data = evt.get("data") or {}
            chunk = data.get("content") or data.get("text") or ""
            if pending_evt is not None and evt.get("run_id") == pending_evt.get(
                "run_id"
            ):
                pending_text += chunk
            else:
                _flush()
                pending_text = chunk
                pending_evt = evt
        else:
            _flush()
            consolidated.append(evt)

    _flush()
    return consolidated


async def get_events_for_conversation(
    conversation_id: str,
    before_sequence: Optional[int] = None,
    before_created_at: Optional[str] = None,
    before_run_id: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """
    Return persisted events for all runs belonging to *conversation_id*.

    Supports cursor-based pagination:
    - ``before_sequence``: only return events with sequence < this value
    - ``limit``: max number of events to return (clamped 1–2000)

    Returns the *last* ``limit`` events (most recent) from the filtered set,
    so clients get the newest events first and scroll up to load older ones.

    Response shape::

        {
            "events": [...],
            "status": "<latest run status>",
            "has_more": bool,
            "oldest_sequence": int | None,
            "newest_sequence": int | None,
            "total_count": int,
            "next_cursor": dict | None,
        }
    """
    limit = max(1, min(limit, 50000))

    try:
        # 1. Collect run_ids for this conversation.
        # Split into two queries: a lightweight one for run_ids/status,
        # and a heavier one for task/metadata only when needed for user_events.
        run_rows = await sync_to_async(list)(
            AgentRun.objects.filter(conversation_id=conversation_id)
            .order_by("created_at")
            .values_list("run_id", "status", "id", "created_at")
        )

        if not run_rows:
            return {
                "events": [],
                "status": "unknown",
                "has_more": False,
                "oldest_sequence": None,
                "newest_sequence": None,
                "total_count": 0,
                "next_cursor": None,
            }

        run_ids = [r[0] for r in run_rows if r[0]]
        latest_status = run_rows[-1][1]  # status of most recent run

        # 3. Query agent_events for those run_ids (only runs that have a run_id)
        qs = AgentServerEvent.objects.filter(run_id__in=run_ids).order_by(
            "created_at", "run_id", "sequence", "id"
        )

        cursor_dt: datetime | None = None
        if before_created_at:
            cursor_dt = parse_datetime(before_created_at)
            if cursor_dt is not None and timezone.is_naive(cursor_dt):
                cursor_dt = timezone.make_aware(cursor_dt)

        # New composite cursor path.
        if cursor_dt is not None and before_run_id and before_sequence is not None:
            qs = qs.filter(
                Q(created_at__lt=cursor_dt)
                | Q(created_at=cursor_dt, run_id__lt=before_run_id)
                | Q(
                    created_at=cursor_dt,
                    run_id=before_run_id,
                    sequence__lt=before_sequence,
                )
            )
        # Backward-compatible legacy cursor path.
        elif before_sequence is not None:
            qs = qs.filter(sequence__lt=before_sequence)

        # Two-step query: first sort lightweight rows (no `data` column) to
        # find the IDs we need, then fetch full rows by ID.  This avoids
        # PostgreSQL decompressing huge TOAST/JSONB `data` blobs for thousands
        # of events just to sort and discard most of them.
        id_rows = await sync_to_async(list)(
            qs.values_list("id", flat=True).reverse()[: limit + 1]
        )

        if len(id_rows) > limit:
            has_more = True
            id_rows = id_rows[:limit]
        else:
            has_more = False

        # Fetch full rows only for the IDs we actually need, in correct order.
        if id_rows:
            rows = await sync_to_async(list)(
                AgentServerEvent.objects.filter(id__in=id_rows)
                .order_by("created_at", "run_id", "sequence", "id")
                .values("id", "run_id", "sequence", "event_type", "data", "created_at")
            )
        else:
            rows = []
        total_count = len(rows)

        events = []
        for row in rows:
            event = {
                "event": row["event_type"],
                "event_type": row["event_type"],
                "data": row["data"],
                "run_id": row["run_id"],
                "sequence": row["sequence"],
            }
            if row["created_at"]:
                event["created_at"] = row["created_at"].isoformat()
            events.append(event)

        # Consolidate consecutive text events into single events so that
        # a page of 500 raw events produces ~500 logical events instead
        # of ~496 text deltas that render as 1 message.
        events = _consolidate_text_events(events)

        # 2. Build synthetic user_message events and interleave them.
        # Only fetch task/metadata for runs that actually need a user_message
        # on this page (runs whose first event seq==0 appears, plus pending runs).
        # This avoids loading large task/metadata for ALL runs on every page.
        page_run_ids_with_seq0: set = set()
        seen_runs: set = set()
        for evt in events:
            rid = evt.get("run_id")
            if rid and rid not in seen_runs:
                seen_runs.add(rid)
                if evt.get("sequence", -1) == 0:
                    page_run_ids_with_seq0.add(rid)

        # Build run_id → (agent_run_id, created_at) map for pending runs
        run_id_map = {r[0]: (r[2], r[3]) for r in run_rows}  # run_id → (id, created_at)
        pending_run_rows = [r for r in run_rows if not r[0]]  # runs without run_id

        # Determine which AgentRun PKs need task/metadata loaded
        need_task_pks = set()
        for rid in page_run_ids_with_seq0:
            info = run_id_map.get(rid)
            if info:
                need_task_pks.add(info[0])  # agent_run pk
        for r in pending_run_rows:
            need_task_pks.add(r[2])
        if not has_more:
            # On the oldest page, include historical runs not seen on this page
            for r in run_rows:
                if r[0] and r[0] not in seen_runs:
                    need_task_pks.add(r[2])

        user_events = []
        if need_task_pks:
            task_rows = await sync_to_async(list)(
                AgentRun.objects.filter(id__in=need_task_pks)
                .order_by("created_at")
                .values_list("run_id", "id", "task", "metadata", "created_at")
            )
            for run_id_val, agent_run_id, task, metadata, created_at in task_rows:
                if task:
                    evt_run_id = run_id_val or f"pending-{agent_run_id}"
                    evt = {
                        "event": "user_message",
                        "event_type": "user_message",
                        "data": {
                            "type": "user_message",
                            "text": task,
                            "files": metadata.get("files", []) if metadata else [],
                        },
                        "run_id": evt_run_id,
                        "sequence": -1,
                    }
                    if created_at:
                        evt["created_at"] = created_at.isoformat()
                    user_events.append(evt)

        if user_events:
            user_by_run = {ue["run_id"]: ue for ue in user_events}
            interleaved: list = []
            for evt in events:
                rid = evt.get("run_id")
                if rid in page_run_ids_with_seq0:
                    ue = user_by_run.pop(rid, None)
                    if ue:
                        interleaved.append(ue)
                    page_run_ids_with_seq0.discard(rid)
                interleaved.append(evt)
            # Remaining user_events: pending runs (end) and historical unseen (start)
            remaining = list(user_by_run.values())
            pending = [ue for ue in remaining if ue["run_id"].startswith("pending-")]
            historical = [
                ue for ue in remaining if not ue["run_id"].startswith("pending-")
            ]
            if not has_more:
                for ue in historical:
                    interleaved.insert(0, ue)
            for ue in pending:
                interleaved.append(ue)
            events = interleaved

        next_cursor = None
        if has_more and rows:
            oldest_row = rows[0]
            if oldest_row["created_at"] is not None:
                next_cursor = {
                    "before_created_at": oldest_row["created_at"].isoformat(),
                    "before_run_id": oldest_row["run_id"],
                    "before_sequence": oldest_row["sequence"],
                }

        return {
            "events": events,
            "status": latest_status,
            "has_more": has_more,
            "oldest_sequence": events[0]["sequence"] if events else None,
            "newest_sequence": events[-1]["sequence"] if events else None,
            "total_count": total_count,
            "next_cursor": next_cursor,
        }

    except (OperationalError, ProgrammingError) as exc:
        # agent_events table doesn't exist in this environment
        logger.warning("agent_events table not available: %s", exc)
        return {
            "events": [],
            "status": "unknown",
            "has_more": False,
            "oldest_sequence": None,
            "newest_sequence": None,
            "total_count": 0,
            "next_cursor": None,
        }
