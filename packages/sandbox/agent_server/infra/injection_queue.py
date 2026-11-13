"""Redis-backed FIFO injection queue for conversation message queuing.

Ported verbatim from backend/apps/agents/injection_queue.py — the only
change is the DjangoUser shadow model import for the GDPR-discard path.

Each conversation has a queue stored as a JSON list in Django cache under
``injection_queue:{conversation_id}``. Entries expire after QUEUE_TTL.
"""

from __future__ import annotations

import json
import logging
import time
import uuid as uuid_mod
from dataclasses import asdict, dataclass, field
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger("agent_server.injection_queue")

MAX_QUEUE_DEPTH = 10
QUEUE_TTL = 3600  # 1 hour


def _queue_key(conversation_id: str) -> str:
    return f"injection_queue:{conversation_id}"


@dataclass
class QueuedInjection:
    """A single queued injection entry."""

    user_id: str
    user_email: str
    user_display_name: str
    prompt: str
    files: list = field(default_factory=list)
    addons: list = field(default_factory=list)
    mcp_configs: list = field(default_factory=list)
    skill_ids: list = field(default_factory=list)
    model: Optional[str] = None
    customise: Optional[dict] = None
    queued_at: float = 0.0

    def __post_init__(self):
        if self.queued_at == 0.0:
            self.queued_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "QueuedInjection":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _get_queue(conversation_id: str) -> list[dict]:
    key = _queue_key(conversation_id)
    raw = cache.get(key)
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
    if isinstance(raw, list):
        return raw
    return []


def _set_queue(conversation_id: str, queue: list[dict]) -> None:
    key = _queue_key(conversation_id)
    if not queue:
        cache.delete(key)
    else:
        cache.set(key, json.dumps(queue), timeout=QUEUE_TTL)


class QueueFullError(Exception):
    """Raised when the injection queue is at max capacity."""


def enqueue(conversation_id: str, entry: QueuedInjection) -> int:
    queue = _get_queue(conversation_id)
    if len(queue) >= MAX_QUEUE_DEPTH:
        raise QueueFullError(f"Injection queue full (max {MAX_QUEUE_DEPTH})")
    queue.append(entry.to_dict())
    _set_queue(conversation_id, queue)
    position = len(queue)
    logger.info(
        "[INJECT-QUEUE] Enqueued for conversation %s at position %d (user=%s)",
        conversation_id,
        position,
        entry.user_id,
    )
    return position


def dequeue(conversation_id: str) -> Optional[QueuedInjection]:
    queue = _get_queue(conversation_id)
    if not queue:
        return None
    entry_dict = queue.pop(0)
    _set_queue(conversation_id, queue)
    entry = QueuedInjection.from_dict(entry_dict)
    logger.info(
        "[INJECT-QUEUE] Dequeued from conversation %s (user=%s, remaining=%d)",
        conversation_id,
        entry.user_id,
        len(queue),
    )
    return entry


def cancel_at_position(conversation_id: str, position: int, user_id: str) -> bool:
    queue = _get_queue(conversation_id)
    idx = position - 1
    if idx < 0 or idx >= len(queue):
        return False
    entry = queue[idx]
    if entry.get("user_id") != user_id:
        return False
    queue.pop(idx)
    _set_queue(conversation_id, queue)
    logger.info(
        "[INJECT-QUEUE] Cancelled position %d in conversation %s (user=%s)",
        position,
        conversation_id,
        user_id,
    )
    return True


def clear_queue(conversation_id: str) -> int:
    queue = _get_queue(conversation_id)
    count = len(queue)
    if count > 0:
        cache.delete(_queue_key(conversation_id))
        logger.info(
            "[INJECT-QUEUE] Cleared %d entries for conversation %s",
            count,
            conversation_id,
        )
    return count


def get_queue_entries(conversation_id: str) -> list[QueuedInjection]:
    return [QueuedInjection.from_dict(d) for d in _get_queue(conversation_id)]


def queue_depth(conversation_id: str) -> int:
    return len(_get_queue(conversation_id))


def discard_deleted_users(conversation_id: str) -> list[str]:
    """Remove entries from users who no longer exist (GDPR). Uses DjangoUser shadow."""
    from agent_server.models import DjangoUser

    queue = _get_queue(conversation_id)
    if not queue:
        return []

    user_ids = {e["user_id"] for e in queue}
    existing = set(
        str(uid)
        for uid in DjangoUser.objects.filter(id__in=[int(uid) for uid in user_ids if uid.isdigit()]).values_list(
            "id", flat=True
        )
    )
    uuid_ids = []
    for uid in user_ids:
        try:
            uuid_mod.UUID(uid)
            uuid_ids.append(uid)
        except ValueError:
            pass
    if uuid_ids:
        existing.update(str(uid) for uid in DjangoUser.objects.filter(id__in=uuid_ids).values_list("id", flat=True))

    discarded = []
    new_queue = []
    for entry in queue:
        if entry["user_id"] in existing or str(entry["user_id"]) in existing:
            new_queue.append(entry)
        else:
            discarded.append(entry["user_id"])

    if discarded:
        _set_queue(conversation_id, new_queue)
        logger.info(
            "[INJECT-QUEUE] Discarded %d entries from deleted users in conversation %s",
            len(discarded),
            conversation_id,
        )
    return discarded
