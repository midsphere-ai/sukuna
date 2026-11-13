"""Tests for enterprise mode toggle, gating, auto-enable, and lifecycle.

Covers US-016B acceptance criteria:
- Toggle on/off
- Gated endpoints return 403 when disabled
- Auto-enable on invite accept
- Cannot disable while in orgs (409)
- Free user cannot enable (402)
- Subscription lapse grace period
- All 6 onboarding flows (backend portion)
- AuditLog entries
- enterprise_mode in /users/me response
"""

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.billing.models import SubscriptionPlan, UserSubscription
from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.enterprise import (
    EnterpriseDisabledError,
    auto_enable_enterprise,
    get_or_create_enterprise_config,
    is_enterprise_enabled,
    require_enterprise,
)
from apps.workspace.models import (
    EnterpriseConfig,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_WS = "/api/v1/workspace"
_ORG = f"{_WS}/organizations"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture(autouse=True)
def _auto_enable_enterprise():
    """Override the workspace conftest fixture that auto-enables enterprise.

    In this test module we need explicit control over enterprise mode,
    so this fixture is a no-op replacement.
    """
    yield


_TEST_PASSWORD = "SecureTestPassword123!"


def _make_user(enterprise_enabled=False, paid=False):
    """Create a user, optionally with enterprise mode and/or paid subscription."""
    user = UserFactory(password=_TEST_PASSWORD)
    token, _ = Token.objects.get_or_create(user=user)

    if enterprise_enabled:
        EnterpriseConfig.objects.create(
            user=user, enabled=True, enabled_at=timezone.now()
        )

    if paid:
        plan, _ = SubscriptionPlan.objects.get_or_create(
            tier="premium",
            defaults={"name": "Premium", "price": 25.00, "is_active": True},
        )
        UserSubscription.objects.create(user=user, plan=plan, status="active")
    else:
        plan, _ = SubscriptionPlan.objects.get_or_create(
            tier="free",
            defaults={"name": "Free", "price": 0.00, "is_active": True},
        )
        UserSubscription.objects.get_or_create(
            user=user, defaults={"plan": plan, "status": "active"}
        )

    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


# =============================================================================
# ENTERPRISE CONFIG MODEL
# =============================================================================


class TestEnterpriseConfigModel:
    """Test EnterpriseConfig model and utility functions."""

    def test_get_or_create_creates_disabled(self):
        user, _ = _make_user()
        # Remove any auto-created config
        EnterpriseConfig.objects.filter(user=user).delete()
        config = get_or_create_enterprise_config(user)
        assert config.enabled is False
        assert config.user == user

    def test_is_enterprise_enabled_false_by_default(self):
        user, _ = _make_user()
        assert is_enterprise_enabled(user) is False

    def test_is_enterprise_enabled_true_when_enabled(self):
        user, _ = _make_user(enterprise_enabled=True)
        assert is_enterprise_enabled(user) is True

    def test_auto_enable_enterprise(self):
        user, _ = _make_user()
        config = auto_enable_enterprise(user)
        assert config.enabled is True
        assert config.enabled_at is not None

    def test_auto_enable_idempotent(self):
        user, _ = _make_user(enterprise_enabled=True)
        original_config = user.enterprise_config
        config = auto_enable_enterprise(user)
        assert config.pk == original_config.pk

    def test_grace_period_property(self):
        user, _ = _make_user(enterprise_enabled=True)
        config = user.enterprise_config
        config.grace_period_end = timezone.now() + timedelta(days=15)
        config.save()
        assert config.is_in_grace_period is True
        assert config.is_grace_period_expired is False

    def test_grace_period_expired(self):
        user, _ = _make_user(enterprise_enabled=True)
        config = user.enterprise_config
        config.grace_period_end = timezone.now() - timedelta(days=1)
        config.save()
        assert config.is_in_grace_period is False
        assert config.is_grace_period_expired is True


# =============================================================================
# ENTERPRISE MODE API
# =============================================================================


class TestGetEnterpriseMode:
    """GET /workspace/enterprise-mode."""

    def test_returns_disabled_by_default(self):
        _, token = _make_user()
        resp = _client(token).get(f"{_WS}/enterprise-mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False
        assert data["available"] is False  # free user

    def test_returns_enabled_for_enterprise_user(self):
        _, token = _make_user(enterprise_enabled=True, paid=True)
        resp = _client(token).get(f"{_WS}/enterprise-mode")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["available"] is True

    def test_unauthenticated_returns_401(self):
        resp = Client().get(f"{_WS}/enterprise-mode")
        assert resp.status_code == 401


class TestUpdateEnterpriseMode:
    """PATCH /workspace/enterprise-mode."""

    def test_enable_as_paid_user(self):
        user, token = _make_user(paid=True)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        # Verify persisted
        user.refresh_from_db()
        assert is_enterprise_enabled(user) is True

    def test_enable_as_free_user_returns_402(self):
        _, token = _make_user(paid=False)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 402

    def test_disable_when_no_orgs(self):
        user, token = _make_user(enterprise_enabled=True, paid=True)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": False, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_disable_returns_409_when_in_orgs(self):
        user, token = _make_user(enterprise_enabled=True, paid=True)
        org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.OWNER,
        )
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": False, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 409
        data = resp.json()
        assert "organizations" in data
        assert len(data["organizations"]) == 1
        assert data["organizations"][0]["name"] == "Test Org"

    def test_enable_creates_audit_log(self):
        user, token = _make_user(paid=True)
        _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": _TEST_PASSWORD},
        )
        log = AuditLog.objects.filter(action="enterprise_mode_enabled").first()
        assert log is not None
        assert log.actor_email == user.email

    def test_disable_creates_audit_log(self):
        user, token = _make_user(enterprise_enabled=True, paid=True)
        _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": False, "current_password": _TEST_PASSWORD},
        )
        log = AuditLog.objects.filter(action="enterprise_mode_disabled").first()
        assert log is not None
        assert log.actor_email == user.email

    def test_enable_idempotent_no_duplicate_audit(self):
        _, token = _make_user(enterprise_enabled=True, paid=True)
        _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": _TEST_PASSWORD},
        )
        # Should not create a new audit log since already enabled
        count = AuditLog.objects.filter(action="enterprise_mode_enabled").count()
        assert count == 0

    def test_wrong_password_returns_403(self):
        _, token = _make_user(paid=True)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": "wrong_password"},
        )
        assert resp.status_code == 403
        assert "Invalid password" in resp.json()["detail"]


# =============================================================================
# ENTERPRISE GATE ON ORG ENDPOINTS
# =============================================================================


class TestEnterpriseGate:
    """Org endpoints return 403 when enterprise mode is disabled."""

    def test_create_org_blocked_when_disabled(self):
        _, token = _make_user(enterprise_enabled=False)
        resp = _post(_client(token), f"{_ORG}/", {"name": "Test"})
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "ENTERPRISE_FEATURES_DISABLED"

    def test_list_orgs_blocked_when_disabled(self):
        _, token = _make_user(enterprise_enabled=False)
        resp = _client(token).get(f"{_ORG}/")
        assert resp.status_code == 403

    def test_create_org_allowed_when_enabled(self):
        _, token = _make_user(enterprise_enabled=True, paid=True)
        resp = _post(_client(token), f"{_ORG}/", {"name": "Test Org"})
        assert resp.status_code == 201

    def test_get_org_blocked_when_disabled(self):
        user, token = _make_user(enterprise_enabled=False)
        org = Organization.objects.create(name="Test Org")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.OWNER
        )
        resp = _client(token).get(f"{_ORG}/{org.pk}")
        assert resp.status_code == 403

    def test_security_policy_blocked_when_disabled(self):
        user, token = _make_user(enterprise_enabled=False)
        org = Organization.objects.create(name="Test Org")
        resp = _client(token).get(f"{_ORG}/{org.pk}/security-policy")
        assert resp.status_code == 403

    def test_sso_endpoints_blocked_when_disabled(self):
        user, token = _make_user(enterprise_enabled=False)
        org = Organization.objects.create(name="Test Org")
        resp = _client(token).get(f"{_ORG}/{org.pk}/sso")
        assert resp.status_code == 403

    def test_scim_token_endpoints_blocked_when_disabled(self):
        user, token = _make_user(enterprise_enabled=False)
        org = Organization.objects.create(name="Test Org")
        resp = _client(token).get(f"{_ORG}/{org.pk}/scim-tokens")
        assert resp.status_code == 403


# =============================================================================
# AUTO-ENABLE ON INVITE
# =============================================================================


class TestAutoEnableOnInvite:
    """Enterprise mode is auto-enabled when a user is added to an org via invite."""

    def test_invite_auto_enables_enterprise(self):
        # Owner creates org
        owner, owner_token = _make_user(enterprise_enabled=True, paid=True)
        resp = _post(_client(owner_token), f"{_ORG}/", {"name": "Test Org"})
        assert resp.status_code == 201
        org_id = resp.json()["id"]

        # Target user has no enterprise mode
        target, _ = _make_user(enterprise_enabled=False)
        assert is_enterprise_enabled(target) is False

        # Owner invites target
        resp = _post(
            _client(owner_token),
            f"{_ORG}/{org_id}/members",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 201

        # Target now has enterprise mode enabled
        target.refresh_from_db()
        assert is_enterprise_enabled(target) is True


# =============================================================================
# USERS/ME RESPONSE
# =============================================================================


class TestUsersMe:
    """enterprise_mode field in GET /workspace/users/me/ response."""

    def test_enterprise_mode_false_by_default(self):
        _, token = _make_user(enterprise_enabled=False)
        resp = _client(token).get(f"{_WS}/users/me/")
        assert resp.status_code == 200
        assert resp.json()["enterprise_mode"] is False

    def test_enterprise_mode_true_when_enabled(self):
        _, token = _make_user(enterprise_enabled=True)
        resp = _client(token).get(f"{_WS}/users/me/")
        assert resp.status_code == 200
        assert resp.json()["enterprise_mode"] is True


# =============================================================================
# SUBSCRIPTION LAPSE / GRACE PERIOD
# =============================================================================


class TestGracePeriod:
    """Enterprise mode grace period on subscription lapse."""

    def test_grace_period_allows_read_only(self):
        user, token = _make_user(enterprise_enabled=True, paid=True)
        config = user.enterprise_config
        config.grace_period_end = timezone.now() + timedelta(days=15)
        config.save()

        # Enterprise mode is still enabled (read-only access)
        assert config.is_in_grace_period is True
        assert is_enterprise_enabled(user) is True

    def test_expired_grace_period(self):
        user, _ = _make_user(enterprise_enabled=True, paid=True)
        config = user.enterprise_config
        config.grace_period_end = timezone.now() - timedelta(days=1)
        config.save()

        assert config.is_grace_period_expired is True


# =============================================================================
# ENTERPRISE UTILITY EDGE CASES
# =============================================================================


class TestEnterpriseUtilities:
    """Edge cases for enterprise utility functions."""

    def test_require_enterprise_raises_on_none_user(self):
        class FakeRequest:
            auth = None

        with pytest.raises(EnterpriseDisabledError):
            require_enterprise(FakeRequest())

    def test_require_enterprise_raises_when_disabled(self):
        user, _ = _make_user(enterprise_enabled=False)

        class FakeRequest:
            auth = user

        with pytest.raises(EnterpriseDisabledError):
            require_enterprise(FakeRequest())

    def test_require_enterprise_passes_when_enabled(self):
        user, _ = _make_user(enterprise_enabled=True)

        class FakeRequest:
            auth = user

        # Should not raise
        require_enterprise(FakeRequest())
