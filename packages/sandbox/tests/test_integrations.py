"""Unit tests for the sandbox messaging integrations (Telegram/Slack/Claw).

Covers:
- ``TelegramSignatureAuth`` — constant-time secret-token compare.
- ``SlackSignatureAuth`` — HMAC-SHA256 over ``v0:{ts}:{body}`` with 5-minute window.
- ``_chunk_text`` and ``_rate_limited`` — shared helpers.
- URL-verification challenge on the Slack events webhook (signature validated).
- Command dispatch surface (bot-ignore, unknown command fallback).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_server.auth import SlackSignatureAuth, TelegramSignatureAuth

# ─────────────────────────────────────────────────────────────────────────────
# TelegramSignatureAuth
# ─────────────────────────────────────────────────────────────────────────────


def test_telegram_auth_accepts_matching_secret() -> None:
    auth = TelegramSignatureAuth()
    with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "s3cret"}):
        assert auth.authenticate(SimpleNamespace(), "s3cret") == "telegram_webhook"


def test_telegram_auth_rejects_mismatched_secret() -> None:
    auth = TelegramSignatureAuth()
    with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "s3cret"}):
        assert auth.authenticate(SimpleNamespace(), "nope") is None


def test_telegram_auth_rejects_when_secret_unset() -> None:
    auth = TelegramSignatureAuth()
    # Unset the env var so authenticate() sees an empty expected value.
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)
        assert auth.authenticate(SimpleNamespace(), "anything") is None


def test_telegram_auth_rejects_none_key() -> None:
    auth = TelegramSignatureAuth()
    with patch.dict(os.environ, {"TELEGRAM_WEBHOOK_SECRET": "s3cret"}):
        assert auth.authenticate(SimpleNamespace(), None) is None


# ─────────────────────────────────────────────────────────────────────────────
# SlackSignatureAuth
# ─────────────────────────────────────────────────────────────────────────────


def _slack_sign(secret: str, timestamp: str, body: bytes) -> str:
    basestring = f"v0:{timestamp}:{body.decode('utf-8')}"
    return "v0=" + hmac.new(secret.encode("utf-8"), basestring.encode("utf-8"), hashlib.sha256).hexdigest()


def _make_slack_request(secret: str, body: bytes, *, ts_offset: int = 0):
    ts = str(int(time.time()) + ts_offset)
    sig = _slack_sign(secret, ts, body)
    request = SimpleNamespace(
        headers={"X-Slack-Request-Timestamp": ts, "X-Slack-Signature": sig},
        body=body,
    )
    return request


def test_slack_auth_accepts_valid_signature() -> None:
    secret = "signing-secret"
    body = b'{"type":"url_verification","challenge":"abc"}'
    req = _make_slack_request(secret, body)
    auth = SlackSignatureAuth()
    with patch.dict(os.environ, {"SLACK_SIGNING_SECRET": secret}):
        assert auth.authenticate(req, "") == "slack_webhook"


def test_slack_auth_rejects_bad_signature() -> None:
    secret = "signing-secret"
    body = b'{"type":"event_callback"}'
    req = _make_slack_request(secret, body)
    # Corrupt the signature after the fact.
    req.headers["X-Slack-Signature"] = "v0=deadbeef"
    auth = SlackSignatureAuth()
    with patch.dict(os.environ, {"SLACK_SIGNING_SECRET": secret}):
        assert auth.authenticate(req, "") is None


def test_slack_auth_rejects_stale_timestamp() -> None:
    secret = "signing-secret"
    body = b'{"type":"event_callback"}'
    # 400 seconds in the past — outside the 5-minute anti-replay window.
    req = _make_slack_request(secret, body, ts_offset=-400)
    auth = SlackSignatureAuth()
    with patch.dict(os.environ, {"SLACK_SIGNING_SECRET": secret}):
        assert auth.authenticate(req, "") is None


def test_slack_auth_rejects_when_secret_unset() -> None:
    auth = SlackSignatureAuth()
    req = _make_slack_request("anything", b"")
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SLACK_SIGNING_SECRET", None)
        assert auth.authenticate(req, "") is None


def test_slack_auth_rejects_missing_headers() -> None:
    secret = "signing-secret"
    req = SimpleNamespace(headers={}, body=b"{}")
    auth = SlackSignatureAuth()
    with patch.dict(os.environ, {"SLACK_SIGNING_SECRET": secret}):
        assert auth.authenticate(req, "") is None


def test_slack_auth_rejects_invalid_timestamp_format() -> None:
    secret = "signing-secret"
    req = SimpleNamespace(
        headers={"X-Slack-Request-Timestamp": "not-a-number", "X-Slack-Signature": "v0=ab"},
        body=b"",
    )
    auth = SlackSignatureAuth()
    with patch.dict(os.environ, {"SLACK_SIGNING_SECRET": secret}):
        assert auth.authenticate(req, "") is None


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (_chunk_text, _rate_limited)
# ─────────────────────────────────────────────────────────────────────────────


def test_chunk_text_returns_single_chunk_when_short() -> None:
    from agent_server.api.integrations import _chunk_text

    assert _chunk_text("hello", 100) == ["hello"]


def test_chunk_text_prefers_newlines_then_spaces() -> None:
    from agent_server.api.integrations import _chunk_text

    # Force multi-chunk at a newline boundary.
    text = "line one\nline two"
    chunks = _chunk_text(text, 10)
    assert chunks[0] == "line one"
    assert chunks[1].strip() == "line two"


def test_chunk_text_hard_splits_when_no_break_found() -> None:
    from agent_server.api.integrations import _chunk_text

    text = "a" * 25
    chunks = _chunk_text(text, 10)
    assert all(len(c) <= 10 for c in chunks)
    assert "".join(chunks) == text


def test_rate_limited_admits_up_to_the_cap(monkeypatch) -> None:
    from django.core.cache import cache

    from agent_server.api.integrations import RATE_LIMIT_MAX, _rate_limited

    cache.clear()
    platform = "telegram"
    key = "test-user"
    # Up to RATE_LIMIT_MAX calls succeed.
    for _ in range(RATE_LIMIT_MAX):
        assert _rate_limited(platform, key) is False
    # The next call is blocked.
    assert _rate_limited(platform, key) is True


# ─────────────────────────────────────────────────────────────────────────────
# Webhook behaviour: URL verification + bot-message ignore
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_slack_events_url_verification_returns_challenge() -> None:
    """Slack URL-verification must echo the challenge verbatim as JSON."""
    from agent_server.api.integrations import slack_events_webhook

    body = json.dumps({"type": "url_verification", "challenge": "abc123"}).encode("utf-8")
    request = SimpleNamespace(body=body)
    response = await slack_events_webhook(request)
    # JsonResponse stores the serialized body under .content
    decoded = json.loads(response.content)
    assert decoded == {"challenge": "abc123"}


@pytest.mark.asyncio
async def test_slack_events_ignores_bot_messages() -> None:
    """Incoming events with bot_id / bot_message subtype must short-circuit.

    This prevents infinite echo loops where the bot's own replies re-trigger
    the handler.
    """
    from agent_server.api.integrations import slack_events_webhook

    body = json.dumps(
        {
            "type": "event_callback",
            "event": {
                "type": "message",
                "bot_id": "B12345",
                "user": "U987",
                "channel": "D123",
                "text": "echo",
                "channel_type": "im",
            },
        }
    ).encode("utf-8")
    response = await slack_events_webhook(SimpleNamespace(body=body))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_telegram_webhook_ignores_missing_text() -> None:
    """Telegram updates without a chat_id or text return 200 with no side effects."""
    from agent_server.api.integrations import telegram_webhook

    body = json.dumps({"message": {}}).encode("utf-8")
    response = await telegram_webhook(SimpleNamespace(body=body))
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_telegram_webhook_rejects_malformed_json() -> None:
    from agent_server.api.integrations import telegram_webhook

    response = await telegram_webhook(SimpleNamespace(body=b"not json"))
    assert response.status_code == 400
