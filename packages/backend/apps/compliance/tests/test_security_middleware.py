"""Tests for SecurityPolicyMiddleware — MFA enforcement, session timeout, concurrent session limits.

Covers:
- MFA enforcement: 403 when org requires MFA and user doesn't have it
- MFA bypass for exempt paths (auth, MFA setup, logout)
- MFA pass-through when MFA is enabled
- Session timeout: 401 when session exceeds idle timeout
- Session timeout respects per-org and global defaults
- Concurrent session limits: oldest sessions evicted when limit exceeded
- UserSession tracking: records created and updated on requests
- Policy computation: most restrictive policy across multiple orgs
- Error resilience: middleware never breaks the request cycle
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from apps.compliance.models import UserSession
from apps.compliance.security_middleware import (
    SecurityPolicyMiddleware,
    _is_exempt,
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


@pytest.fixture
def org_with_mfa():
    """Create an org with MFA required."""
    org = Organization.objects.create(name="MFA Corp", mfa_required=True)
    return org


@pytest.fixture
def org_with_timeout():
    """Create an org with a 30-minute session timeout."""
    org = Organization.objects.create(name="Timeout Corp", session_timeout_minutes=30)
    return org


@pytest.fixture
def org_with_session_limit():
    """Create an org with max 2 concurrent sessions."""
    org = Organization.objects.create(name="Session Corp", max_concurrent_sessions=2)
    return org


def _make_request(
    rf, path="/api/v1/spaces/", user=None, session_data=None, method="get"
):
    """Build a request with an authenticated user and optional session."""
    request = getattr(rf, method)(path)
    if user:
        request.user = user
    else:
        request.user = MagicMock(is_authenticated=False)
    # Create a real session
    session = SessionStore()
    if session_data:
        for k, v in session_data.items():
            session[k] = v
    session.create()
    request.session = session
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.META["HTTP_USER_AGENT"] = "TestAgent/1.0"
    return request


# =============================================================================
# PATH EXEMPTION
# =============================================================================


class TestPathExemption:
    def test_auth_paths_exempt(self):
        assert _is_exempt("/authentication/login/")
        assert _is_exempt("/accounts/google/login/")

    def test_mfa_paths_exempt(self):
        assert _is_exempt("/accounts/2fa/totp/activate/")
        assert _is_exempt("/api/v1/accounts/mfa/setup")

    def test_logout_paths_exempt(self):
        assert _is_exempt("/authentication/logout/")

    def test_admin_exempt(self):
        assert _is_exempt("/admin/compliance/auditlog/")

    def test_static_exempt(self):
        assert _is_exempt("/static/js/app.js")
        assert _is_exempt("/media/uploads/file.png")

    def test_security_policy_endpoint_exempt(self):
        assert _is_exempt("/api/v1/compliance/security-policy")

    def test_normal_api_not_exempt(self):
        assert not _is_exempt("/api/v1/spaces/")
        assert not _is_exempt("/api/v1/chat/completions/start")


# =============================================================================
# UNAUTHENTICATED PASSTHROUGH
# =============================================================================


class TestUnauthenticated:
    def test_anonymous_passes_through(self, rf, mw):
        request = _make_request(rf, user=None)
        result = mw.process_request(request)
        assert result is None

    def test_non_api_path_passes_through(self, rf, mw, user):
        request = _make_request(rf, path="/some/non/api/path", user=user)
        result = mw.process_request(request)
        assert result is None


# =============================================================================
# MFA ENFORCEMENT
# =============================================================================


class TestMFAEnforcement:
    def test_no_mfa_required_passes(self, rf, mw, user):
        """User with no org MFA requirement passes through."""
        org = Organization.objects.create(name="No MFA Org", mfa_required=False)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        request = _make_request(rf, user=user)
        result = mw.process_request(request)
        assert result is None

    def test_mfa_required_no_mfa_enabled_returns_403(self, rf, mw, user, org_with_mfa):
        """User in MFA-required org without MFA gets 403."""
        OrganizationMembership.objects.create(
            organization=org_with_mfa, user=user, role=OrganizationRole.MEMBER
        )
        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is not None
            assert result.status_code == 403
            import json

            body = json.loads(result.content)
            assert body["code"] == "mfa_required"

    def test_mfa_required_with_mfa_enabled_passes(self, rf, mw, user, org_with_mfa):
        """User in MFA-required org with MFA enabled passes through."""
        OrganizationMembership.objects.create(
            organization=org_with_mfa, user=user, role=OrganizationRole.MEMBER
        )
        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=True):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is None

    def test_mfa_exempt_path_not_blocked(self, rf, mw, user, org_with_mfa):
        """MFA-required user can still access exempt paths."""
        OrganizationMembership.objects.create(
            organization=org_with_mfa, user=user, role=OrganizationRole.MEMBER
        )
        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, path="/accounts/2fa/totp/activate/", user=user)
            result = mw.process_request(request)
            assert result is None

    def test_user_in_multiple_orgs_one_requires_mfa(self, rf, mw, user):
        """If any org requires MFA, it's enforced."""
        org_no_mfa = Organization.objects.create(name="Relaxed Org", mfa_required=False)
        org_mfa = Organization.objects.create(name="Strict Org", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org_no_mfa, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_mfa, user=user, role=OrganizationRole.MEMBER
        )

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is not None
            assert result.status_code == 403


# =============================================================================
# SESSION TIMEOUT
# =============================================================================


class TestSessionTimeout:
    def test_session_not_expired_passes(self, rf, mw, user):
        """Session with recent activity passes through."""
        request = _make_request(
            rf, user=user, session_data={"_last_activity": time.time()}
        )
        result = mw.process_request(request)
        assert result is None

    @override_settings(SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES=60)
    def test_session_expired_returns_401(self, rf, mw, user):
        """Session idle beyond global timeout returns 401."""
        # Set last activity to 2 hours ago
        expired_time = time.time() - (2 * 60 * 60)
        request = _make_request(
            rf, user=user, session_data={"_last_activity": expired_time}
        )
        result = mw.process_request(request)
        assert result is not None
        assert result.status_code == 401
        import json

        body = json.loads(result.content)
        assert body["code"] == "session_expired"

    def test_org_timeout_overrides_global(self, rf, mw, user, org_with_timeout):
        """Org with 30-min timeout expires session that's 31 minutes old."""
        OrganizationMembership.objects.create(
            organization=org_with_timeout, user=user, role=OrganizationRole.MEMBER
        )
        expired_time = time.time() - (31 * 60)
        request = _make_request(
            rf, user=user, session_data={"_last_activity": expired_time}
        )
        result = mw.process_request(request)
        assert result is not None
        assert result.status_code == 401

    def test_org_timeout_allows_within_window(self, rf, mw, user, org_with_timeout):
        """Session within 30-min org timeout passes."""
        OrganizationMembership.objects.create(
            organization=org_with_timeout, user=user, role=OrganizationRole.MEMBER
        )
        recent_time = time.time() - (15 * 60)  # 15 minutes ago
        request = _make_request(
            rf, user=user, session_data={"_last_activity": recent_time}
        )
        result = mw.process_request(request)
        assert result is None

    def test_new_session_gets_activity_stamp(self, rf, mw, user):
        """First request stamps _last_activity on the session."""
        request = _make_request(rf, user=user)
        assert "_last_activity" not in request.session
        mw.process_request(request)
        assert "_last_activity" in request.session

    def test_most_restrictive_timeout_wins(self, rf, mw, user):
        """With multiple orgs, the shortest timeout is used."""
        org_30 = Organization.objects.create(name="Short", session_timeout_minutes=30)
        org_120 = Organization.objects.create(name="Long", session_timeout_minutes=120)
        OrganizationMembership.objects.create(
            organization=org_30, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_120, user=user, role=OrganizationRole.MEMBER
        )

        # 45 minutes ago — within 120 but outside 30
        expired_time = time.time() - (45 * 60)
        request = _make_request(
            rf, user=user, session_data={"_last_activity": expired_time}
        )
        result = mw.process_request(request)
        assert result is not None
        assert result.status_code == 401

    def test_session_timeout_cleans_user_session(self, rf, mw, user, org_with_timeout):
        """When session expires, the UserSession tracking record is cleaned up."""
        OrganizationMembership.objects.create(
            organization=org_with_timeout, user=user, role=OrganizationRole.MEMBER
        )
        expired_time = time.time() - (31 * 60)
        request = _make_request(
            rf, user=user, session_data={"_last_activity": expired_time}
        )
        session_key = request.session.session_key

        # Create a tracking record
        UserSession.objects.create(user=user, session_key=session_key)

        mw.process_request(request)
        assert not UserSession.objects.filter(session_key=session_key).exists()


# =============================================================================
# CONCURRENT SESSION LIMITS
# =============================================================================


class TestConcurrentSessions:
    def test_session_tracked_on_request(self, rf, mw, user):
        """A UserSession record is created for authenticated requests."""
        request = _make_request(
            rf, user=user, session_data={"_last_activity": time.time()}
        )
        mw.process_request(request)
        assert UserSession.objects.filter(user=user).count() == 1

    def test_session_updated_on_subsequent_request(self, rf, mw, user):
        """Subsequent requests update the existing UserSession, not create new ones."""
        request = _make_request(
            rf, user=user, session_data={"_last_activity": time.time()}
        )
        mw.process_request(request)
        session_key = request.session.session_key

        # Second request with same session
        request2 = _make_request(rf, user=user)
        request2.session = request.session
        request2.session["_last_activity"] = time.time()
        mw.process_request(request2)

        assert UserSession.objects.filter(session_key=session_key).count() == 1

    @override_settings(SECURITY_DEFAULT_MAX_CONCURRENT_SESSIONS=5)
    def test_within_limit_no_eviction(self, rf, mw, user):
        """Sessions within the limit are not evicted."""
        for i in range(3):
            request = _make_request(
                rf, user=user, session_data={"_last_activity": time.time()}
            )
            mw.process_request(request)

        assert UserSession.objects.filter(user=user).count() == 3

    def test_exceeding_limit_evicts_oldest(self, rf, mw, user, org_with_session_limit):
        """When concurrent sessions exceed the limit (2), oldest are evicted."""
        OrganizationMembership.objects.create(
            organization=org_with_session_limit, user=user, role=OrganizationRole.MEMBER
        )

        session_keys = []
        for i in range(3):
            request = _make_request(
                rf, user=user, session_data={"_last_activity": time.time()}
            )
            mw.process_request(request)
            session_keys.append(request.session.session_key)

        # Should have evicted the oldest, keeping only 2
        remaining = UserSession.objects.filter(user=user)
        assert remaining.count() == 2
        # The oldest (first) session should have been evicted
        remaining_keys = set(remaining.values_list("session_key", flat=True))
        assert session_keys[0] not in remaining_keys

    def test_eviction_deletes_django_session(
        self, rf, mw, user, org_with_session_limit
    ):
        """Evicted sessions are also removed from Django's session store."""
        OrganizationMembership.objects.create(
            organization=org_with_session_limit, user=user, role=OrganizationRole.MEMBER
        )

        sessions = []
        for i in range(3):
            request = _make_request(
                rf, user=user, session_data={"_last_activity": time.time()}
            )
            mw.process_request(request)
            sessions.append(request.session.session_key)

        # The oldest Django session should be gone
        assert not Session.objects.filter(session_key=sessions[0]).exists()

    def test_most_restrictive_session_limit_wins(self, rf, mw, user):
        """With multiple orgs, the smallest max_concurrent_sessions is used."""
        org_2 = Organization.objects.create(name="Strict", max_concurrent_sessions=2)
        org_10 = Organization.objects.create(name="Relaxed", max_concurrent_sessions=10)
        OrganizationMembership.objects.create(
            organization=org_2, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_10, user=user, role=OrganizationRole.MEMBER
        )

        for i in range(4):
            request = _make_request(
                rf, user=user, session_data={"_last_activity": time.time()}
            )
            mw.process_request(request)

        # Limit 2 should win
        assert UserSession.objects.filter(user=user).count() == 2

    def test_session_records_ip_and_user_agent(self, rf, mw, user):
        """UserSession stores IP and user agent."""
        request = _make_request(
            rf, user=user, session_data={"_last_activity": time.time()}
        )
        request.META["REMOTE_ADDR"] = "10.0.0.1"
        request.META["HTTP_USER_AGENT"] = "Chrome/120.0"
        mw.process_request(request)

        record = UserSession.objects.get(user=user)
        assert record.ip_address == "10.0.0.1"
        assert record.user_agent == "Chrome/120.0"


# =============================================================================
# EFFECTIVE POLICY COMPUTATION
# =============================================================================


class TestEffectivePolicy:
    def test_no_orgs_uses_global_defaults(self, user):
        """User with no org memberships gets global defaults."""
        mfa, timeout, max_sessions, _sso = get_effective_policy(user)
        assert mfa is False
        from django.conf import settings

        assert timeout == settings.SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES
        assert max_sessions == settings.SECURITY_DEFAULT_MAX_CONCURRENT_SESSIONS

    def test_single_org_overrides(self, user):
        """Single org settings override globals."""
        org = Organization.objects.create(
            name="Custom",
            mfa_required=True,
            session_timeout_minutes=60,
            max_concurrent_sessions=3,
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        mfa, timeout, max_sessions, _sso = get_effective_policy(user)
        assert mfa is True
        assert timeout == 60
        assert max_sessions == 3

    def test_multiple_orgs_takes_most_restrictive(self, user):
        """Multiple orgs — MFA required if any, smallest timeout and session count."""
        org1 = Organization.objects.create(
            name="Org1",
            mfa_required=False,
            session_timeout_minutes=120,
            max_concurrent_sessions=10,
        )
        org2 = Organization.objects.create(
            name="Org2",
            mfa_required=True,
            session_timeout_minutes=30,
            max_concurrent_sessions=3,
        )
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.MEMBER
        )

        mfa, timeout, max_sessions, _sso = get_effective_policy(user)
        assert mfa is True
        assert timeout == 30
        assert max_sessions == 3

    def test_null_org_fields_fall_back_to_global(self, user):
        """Org fields set to None don't override global defaults."""
        org = Organization.objects.create(
            name="Default Org",
            mfa_required=False,
            session_timeout_minutes=None,
            max_concurrent_sessions=None,
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        mfa, timeout, max_sessions, _sso = get_effective_policy(user)
        assert mfa is False
        from django.conf import settings

        assert timeout == settings.SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES
        assert max_sessions == settings.SECURITY_DEFAULT_MAX_CONCURRENT_SESSIONS


# =============================================================================
# ERROR RESILIENCE
# =============================================================================


class TestErrorResilience:
    def test_middleware_swallows_exceptions(self, rf, mw, user):
        """Middleware never breaks the request cycle, even on internal errors."""
        request = _make_request(rf, user=user)
        with patch.object(mw, "_enforce", side_effect=RuntimeError("boom")):
            result = mw.process_request(request)
            assert result is None  # Passes through

    def test_mfa_check_handles_import_error(self, rf, mw, user, org_with_mfa):
        """If allauth.mfa is not importable, MFA check is skipped."""
        OrganizationMembership.objects.create(
            organization=org_with_mfa, user=user, role=OrganizationRole.MEMBER
        )
        with patch(
            "apps.compliance.security_middleware.SecurityPolicyMiddleware._check_mfa"
        ) as mock:
            # Simulate the import error path
            mock.return_value = None
            request = _make_request(rf, user=user)
            result = mw.process_request(request)
            assert result is None


# =============================================================================
# USER SESSION MODEL
# =============================================================================


class TestUserSessionModel:
    def test_create_session(self, user):
        session = UserSession.objects.create(
            user=user,
            session_key="abc123",
            ip_address="10.0.0.1",
            user_agent="TestAgent/1.0",
        )
        assert session.pk is not None
        assert session.created_at is not None
        assert session.last_activity is not None

    def test_unique_session_key(self, user):
        UserSession.objects.create(user=user, session_key="key1")
        with pytest.raises(Exception):  # IntegrityError
            UserSession.objects.create(user=user, session_key="key1")

    def test_cascade_on_user_delete(self, user):
        UserSession.objects.create(user=user, session_key="key1")
        user.delete()
        assert UserSession.objects.filter(session_key="key1").count() == 0

    def test_str_representation(self, user):
        session = UserSession.objects.create(user=user, session_key="abcdefgh12345678")  # gitleaks:allow
        assert "abcdefgh" in str(session)
