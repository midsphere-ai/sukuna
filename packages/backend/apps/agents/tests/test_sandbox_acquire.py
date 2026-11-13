"""
Tests for POST /api/v1/chat/sandbox/acquire and /api/v1/chat/sandbox/jwt-refresh.

These are Step 2 of the backend-purge plan: one backend call per session to hand
the frontend a ``(sandbox_host, jwt)`` pair. The sandbox then owns the whole run
lifecycle and the backend sees no further per-run traffic.
"""

import json
import uuid

import jwt as pyjwt
import pytest
from django.conf import settings
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.agents.models import E2bSandbox
from apps.storage.models import Conversation
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_P = "/api/v1/chat"
FAKE_HOST = "sbx-test.e2b.dev"
# Endpoint normalizes bare E2B hosts with https:// before returning.
EXPECTED_HOST = f"https://{FAKE_HOST}"


def _user_with_token():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _authed_client(token: str) -> Client:
    return Client(headers={"authorization": f"Bearer {token}"})


def _fake_provision(monkeypatch):
    """Stub out provision_sandbox_for_conversation to avoid real E2B calls."""
    from asgiref.sync import sync_to_async

    record_box: dict = {}

    async def _provision(conversation, user):
        if "record" not in record_box:
            record_box["record"] = await sync_to_async(E2bSandbox.objects.create)(
                conversation=conversation,
                sandbox_id="sbx-fake",
                sandbox_state=E2bSandbox.SandboxState.READY,
            )
        return record_box["record"], FAKE_HOST

    monkeypatch.setattr(
        "apps.agents.views.provision_sandbox_for_conversation",
        _provision,
    )


def _decode_jwt(token: str) -> dict:
    return pyjwt.decode(
        token,
        settings.SUKUNA_STREAM_JWT_SECRET,
        algorithms=["HS256"],
        issuer="sukuna-backend",
        audience="sukuna-sandbox-stream",
        options={"require": ["exp", "sub", "iss", "aud"]},
    )


class TestAcquireSandbox:
    def test_requires_auth(self):
        resp = Client().post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"prompt_preview": "hi"}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_creates_conversation_and_mints_token_when_id_omitted(self, monkeypatch):
        _fake_provision(monkeypatch)
        user, token = _user_with_token()

        resp = _authed_client(token).post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"prompt_preview": "first message"}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()

        # Conversation was created and the id round-trips.
        assert Conversation.objects.filter(id=body["conversation_id"]).exists()
        assert body["sandbox_host"] == EXPECTED_HOST
        assert body["jwt"]

        claims = _decode_jwt(body["jwt"])
        # No run yet → ``sub`` is the conversation scope sentinel.
        assert claims["sub"] == f"conv:{body['conversation_id']}"
        assert set(claims["scope"]) == {
            "stream:read",
            "run:admin",
            "hitl:respond",
            "mcp:manage",
            "files:rw",
        }
        assert claims["user_id"] == str(user.id)

    def test_reuses_existing_conversation(self, monkeypatch):
        _fake_provision(monkeypatch)
        user, token = _user_with_token()
        conv = Conversation.objects.create(user=user, title="Existing")

        resp = _authed_client(token).post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"conversation_id": str(conv.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == str(conv.id)

    def test_returns_403_when_conversation_owner_mismatches(self, monkeypatch):
        _fake_provision(monkeypatch)
        owner = UserFactory()
        conv = Conversation.objects.create(user=owner, title="Other user")

        _, outsider_token = _user_with_token()
        resp = _authed_client(outsider_token).post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"conversation_id": str(conv.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_returns_404_for_missing_conversation(self, monkeypatch):
        _fake_provision(monkeypatch)
        _, token = _user_with_token()
        resp = _authed_client(token).post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"conversation_id": str(uuid.uuid4())}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_provision_failure_surfaces_as_502(self, monkeypatch):
        from ninja.errors import HttpError

        async def _boom(conversation, user):
            raise HttpError(502, "Failed to provision sandbox")

        monkeypatch.setattr(
            "apps.agents.views.provision_sandbox_for_conversation", _boom
        )

        _, token = _user_with_token()
        resp = _authed_client(token).post(
            f"{_P}/sandbox/acquire",
            data=json.dumps({"prompt_preview": "x"}),
            content_type="application/json",
        )
        assert resp.status_code == 502


class TestJwtRefresh:
    def test_requires_conversation_id(self, monkeypatch):
        _fake_provision(monkeypatch)
        _, token = _user_with_token()
        resp = _authed_client(token).post(
            f"{_P}/sandbox/jwt-refresh",
            data=json.dumps({}),
            content_type="application/json",
        )
        # Schema validation failure.
        assert resp.status_code == 422

    def test_returns_new_token_for_same_conversation(self, monkeypatch):
        _fake_provision(monkeypatch)
        user, token = _user_with_token()
        conv = Conversation.objects.create(user=user, title="Refresh me")

        resp = _authed_client(token).post(
            f"{_P}/sandbox/jwt-refresh",
            data=json.dumps({"conversation_id": str(conv.id)}),
            content_type="application/json",
        )
        assert resp.status_code == 200, resp.content
        body = resp.json()
        assert body["conversation_id"] == str(conv.id)

        claims = _decode_jwt(body["jwt"])
        assert claims["sub"] == f"conv:{conv.id}"
        assert "run:admin" in claims["scope"]

    def test_rejects_other_users_conversation(self, monkeypatch):
        _fake_provision(monkeypatch)
        owner = UserFactory()
        conv = Conversation.objects.create(user=owner, title="Not yours")

        _, outsider_token = _user_with_token()
        resp = _authed_client(outsider_token).post(
            f"{_P}/sandbox/jwt-refresh",
            data=json.dumps({"conversation_id": str(conv.id)}),
            content_type="application/json",
        )
        # get_conversation_for_user raises 403 for non-owner without share.
        assert resp.status_code in (403, 404)
