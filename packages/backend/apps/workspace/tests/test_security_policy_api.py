"""Tests for Organization security policy API endpoints.

Covers:
- GET /{org_id}/security-policy — read security settings (viewer+)
- PATCH /{org_id}/security-policy — update security settings (admin+)
- GET /api/v1/compliance/security-policy — effective policy for current user
- Validation: timeout range, session limit range
- RBAC: viewers can read, only admins+ can update
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"
_COMPLIANCE = "/api/v1/compliance"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _create_org(name="Test Org"):
    owner, token = _make_user()
    resp = _post(_client(token), f"{_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None):
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


# =============================================================================
# GET SECURITY POLICY
# =============================================================================


class TestGetSecurityPolicy:
    def test_owner_can_read(self):
        org, owner, token = _create_org()
        resp = _client(token).get(f"{_BASE}/{org.pk}/security-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is False
        assert data["session_timeout_minutes"] is None
        assert data["max_concurrent_sessions"] is None

    def test_viewer_can_read(self):
        org, owner, owner_token = _create_org()
        viewer, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        resp = _client(viewer_token).get(f"{_BASE}/{org.pk}/security-policy")
        assert resp.status_code == 200

    def test_non_member_rejected(self):
        org, owner, owner_token = _create_org()
        outsider, outsider_token = _make_user()
        resp = _client(outsider_token).get(f"{_BASE}/{org.pk}/security-policy")
        assert resp.status_code == 401  # UnauthorizedAccessError → 401

    def test_unauthenticated_rejected(self):
        org, owner, owner_token = _create_org()
        resp = Client().get(f"{_BASE}/{org.pk}/security-policy")
        assert resp.status_code == 401


# =============================================================================
# PATCH SECURITY POLICY
# =============================================================================


class TestUpdateSecurityPolicy:
    def test_owner_can_update_all(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "mfa_required": True,
                "session_timeout_minutes": 60,
                "max_concurrent_sessions": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is True
        assert data["session_timeout_minutes"] == 60
        assert data["max_concurrent_sessions"] == 3

        # Verify persisted
        org.refresh_from_db()
        assert org.mfa_required is True
        assert org.session_timeout_minutes == 60
        assert org.max_concurrent_sessions == 3

    def test_admin_can_update(self):
        org, owner, owner_token = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "mfa_required": True,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["mfa_required"] is True

    def test_member_cannot_update(self):
        org, owner, owner_token = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "mfa_required": True,
            },
        )
        assert resp.status_code == 401  # UnauthorizedAccessError → 401

    def test_viewer_cannot_update(self):
        org, owner, owner_token = _create_org()
        viewer, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        resp = _patch(
            _client(viewer_token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "mfa_required": True,
            },
        )
        assert resp.status_code == 401  # UnauthorizedAccessError → 401

    def test_partial_update_mfa_only(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "mfa_required": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is True
        assert data["session_timeout_minutes"] is None
        assert data["max_concurrent_sessions"] is None

    def test_partial_update_timeout_only(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "session_timeout_minutes": 120,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["session_timeout_minutes"] == 120

    def test_invalid_timeout_too_low(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "session_timeout_minutes": 2,
            },
        )
        assert resp.status_code == 400
        assert "session_timeout_minutes" in resp.json()["detail"]

    def test_invalid_timeout_too_high(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "session_timeout_minutes": 999999,
            },
        )
        assert resp.status_code == 400

    def test_invalid_session_limit_too_low(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "max_concurrent_sessions": 0,
            },
        )
        assert resp.status_code == 400
        assert "max_concurrent_sessions" in resp.json()["detail"]

    def test_invalid_session_limit_too_high(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/security-policy",
            {
                "max_concurrent_sessions": 999,
            },
        )
        assert resp.status_code == 400


# =============================================================================
# EFFECTIVE SECURITY POLICY (compliance endpoint)
# =============================================================================


class TestEffectiveSecurityPolicy:
    def test_no_orgs_returns_defaults(self):
        user, token = _make_user()
        resp = _client(token).get(f"{_COMPLIANCE}/security-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is False
        assert data["mfa_enabled"] is False
        assert "session_timeout_minutes" in data
        assert "max_concurrent_sessions" in data

    def test_org_policy_reflected(self):
        org, owner, token = _create_org()
        org.mfa_required = True
        org.session_timeout_minutes = 30
        org.max_concurrent_sessions = 2
        org.save()
        resp = _client(token).get(f"{_COMPLIANCE}/security-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["mfa_required"] is True
        assert data["session_timeout_minutes"] == 30
        assert data["max_concurrent_sessions"] == 2

    def test_unauthenticated_rejected(self):
        resp = Client().get(f"{_COMPLIANCE}/security-policy")
        assert resp.status_code == 401
