"""MFA enforcement integration tests.

Verifies the SecurityPolicyMiddleware MFA check with various org
configurations: single org, multi-org, exempt paths, and MFA-enabled users.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import RequestFactory

from apps.compliance.security_middleware import (
    SecurityPolicyMiddleware,
    get_effective_policy,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.models import Organization, OrganizationMembership, OrganizationRole

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mw():
    return SecurityPolicyMiddleware(get_response=lambda r: MagicMock(status_code=200))


@pytest.fixture
def user():
    return UserFactory()


def _make_request(rf, path="/api/v1/spaces/", user=None):
    """Build a request with session for middleware testing."""
    import time

    request = rf.get(path)
    if user:
        request.user = user
    else:
        request.user = MagicMock(is_authenticated=False)
    session = SessionStore()
    session["_last_activity"] = time.time()
    session.create()
    request.session = session
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.META["HTTP_USER_AGENT"] = "TestAgent/1.0"
    return request


# ============================================================================
# MFA enforcement with single org
# ============================================================================


class TestMFASingleOrg:
    def test_mfa_not_required_passes(self, rf, mw, user):
        """User in org without MFA requirement passes through."""
        org = Organization.objects.create(name="No MFA", mfa_required=False)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _make_request(rf, user=user)
        result = mw.process_request(request)
        assert result is None

    def test_mfa_required_without_mfa_returns_403(self, rf, mw, user):
        """User in MFA-required org without MFA gets 403."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is not None
            assert result.status_code == 403
            body = json.loads(result.content)
            assert body["code"] == "mfa_required"

    def test_mfa_required_with_mfa_passes(self, rf, mw, user):
        """User in MFA-required org with MFA enabled passes through."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=True):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is None

    def test_403_body_contains_detail_message(self, rf, mw, user):
        """MFA 403 response contains actionable detail text."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            body = json.loads(result.content)
            assert "multi-factor authentication" in body["detail"].lower()


# ============================================================================
# MFA enforcement with exempt paths
# ============================================================================


class TestMFAExemptPaths:
    def test_mfa_setup_path_exempt(self, rf, mw, user):
        """User can access MFA setup even when MFA is required but not enabled."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, path="/accounts/2fa/totp/activate/", user=user)
            result = mw.process_request(request)
            assert result is None

    def test_auth_login_exempt(self, rf, mw, user):
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, path="/authentication/login/", user=user)
            result = mw.process_request(request)
            assert result is None

    def test_security_policy_endpoint_exempt(self, rf, mw, user):
        """User can check their security policy even without MFA."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(
                rf, path="/api/v1/compliance/security-policy", user=user
            )
            result = mw.process_request(request)
            assert result is None

    def test_logout_path_exempt(self, rf, mw, user):
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, path="/authentication/logout/", user=user)
            result = mw.process_request(request)
            assert result is None


# ============================================================================
# MFA enforcement with multi-org — most restrictive policy
# ============================================================================


class TestMFAMultiOrg:
    def test_any_org_requires_mfa_enforced(self, rf, mw, user):
        """If any org requires MFA, it's enforced even if others don't."""
        org_relaxed = Organization.objects.create(name="Relaxed", mfa_required=False)
        org_strict = Organization.objects.create(name="Strict", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org_relaxed, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_strict, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is not None
            assert result.status_code == 403

    def test_all_orgs_no_mfa_passes(self, rf, mw, user):
        """If no org requires MFA, user passes."""
        for i in range(3):
            org = Organization.objects.create(name=f"Org {i}", mfa_required=False)
            OrganizationMembership.objects.create(
                organization=org, user=user, role=OrganizationRole.MEMBER
            )

        request = _make_request(rf, user=user)
        result = mw.process_request(request)
        assert result is None

    def test_effective_policy_mfa_aggregation(self, user):
        """get_effective_policy returns mfa_required=True if any org requires it."""
        org1 = Organization.objects.create(name="No MFA", mfa_required=False)
        org2 = Organization.objects.create(name="MFA Org", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.MEMBER
        )

        mfa_required, _, _, _ = get_effective_policy(user)
        assert mfa_required is True


# ============================================================================
# MFA with allauth import error resilience
# ============================================================================


class TestMFAImportResilience:
    def test_allauth_mfa_import_error_skips_check(self, rf, mw, user):
        """If allauth.mfa is not importable, MFA check is gracefully skipped."""
        org = Organization.objects.create(name="MFA Corp", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        with patch.object(mw, "_check_mfa", return_value=None):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is None
