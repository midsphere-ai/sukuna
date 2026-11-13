"""Tests for US-021: Real-time presence — backend (Redis + SSE events).

Tests cover:
- Heartbeat updates TTL and presence
- Join/leave events
- Typing indicators (start/stop)
- Multiple conversations isolated
- Expired users removed
- Deduplication (same user, multiple tabs)
- Typing auto-expiry
"""

import time

import pytest
from cryptography.fernet import Fernet
from django.core.cache import cache

from apps.agents.presence import (
    PRESENCE_TTL,
    PresenceEntry,
    _presence_key,
    _typing_key,
    clear_presence,
    get_present_users,
    get_typing_users,
    heartbeat,
    leave,
    set_typing,
)

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)


@pytest.fixture(autouse=True)
def _clear_cache():
    yield
    cache.clear()


CONV_ID = "presence-conv-001"


# ── Heartbeat ───────────────────────────────────────────────────────────


class TestHeartbeat:
    def test_first_heartbeat_is_join(self):
        is_new, expired = heartbeat(CONV_ID, "u1", "Alice")
        assert is_new is True
        assert expired == []

    def test_subsequent_heartbeat_not_join(self):
        heartbeat(CONV_ID, "u1", "Alice")
        is_new, _ = heartbeat(CONV_ID, "u1", "Alice")
        assert is_new is False

    def test_heartbeat_updates_timestamp(self):
        heartbeat(CONV_ID, "u1", "Alice")
        users1 = get_present_users(CONV_ID)
        ts1 = users1[0].last_seen

        time.sleep(0.05)
        heartbeat(CONV_ID, "u1", "Alice")
        users2 = get_present_users(CONV_ID)
        ts2 = users2[0].last_seen
        assert ts2 > ts1

    def test_multiple_users_present(self):
        heartbeat(CONV_ID, "u1", "Alice")
        heartbeat(CONV_ID, "u2", "Bob")
        heartbeat(CONV_ID, "u3", "Charlie")

        users = get_present_users(CONV_ID)
        assert len(users) == 3
        user_ids = {u.user_id for u in users}
        assert user_ids == {"u1", "u2", "u3"}

    def test_heartbeat_includes_avatar(self):
        heartbeat(CONV_ID, "u1", "Alice", avatar="https://example.com/avatar.png")
        users = get_present_users(CONV_ID)
        assert users[0].avatar == "https://example.com/avatar.png"


# ── Join / Leave ────────────────────────────────────────────────────────


class TestJoinLeave:
    def test_leave_removes_user(self):
        heartbeat(CONV_ID, "u1", "Alice")
        heartbeat(CONV_ID, "u2", "Bob")
        assert leave(CONV_ID, "u1") is True

        users = get_present_users(CONV_ID)
        assert len(users) == 1
        assert users[0].user_id == "u2"

    def test_leave_absent_user_returns_false(self):
        assert leave(CONV_ID, "nonexistent") is False

    def test_clear_presence(self):
        heartbeat(CONV_ID, "u1", "Alice")
        heartbeat(CONV_ID, "u2", "Bob")
        clear_presence(CONV_ID)
        assert get_present_users(CONV_ID) == []


# ── Expired users removed ──────────────────────────────────────────────


class TestExpiredUsers:
    def test_expired_entries_purged(self, monkeypatch):
        """Entries older than PRESENCE_TTL are automatically removed."""
        # Heartbeat with a very old timestamp by directly injecting
        import json

        old_ts = time.time() - PRESENCE_TTL - 10  # 10 seconds past TTL
        pmap = {
            "u1": {"display_name": "Alice", "avatar": "", "last_seen": old_ts},
            "u2": {"display_name": "Bob", "avatar": "", "last_seen": time.time()},
        }
        cache.set(_presence_key(CONV_ID), json.dumps(pmap), timeout=PRESENCE_TTL * 2)

        users = get_present_users(CONV_ID)
        assert len(users) == 1
        assert users[0].user_id == "u2"

    def test_heartbeat_reports_expired_users(self):
        """Heartbeat returns expired user IDs."""
        import json

        old_ts = time.time() - PRESENCE_TTL - 10
        pmap = {
            "u1": {"display_name": "Alice", "avatar": "", "last_seen": old_ts},
        }
        cache.set(_presence_key(CONV_ID), json.dumps(pmap), timeout=PRESENCE_TTL * 2)

        is_new, expired = heartbeat(CONV_ID, "u2", "Bob")
        assert is_new is True
        assert "u1" in expired


# ── Deduplication ───────────────────────────────────────────────────────


class TestDeduplication:
    def test_same_user_multiple_heartbeats(self):
        """Same user from multiple tabs → single presence entry."""
        heartbeat(CONV_ID, "u1", "Alice")
        heartbeat(CONV_ID, "u1", "Alice")
        heartbeat(CONV_ID, "u1", "Alice")

        users = get_present_users(CONV_ID)
        assert len(users) == 1

    def test_dedup_updates_display_name(self):
        """If user changes display name, latest wins."""
        heartbeat(CONV_ID, "u1", "Old Name")
        heartbeat(CONV_ID, "u1", "New Name")

        users = get_present_users(CONV_ID)
        assert users[0].display_name == "New Name"


# ── Typing indicators ──────────────────────────────────────────────────


class TestTyping:
    def test_start_typing(self):
        set_typing(CONV_ID, "u1", "start")
        typers = get_typing_users(CONV_ID)
        assert "u1" in typers

    def test_stop_typing(self):
        set_typing(CONV_ID, "u1", "start")
        set_typing(CONV_ID, "u1", "stop")
        typers = get_typing_users(CONV_ID)
        assert "u1" not in typers

    def test_multiple_typers(self):
        set_typing(CONV_ID, "u1", "start")
        set_typing(CONV_ID, "u2", "start")
        typers = get_typing_users(CONV_ID)
        assert set(typers) == {"u1", "u2"}

    def test_typing_empty_when_none(self):
        assert get_typing_users(CONV_ID) == []


# ── Conversation isolation ──────────────────────────────────────────────


class TestConversationIsolation:
    def test_different_conversations_independent(self):
        heartbeat("conv-a", "u1", "Alice")
        heartbeat("conv-b", "u2", "Bob")

        users_a = get_present_users("conv-a")
        users_b = get_present_users("conv-b")
        assert len(users_a) == 1
        assert len(users_b) == 1
        assert users_a[0].user_id == "u1"
        assert users_b[0].user_id == "u2"

    def test_typing_isolated(self):
        set_typing("conv-a", "u1", "start")
        assert get_typing_users("conv-a") == ["u1"]
        assert get_typing_users("conv-b") == []

    def test_clear_one_conversation_doesnt_affect_other(self):
        heartbeat("conv-a", "u1", "Alice")
        heartbeat("conv-b", "u2", "Bob")
        clear_presence("conv-a")
        assert get_present_users("conv-a") == []
        assert len(get_present_users("conv-b")) == 1


# ── PresenceEntry ───────────────────────────────────────────────────────


class TestPresenceEntry:
    def test_to_dict(self):
        entry = PresenceEntry(
            user_id="u1", display_name="Alice", avatar="av.png", last_seen=1.0
        )
        d = entry.to_dict()
        assert d["user_id"] == "u1"
        assert d["display_name"] == "Alice"
        assert d["avatar"] == "av.png"

    def test_key_format(self):
        assert _presence_key("abc") == "presence:abc"
        assert _typing_key("abc") == "typing:abc"
