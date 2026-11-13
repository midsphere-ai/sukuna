"""Real-time presence tracking for conversation viewers.

Uses Django cache (Redis in production) to store per-conversation presence
as a dict mapping user_id → {display_name, avatar, last_seen_ts}.

Key: ``presence:{conversation_id}``

Presence entries expire after PRESENCE_TTL seconds (60s). Missing two
consecutive heartbeats (sent every ~30s) causes the user to be considered
gone.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass

from django.core.cache import cache

logger = logging.getLogger(__name__)

PRESENCE_TTL = 60  # seconds — 2 missed heartbeats = gone
TYPING_TTL = 5  # seconds — typing indicator auto-expires


def _presence_key(conversation_id: str) -> str:
    return f"presence:{conversation_id}"


def _typing_key(conversation_id: str) -> str:
    return f"typing:{conversation_id}"


@dataclass
class PresenceEntry:
    """A single user's presence in a conversation."""

    user_id: str
    display_name: str
    avatar: str = ""
    last_seen: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def _get_presence_map(conversation_id: str) -> dict[str, dict]:
    """Return the presence dict from cache {user_id: {display_name, avatar, last_seen}}."""
    key = _presence_key(conversation_id)
    raw = cache.get(key)
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
    if isinstance(raw, dict):
        return raw
    return {}


def _set_presence_map(conversation_id: str, pmap: dict[str, dict]) -> None:
    key = _presence_key(conversation_id)
    if not pmap:
        cache.delete(key)
    else:
        cache.set(key, json.dumps(pmap), timeout=PRESENCE_TTL * 2)


def _purge_expired(pmap: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """Remove entries older than PRESENCE_TTL. Returns (cleaned_map, left_user_ids)."""
    now = time.time()
    cutoff = now - PRESENCE_TTL
    left = []
    cleaned = {}
    for uid, data in pmap.items():
        if data.get("last_seen", 0) >= cutoff:
            cleaned[uid] = data
        else:
            left.append(uid)
    return cleaned, left


def heartbeat(
    conversation_id: str,
    user_id: str,
    display_name: str,
    avatar: str = "",
) -> tuple[bool, list[str]]:
    """Update presence for a user. Returns (is_new_join, expired_user_ids).

    - If user was not present, this is a join → is_new_join=True.
    - Expired entries are purged and returned.
    """
    pmap = _get_presence_map(conversation_id)
    pmap, expired = _purge_expired(pmap)

    is_new = user_id not in pmap
    pmap[user_id] = {
        "display_name": display_name,
        "avatar": avatar,
        "last_seen": time.time(),
    }
    _set_presence_map(conversation_id, pmap)

    if is_new:
        logger.debug(
            "[PRESENCE] Join: user %s in conversation %s", user_id, conversation_id
        )
    return is_new, expired


def leave(conversation_id: str, user_id: str) -> bool:
    """Remove a user from presence. Returns True if they were present."""
    pmap = _get_presence_map(conversation_id)
    if user_id not in pmap:
        return False
    del pmap[user_id]
    _set_presence_map(conversation_id, pmap)
    logger.debug(
        "[PRESENCE] Leave: user %s from conversation %s", user_id, conversation_id
    )
    return True


def get_present_users(conversation_id: str) -> list[PresenceEntry]:
    """Return all currently present users (with expired entries purged)."""
    pmap = _get_presence_map(conversation_id)
    pmap, expired = _purge_expired(pmap)
    if expired:
        _set_presence_map(conversation_id, pmap)
    return [
        PresenceEntry(
            user_id=uid,
            display_name=data.get("display_name", ""),
            avatar=data.get("avatar", ""),
            last_seen=data.get("last_seen", 0),
        )
        for uid, data in pmap.items()
    ]


def clear_presence(conversation_id: str) -> None:
    """Clear all presence for a conversation."""
    cache.delete(_presence_key(conversation_id))
    cache.delete(_typing_key(conversation_id))


# ── Typing indicators ──────────────────────────────────────────────────


def set_typing(conversation_id: str, user_id: str, action: str) -> None:
    """Set or clear typing status for a user.

    Args:
        action: "start" or "stop"
    """
    key = _typing_key(conversation_id)
    raw = cache.get(key)
    typing_map: dict = {}
    if raw:
        try:
            typing_map = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            pass

    if action == "start":
        typing_map[user_id] = time.time()
    elif action == "stop":
        typing_map.pop(user_id, None)

    if typing_map:
        cache.set(key, json.dumps(typing_map), timeout=TYPING_TTL)
    else:
        cache.delete(key)


def get_typing_users(conversation_id: str) -> list[str]:
    """Return user IDs currently typing (within TYPING_TTL)."""
    key = _typing_key(conversation_id)
    raw = cache.get(key)
    if not raw:
        return []
    try:
        typing_map = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []

    now = time.time()
    cutoff = now - TYPING_TTL
    return [uid for uid, ts in typing_map.items() if ts >= cutoff]
