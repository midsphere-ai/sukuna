"""Session management integration tests.

Covers session timeout, concurrent session limits, oldest session eviction,
and sliding window reset of the _last_activity timestamp.
"""

import time
from unittest.mock import MagicMock

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from apps.compliance.models import UserSession
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


def _make_request(rf, user, last_activity=None, path="/api/v1/spaces/"):
    """Build a request with session and optional last_activity stamp."""
    request = rf.get(path)
    request.user = user
    session = SessionStore()
    if last_activity is not None:
        session["_last_activity"] = last_activity
    session.create()
    request.session = session
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.META["HTTP_USER_AGENT"] = "TestAgent/1.0"
    return request


# ============================================================================
# Session timeout
# ============================================================================


class TestSessionTimeout:
    @override_settings(SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES=60)
    def test_fresh_session_passes(self, rf, mw, user):
        """Session with recent activity passes through."""
        request = _make_request(rf, user, last_activity=time.time())
        result = mw.process_request(request)
        assert result is None

    @override_settings(SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES=60)
    def test_expired_session_returns_401(self, rf, mw, user):
        """Session idle beyond timeout returns 401."""
        expired = time.time() - (61 * 60)
        request = _make_request(rf, user, last_activity=expired)
        result = mw.process_request(request)
        assert result is not None
        assert result.status_code == 401

    def test_org_timeout_overrides_global(self, rf, mw, user):
        """Org-specific 30-minute timeout expires a 31-minute session."""
        org = Organization.objects.create(
            name="Timeout Org", session_timeout_minutes=30
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        expired = time.time() - (31 * 60)
        request = _make_request(rf, user, last_activity=expired)
        result = mw.process_request(request)
        assert result is not None
        assert result.status_code == 401

    def test_within_org_timeout_passes(self, rf, mw, user):
        """Session within 30-minute org timeout passes."""
        org = Organization.objects.create(
            name="Timeout Org", session_timeout_minutes=30
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        recent = time.time() - (15 * 60)
        request = _make_request(rf, user, last_activity=recent)
        result = mw.process_request(request)
        assert result is None

    def test_sliding_window_resets_on_activity(self, rf, mw, user):
        """Each request updates _last_activity (sliding window)."""
        request = _make_request(rf, user, last_activity=time.time() - 10)
        before = request.session.get("_last_activity")
        mw.process_request(request)
        after = request.session.get("_last_activity")
        assert after > before

    def test_new_session_gets_activity_stamp(self, rf, mw, user):
        """First request on a session stamps _last_activity."""
        request = _make_request(rf, user, last_activity=None)
        assert "_last_activity" not in request.session
        mw.process_request(request)
        assert "_last_activity" in request.session

    def test_expired_session_cleans_up_user_session(self, rf, mw, user):
        """Expired session's UserSession tracking record is deleted."""
        org = Organization.objects.create(
            name="Timeout Org", session_timeout_minutes=10
        )
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        expired = time.time() - (11 * 60)
        request = _make_request(rf, user, last_activity=expired)
        session_key = request.session.session_key
        UserSession.objects.create(user=user, session_key=session_key)

        mw.process_request(request)
        assert not UserSession.objects.filter(session_key=session_key).exists()


# ============================================================================
# Concurrent session limits
# ============================================================================


class TestConcurrentSessionLimits:
    def test_within_limit_no_eviction(self, rf, mw, user):
        """Sessions within the org limit are preserved."""
        org = Organization.objects.create(name="Session Org", max_concurrent_sessions=5)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        for _ in range(3):
            request = _make_request(rf, user, last_activity=time.time())
            mw.process_request(request)

        assert UserSession.objects.filter(user=user).count() == 3

    def test_exceeding_limit_evicts_oldest(self, rf, mw, user):
        """Creating sessions beyond the limit evicts the oldest."""
        org = Organization.objects.create(name="Session Org", max_concurrent_sessions=2)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        session_keys = []
        for _ in range(3):
            request = _make_request(rf, user, last_activity=time.time())
            mw.process_request(request)
            session_keys.append(request.session.session_key)

        remaining = UserSession.objects.filter(user=user)
        assert remaining.count() == 2
        remaining_keys = set(remaining.values_list("session_key", flat=True))
        assert session_keys[0] not in remaining_keys

    def test_eviction_removes_django_session(self, rf, mw, user):
        """Evicted sessions are also removed from Django's session store."""
        org = Organization.objects.create(name="Session Org", max_concurrent_sessions=2)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        sessions = []
        for _ in range(3):
            request = _make_request(rf, user, last_activity=time.time())
            mw.process_request(request)
            sessions.append(request.session.session_key)

        assert not Session.objects.filter(session_key=sessions[0]).exists()

    def test_most_restrictive_limit_wins(self, rf, mw, user):
        """With multiple orgs, the smallest session limit is enforced."""
        org_strict = Organization.objects.create(
            name="Strict", max_concurrent_sessions=2
        )
        org_relaxed = Organization.objects.create(
            name="Relaxed", max_concurrent_sessions=10
        )
        OrganizationMembership.objects.create(
            organization=org_strict, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_relaxed, user=user, role=OrganizationRole.MEMBER
        )

        for _ in range(4):
            request = _make_request(rf, user, last_activity=time.time())
            mw.process_request(request)

        assert UserSession.objects.filter(user=user).count() == 2

    def test_session_records_ip_and_user_agent(self, rf, mw, user):
        """UserSession stores the client IP and user agent."""
        request = _make_request(rf, user, last_activity=time.time())
        request.META["REMOTE_ADDR"] = "10.0.0.42"
        request.META["HTTP_USER_AGENT"] = "Mozilla/5.0"
        mw.process_request(request)

        record = UserSession.objects.get(user=user)
        assert record.ip_address == "10.0.0.42"
        assert record.user_agent == "Mozilla/5.0"

    def test_subsequent_request_updates_not_creates(self, rf, mw, user):
        """Repeated requests with the same session key don't create duplicates."""
        request = _make_request(rf, user, last_activity=time.time())
        mw.process_request(request)

        # Reuse same session
        request2 = rf.get("/api/v1/spaces/")
        request2.user = user
        request2.session = request.session
        request2.session["_last_activity"] = time.time()
        request2.META["REMOTE_ADDR"] = "127.0.0.1"
        request2.META["HTTP_USER_AGENT"] = "TestAgent/1.0"
        mw.process_request(request2)

        assert (
            UserSession.objects.filter(session_key=request.session.session_key).count()
            == 1
        )


# ============================================================================
# Effective policy — timeout and session aggregation
# ============================================================================


class TestEffectivePolicySessionIntegration:
    def test_most_restrictive_timeout(self, user):
        """Shortest timeout across orgs is returned."""
        org1 = Organization.objects.create(name="Short", session_timeout_minutes=30)
        org2 = Organization.objects.create(name="Long", session_timeout_minutes=120)
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.MEMBER
        )

        _, timeout, _, _ = get_effective_policy(user)
        assert timeout == 30

    def test_null_timeout_falls_back_to_global(self, user):
        """Org with null session_timeout_minutes defers to global default."""
        org = Organization.objects.create(name="Default", session_timeout_minutes=None)
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from django.conf import settings

        _, timeout, _, _ = get_effective_policy(user)
        assert timeout == settings.SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES

    def test_most_restrictive_max_sessions(self, user):
        """Smallest max_concurrent_sessions across orgs is returned."""
        org1 = Organization.objects.create(name="Strict", max_concurrent_sessions=2)
        org2 = Organization.objects.create(name="Relaxed", max_concurrent_sessions=10)
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.MEMBER
        )

        _, _, max_sessions, _ = get_effective_policy(user)
        assert max_sessions == 2
