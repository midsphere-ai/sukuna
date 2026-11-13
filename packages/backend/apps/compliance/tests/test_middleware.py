"""Tests for the AuditMiddleware — request-level audit logging."""

import pytest
from django.test import RequestFactory

from apps.compliance.middleware import AuditMiddleware, _looks_like_id, get_client_ip
from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory


@pytest.fixture
def rf():
    """Django RequestFactory."""
    return RequestFactory()


@pytest.fixture
def dummy_response():
    """Minimal response-like object."""
    from django.http import HttpResponse

    return HttpResponse(status=200)


def _make_middleware(response=None):
    """Create an AuditMiddleware instance with a canned get_response."""
    from django.http import HttpResponse

    resp = response or HttpResponse(status=200)

    def get_response(request):
        return resp

    return AuditMiddleware(get_response)


# ---------------------------------------------------------------------------
# get_client_ip
# ---------------------------------------------------------------------------


class TestGetClientIP:
    def test_x_forwarded_for_single(self, rf):
        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4")
        assert get_client_ip(request) == "1.2.3.4"

    def test_x_forwarded_for_chain(self, rf):
        request = rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1, 192.168.1.1")
        assert get_client_ip(request) == "1.2.3.4"

    def test_remote_addr_fallback(self, rf):
        request = rf.get("/")
        # RequestFactory sets REMOTE_ADDR to 127.0.0.1 by default
        assert get_client_ip(request) == "127.0.0.1"

    def test_x_forwarded_for_with_spaces(self, rf):
        request = rf.get("/", HTTP_X_FORWARDED_FOR="  10.10.10.10 , 192.168.0.1")
        assert get_client_ip(request) == "10.10.10.10"


# ---------------------------------------------------------------------------
# _looks_like_id heuristic
# ---------------------------------------------------------------------------


class TestLooksLikeId:
    def test_numeric_id(self):
        assert _looks_like_id("42") is True
        assert _looks_like_id("123456789") is True

    def test_uuid_with_dashes(self):
        assert _looks_like_id("550e8400-e29b-41d4-a716-446655440000") is True

    def test_uuid_hex(self):
        assert _looks_like_id("550e8400e29b41d4a716446655440000") is True

    def test_short_id(self):
        assert _looks_like_id("abc12def34") is True

    def test_not_id_keywords(self):
        assert _looks_like_id("start") is False
        assert _looks_like_id("stream") is False
        assert _looks_like_id("export") is False
        assert _looks_like_id("me") is False

    def test_not_id_words(self):
        assert _looks_like_id("users") is False
        assert _looks_like_id("chat") is False
        assert _looks_like_id("completions") is False


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAuditMiddlewareLogging:
    """Verify that the middleware creates AuditLog entries for mutating API requests."""

    def test_post_creates_audit_entry(self, rf):
        user = UserFactory()
        middleware = _make_middleware()
        request = rf.post(
            "/api/v1/chat/completions/start", HTTP_X_FORWARDED_FOR="8.8.8.8"
        )
        request.user = user
        request.request_id = "req-123"

        middleware(request)

        assert AuditLog.objects.count() >= 1
        # Find the middleware entry (not the user creation signal entry)
        entry = AuditLog.objects.filter(
            request_id="req-123", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.action == "create"
        assert entry.actor_ip == "8.8.8.8"
        assert entry.actor_email == user.email
        assert entry.actor_id.int == user.pk
        assert entry.metadata["method"] == "POST"
        assert entry.metadata["path"] == "/api/v1/chat/completions/start"
        assert entry.metadata["status_code"] == 200

    def test_delete_creates_audit_entry(self, rf):
        user = UserFactory()
        middleware = _make_middleware()
        request = rf.delete("/api/v1/users/me", HTTP_X_FORWARDED_FOR="1.1.1.1")
        request.user = user
        request.request_id = "req-del"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-del", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.action == "delete"
        assert entry.metadata["method"] == "DELETE"

    def test_put_creates_update_action(self, rf):
        user = UserFactory()
        middleware = _make_middleware()
        request = rf.put(
            "/api/v1/spaces/abc-123/settings", content_type="application/json"
        )
        request.user = user
        request.request_id = "req-put"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-put", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.action == "update"

    def test_patch_creates_update_action(self, rf):
        user = UserFactory()
        middleware = _make_middleware()
        request = rf.patch("/api/v1/users/me", content_type="application/json")
        request.user = user
        request.request_id = "req-patch"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-patch", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.action == "update"

    def test_failed_request_logs_failure_action(self, rf):
        from django.http import HttpResponse

        middleware = _make_middleware(response=HttpResponse(status=403))
        user = UserFactory()
        request = rf.post("/api/v1/billing/subscribe", HTTP_X_FORWARDED_FOR="9.9.9.9")
        request.user = user
        request.request_id = "req-fail"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-fail", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.action == "post_failed"
        assert entry.metadata["status_code"] == 403

    def test_duration_tracked(self, rf):
        user = UserFactory()
        middleware = _make_middleware()
        request = rf.post("/api/v1/chat/completions/start")
        request.user = user
        request.request_id = "req-dur"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-dur", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert "duration_ms" in entry.metadata
        assert isinstance(entry.metadata["duration_ms"], int)


@pytest.mark.django_db
class TestAuditMiddlewareSkips:
    """Verify the middleware correctly skips non-auditable requests."""

    def test_get_not_logged(self, rf):
        middleware = _make_middleware()
        request = rf.get("/api/v1/users/me")
        request.user = UserFactory()
        request.request_id = "req-get"

        middleware(request)

        # Should not find a middleware audit entry for GET
        entry = AuditLog.objects.filter(
            request_id="req-get", metadata__has_key="method"
        ).first()
        assert entry is None

    def test_non_api_path_not_logged(self, rf):
        middleware = _make_middleware()
        request = rf.post("/admin/login/")
        request.user = UserFactory()
        request.request_id = "req-admin"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-admin", metadata__has_key="method"
        ).first()
        assert entry is None

    def test_static_path_not_logged(self, rf):
        middleware = _make_middleware()
        request = rf.post("/static/something.js")
        request.request_id = "req-static"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-static", metadata__has_key="method"
        ).first()
        assert entry is None

    def test_unauthenticated_request_still_logged(self, rf):
        """Unauthenticated mutating API requests should still be audited."""
        from django.contrib.auth.models import AnonymousUser

        middleware = _make_middleware()
        request = rf.post("/api/v1/auth/register", HTTP_X_FORWARDED_FOR="5.5.5.5")
        request.user = AnonymousUser()
        request.request_id = "req-anon"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-anon", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.actor_id is None
        assert entry.actor_email == ""
        assert entry.actor_ip == "5.5.5.5"


@pytest.mark.django_db
class TestAuditMiddlewareResourceParsing:
    """Verify URL path → resource_type/resource_id extraction."""

    def test_simple_path(self, rf):
        middleware = _make_middleware()
        user = UserFactory()
        request = rf.post("/api/v1/users/me")
        request.user = user
        request.request_id = "req-parse-1"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-parse-1", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.resource_type == "users.me"

    def test_path_with_uuid_id(self, rf):
        middleware = _make_middleware()
        user = UserFactory()
        uuid_id = "550e8400-e29b-41d4-a716-446655440000"
        request = rf.delete(f"/api/v1/spaces/{uuid_id}/files")
        request.user = user
        request.request_id = "req-parse-2"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-parse-2", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.resource_type == "spaces.files"
        assert entry.resource_id == uuid_id

    def test_nested_action_path(self, rf):
        middleware = _make_middleware()
        user = UserFactory()
        request = rf.post("/api/v1/chat/completions/start")
        request.user = user
        request.request_id = "req-parse-3"

        middleware(request)

        entry = AuditLog.objects.filter(
            request_id="req-parse-3", metadata__has_key="method"
        ).first()
        assert entry is not None
        assert entry.resource_type == "chat.completions.start"


@pytest.mark.django_db
class TestAuditMiddlewareNeverBreaksRequest:
    """The middleware must never cause a request to fail, even if logging errors out."""

    def test_middleware_swallows_exceptions(self, rf, monkeypatch):
        """If AuditLog.log raises, the response is still returned."""
        from django.http import HttpResponse

        resp = HttpResponse(status=201)
        middleware = _make_middleware(response=resp)

        # Make AuditLog.log raise
        monkeypatch.setattr(
            "apps.compliance.middleware.AuditLog.log",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        request = rf.post("/api/v1/test/endpoint")
        request.user = UserFactory()
        request.request_id = "req-err"

        result = middleware(request)
        assert result.status_code == 201
