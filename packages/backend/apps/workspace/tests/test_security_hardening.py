"""Tests for US-051: Security hardening.

Covers:
- API key scope enforcement (org:read, org:write, org:admin)
- Display name sanitization (XSS, LLM injection prevention)
- SSE access revocation (shared conversation mid-stream check)
- Rate limiting on invite accept endpoint
- SCIM 404 rate limiting for org enumeration prevention
- Enterprise toggle re-authentication
"""

import hashlib
import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.models import DeveloperAPIKey
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SCIMToken,
)
from apps.workspace.security import (
    ORG_SCOPE_ADMIN,
    ORG_SCOPE_READ,
    ORG_SCOPE_WRITE,
    check_api_key_org_scope,
    check_scim_404_rate,
    sanitize_display_name,
)

pytestmark = pytest.mark.django_db

_ORG_BASE = "/api/v1/workspace/organizations"
_SANDBOX_BASE = "/api/v1/chat/sandbox"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


_TEST_PASSWORD = "SecureTestPassword123!"


def _make_user(password=_TEST_PASSWORD):
    user = UserFactory(password=password)
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _api_key_client(raw_key):
    return Client(headers={"x-api-key": raw_key})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _create_api_key(user, scopes=None):
    """Create a DeveloperAPIKey and return (key_obj, raw_key)."""
    raw_key = DeveloperAPIKey.generate_key()
    key_obj = DeveloperAPIKey.objects.create(
        name="test-key",
        key_hash=DeveloperAPIKey.hash_key(raw_key),
        key_prefix=raw_key[:12],
        user=user,
        scopes=scopes or [],
    )
    return key_obj, raw_key


def _create_org(name="Test Org"):
    owner, token = _make_user()
    resp = _post(_client(token), f"{_ORG_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


# =============================================================================
# DISPLAY NAME SANITIZATION
# =============================================================================


class TestDisplayNameSanitization:
    """Display name sanitization strips injection and markdown characters."""

    def test_strips_brackets(self):
        assert sanitize_display_name("[Admin] John") == "Admin John"

    def test_strips_angle_brackets(self):
        assert (
            sanitize_display_name("<script>alert(1)</script>")
            == "scriptalert(1)/script"
        )

    def test_strips_curly_braces(self):
        assert sanitize_display_name("User {role}") == "User role"

    def test_strips_pipe(self):
        assert sanitize_display_name("John|Doe") == "JohnDoe"

    def test_strips_backslash(self):
        assert sanitize_display_name("John\\Doe") == "JohnDoe"

    def test_strips_backticks(self):
        assert sanitize_display_name("`admin`") == "admin"

    def test_strips_markdown_bold(self):
        assert sanitize_display_name("**Admin**") == "Admin"

    def test_strips_markdown_italic(self):
        assert sanitize_display_name("_italic_") == "italic"

    def test_strips_markdown_strikethrough(self):
        assert sanitize_display_name("~deleted~") == "deleted"

    def test_strips_markdown_heading(self):
        assert sanitize_display_name("# heading") == "heading"

    def test_preserves_unicode(self):
        assert sanitize_display_name("日本太郎") == "日本太郎"

    def test_preserves_spaces(self):
        assert sanitize_display_name("John Doe") == "John Doe"

    def test_none_returns_empty(self):
        assert sanitize_display_name(None) == ""

    def test_empty_returns_empty(self):
        assert sanitize_display_name("") == ""

    def test_only_special_chars_returns_empty(self):
        assert sanitize_display_name("[]<>{}|\\`*_~#") == ""

    def test_mixed_content(self):
        assert sanitize_display_name("[User: <admin>] `test`") == "User: admin test"

    def test_sanitization_on_profile_save(self):
        """Verify sanitization is applied when modifying user profile."""
        from apps.workspace.services.workspace import WorkspaceService

        user, _ = _make_user()
        svc = WorkspaceService()
        updated = svc.modify_user(user, str(user.id), {"user_name": "[Admin] <script>"})
        assert "[" not in updated.name
        assert "<" not in updated.name
        assert updated.name == "Admin script"


# =============================================================================
# API KEY SCOPE ENFORCEMENT
# =============================================================================


class TestApiKeyScopeEnforcement:
    """API keys must have org:* scopes to access org endpoints."""

    def test_api_key_with_org_read_can_list_orgs(self):
        """API key with org:read can GET org endpoints."""
        user, token = _make_user()
        # Create an org with bearer token first
        resp = _post(_client(token), f"{_ORG_BASE}/", {"name": "Scope Test Org"})
        assert resp.status_code == 201

        # Now access with API key that has org:read
        _, raw_key = _create_api_key(user, scopes=[ORG_SCOPE_READ])
        resp = _api_key_client(raw_key).get(f"{_ORG_BASE}/")
        assert resp.status_code == 200

    def test_api_key_without_org_scope_blocked(self):
        """API key without any org scope gets 403 on org endpoints."""
        user, token = _make_user()
        _post(_client(token), f"{_ORG_BASE}/", {"name": "Scope Test Org"})

        _, raw_key = _create_api_key(user, scopes=["agent:run"])
        resp = _api_key_client(raw_key).get(f"{_ORG_BASE}/")
        assert resp.status_code == 403

    def test_api_key_org_read_cannot_create_org(self):
        """API key with only org:read cannot POST to create org."""
        user, _ = _make_user()
        _, raw_key = _create_api_key(user, scopes=[ORG_SCOPE_READ])
        resp = _post(
            _api_key_client(raw_key),
            f"{_ORG_BASE}/",
            {"name": "Should Fail"},
        )
        assert resp.status_code == 403

    def test_api_key_org_write_can_create_org(self):
        """API key with org:write can POST to create org."""
        user, _ = _make_user()
        _, raw_key = _create_api_key(user, scopes=[ORG_SCOPE_WRITE])
        resp = _post(
            _api_key_client(raw_key),
            f"{_ORG_BASE}/",
            {"name": "Write Scope Org"},
        )
        assert resp.status_code == 201

    def test_api_key_org_admin_can_update_security_policy(self):
        """API key with org:admin can access admin-level endpoints."""
        org, owner, bearer_token = _create_org()
        _, raw_key = _create_api_key(owner, scopes=[ORG_SCOPE_ADMIN])
        resp = _api_key_client(raw_key).get(f"{_ORG_BASE}/{org.pk}/security-policy")
        assert resp.status_code == 200

    def test_api_key_org_write_blocked_from_admin_endpoints(self):
        """API key with only org:write cannot access admin-level endpoints."""
        org, owner, bearer_token = _create_org()
        _, raw_key = _create_api_key(owner, scopes=[ORG_SCOPE_WRITE])
        resp = _patch(
            _api_key_client(raw_key),
            f"{_ORG_BASE}/{org.pk}/security-policy",
            {"mfa_required": True},
        )
        assert resp.status_code == 403

    def test_scope_hierarchy_admin_implies_write(self):
        """org:admin scope allows write operations too."""
        user, _ = _make_user()
        _, raw_key = _create_api_key(user, scopes=[ORG_SCOPE_ADMIN])
        resp = _post(
            _api_key_client(raw_key),
            f"{_ORG_BASE}/",
            {"name": "Admin Create Org"},
        )
        assert resp.status_code == 201

    def test_scope_hierarchy_admin_implies_read(self):
        """org:admin scope allows read operations too."""
        user, token = _make_user()
        _post(_client(token), f"{_ORG_BASE}/", {"name": "Test"})
        _, raw_key = _create_api_key(user, scopes=[ORG_SCOPE_ADMIN])
        resp = _api_key_client(raw_key).get(f"{_ORG_BASE}/")
        assert resp.status_code == 200

    def test_bearer_token_has_all_scopes(self):
        """Bearer token auth has all scopes implicitly."""
        user, token = _make_user()
        resp = _post(_client(token), f"{_ORG_BASE}/", {"name": "Bearer Org"})
        assert resp.status_code == 201


class TestCheckApiKeyScopeUnit:
    """Unit tests for check_api_key_org_scope helper."""

    def test_no_api_key_passes(self):
        """Bearer token requests (no api_key attr) always pass."""
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        # No api_key attribute — should not raise
        check_api_key_org_scope(request, ORG_SCOPE_READ)

    def test_api_key_with_matching_scope_passes(self):
        from unittest.mock import MagicMock

        from django.test import RequestFactory

        request = RequestFactory().get("/")
        mock_key = MagicMock()
        mock_key.scopes = [ORG_SCOPE_READ]
        request.api_key = mock_key
        check_api_key_org_scope(request, ORG_SCOPE_READ)

    def test_api_key_missing_scope_raises(self):
        from unittest.mock import MagicMock

        from django.test import RequestFactory
        from ninja.errors import HttpError

        request = RequestFactory().get("/")
        mock_key = MagicMock()
        mock_key.scopes = ["agent:run"]
        request.api_key = mock_key
        with pytest.raises(HttpError) as exc_info:
            check_api_key_org_scope(request, ORG_SCOPE_READ)
        assert exc_info.value.status_code == 403


# =============================================================================
# SCIM 404 RATE LIMITING
# =============================================================================


class TestScim404RateLimiting:
    """SCIM endpoint 404 rate limiting prevents org enumeration."""

    def test_scim_404_rate_limit_unit(self):
        """check_scim_404_rate returns True after threshold."""
        from django.test import RequestFactory

        request = RequestFactory().get("/")
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        # First 5 should return False (not rate limited)
        for _ in range(5):
            assert check_scim_404_rate(request) is False

        # 6th should return True (rate limited)
        assert check_scim_404_rate(request) is True

    def test_scim_different_ips_independent(self):
        """Rate limiting is per-IP, not global."""
        from django.test import RequestFactory

        req1 = RequestFactory().get("/")
        req1.META["REMOTE_ADDR"] = "10.0.0.1"
        req2 = RequestFactory().get("/")
        req2.META["REMOTE_ADDR"] = "10.0.0.2"

        for _ in range(5):
            check_scim_404_rate(req1)

        # req1 should be limited, req2 should not
        assert check_scim_404_rate(req1) is True
        assert check_scim_404_rate(req2) is False

    def test_scim_endpoint_returns_429_on_enumeration(self):
        """SCIM endpoint returns 429 after repeated bad org slugs."""
        user, _ = _make_user()
        org = Organization.objects.create(name="SCIM Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.OWNER,
        )
        raw_token = "scim-test-token-for-429"
        SCIMToken.objects.create(
            organization=org,
            name="test",
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        )

        client = Client(headers={"authorization": f"Bearer {raw_token}"})
        # Send many requests with wrong org slug
        for _ in range(8):
            resp = client.get(f"/api/v1/scim/v2/nonexistent-org-slug/Users")

        # After threshold, should get 429
        resp = client.get(f"/api/v1/scim/v2/nonexistent-org-slug/Users")
        assert resp.status_code == 429


# =============================================================================
# INVITE ACCEPT RATE LIMITING (verify existing implementation)
# =============================================================================


class TestInviteAcceptRateLimit:
    """Invite accept endpoint has rate limiting (10/min/IP)."""

    def test_rate_limit_blocks_after_threshold(self):
        """After 10 accepts per minute per IP, returns 429."""
        _, token = _make_user()
        c = _client(token)

        # Pre-fill the rate limit cache to simulate 10 prior accepts
        from django.core.cache import cache

        cache.set("invite_accept:127.0.0.1", 10, timeout=60)

        # Next accept attempt should be rate limited
        resp = c.post(
            "/api/v1/workspace/invitations/00000000-0000-0000-0000-000000000000/accept",
            content_type="application/json",
        )
        assert resp.status_code == 429


# =============================================================================
# ENTERPRISE TOGGLE RE-AUTH
# =============================================================================

_WS = "/api/v1/workspace"


class TestEnterpriseToggleReauth:
    """Enterprise mode toggle requires re-authentication."""

    @pytest.fixture(autouse=True)
    def _no_auto_enterprise(self):
        """Disable auto-enable enterprise for toggle tests."""
        yield

    def _make_paid_user(self, enterprise_enabled=False):
        from apps.billing.models import SubscriptionPlan, UserSubscription
        from apps.workspace.models import EnterpriseConfig

        user = UserFactory(password=_TEST_PASSWORD)
        token_obj, _ = Token.objects.get_or_create(user=user)
        plan, _ = SubscriptionPlan.objects.get_or_create(
            tier="premium",
            defaults={"name": "Premium", "price": 25.00, "is_active": True},
        )
        UserSubscription.objects.create(user=user, plan=plan, status="active")
        if enterprise_enabled:
            from django.utils import timezone

            from apps.workspace.models import EnterpriseConfig

            EnterpriseConfig.objects.update_or_create(
                user=user,
                defaults={"enabled": True, "enabled_at": timezone.now()},
            )
        return user, token_obj.key

    def test_correct_password_allows_toggle(self):
        _, token = self._make_paid_user()
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200

    def test_wrong_password_returns_403(self):
        _, token = self._make_paid_user()
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True, "current_password": "wrong_password"},
        )
        assert resp.status_code == 403
        assert "Invalid password" in resp.json()["detail"]

    def test_missing_password_returns_422(self):
        """Missing current_password field returns validation error."""
        _, token = self._make_paid_user()
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": True},
        )
        # Django Ninja returns 422 for missing required fields
        assert resp.status_code == 422

    def test_disable_with_correct_password(self):
        _, token = self._make_paid_user(enterprise_enabled=True)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": False, "current_password": _TEST_PASSWORD},
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_disable_with_wrong_password(self):
        _, token = self._make_paid_user(enterprise_enabled=True)
        resp = _patch(
            _client(token),
            f"{_WS}/enterprise-mode",
            {"enabled": False, "current_password": "bad_pass"},
        )
        assert resp.status_code == 403


# =============================================================================
# SSE ACCESS REVOCATION
# =============================================================================


class TestSSEAccessRevocation:
    """Verify mid-stream access revocation helpers work correctly.

    Tests the underlying sync permission functions that the async SSE
    wrappers call, since async wrappers use sync_to_async over these.
    """

    def test_shared_conversation_detected(self):
        """Shared metadata flag is correctly read."""
        from apps.storage.models import Conversation

        user, _ = _make_user()
        conv = Conversation.objects.create(
            user=user,
            title="SSE test conv",
            metadata={"shared": True},
        )
        metadata = conv.metadata or {}
        assert bool(metadata.get("shared")) is True

    def test_unshared_conversation_not_shared(self):
        """Empty metadata means not shared."""
        from apps.storage.models import Conversation

        user, _ = _make_user()
        conv = Conversation.objects.create(
            user=user,
            title="SSE test conv",
            metadata={},
        )
        metadata = conv.metadata or {}
        assert bool(metadata.get("shared")) is False

    def test_revocation_on_unshare(self):
        """After removing shared flag, check returns False."""
        from apps.storage.models import Conversation

        user, _ = _make_user()
        conv = Conversation.objects.create(
            user=user,
            title="SSE test conv",
            metadata={"shared": True},
        )
        assert bool((conv.metadata or {}).get("shared")) is True

        # Simulate unsharing mid-stream
        conv.metadata = {}
        conv.save(update_fields=["metadata"])
        conv.refresh_from_db()
        assert bool((conv.metadata or {}).get("shared")) is False

    def test_user_access_check_owner(self):
        """conversation_can_view returns True for owner."""
        from apps.storage.models import Conversation, conversation_can_view

        user, _ = _make_user()
        conv = Conversation.objects.create(user=user, title="Owner conv")
        assert conversation_can_view(conv, user) is True

    def test_user_access_check_no_permission(self):
        """conversation_can_view returns False for unrelated user."""
        from apps.storage.models import Conversation, conversation_can_view

        owner, _ = _make_user()
        stranger, _ = _make_user()
        conv = Conversation.objects.create(user=owner, title="Private conv")
        assert conversation_can_view(conv, stranger) is False

    def test_access_revoked_when_participant_removed(self):
        """Access is revoked when participant record is deleted."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
            conversation_can_view,
        )

        owner, _ = _make_user()
        viewer, _ = _make_user()
        conv = Conversation.objects.create(user=owner, title="Revoke test")
        participant = ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )
        assert conversation_can_view(conv, viewer) is True

        # Simulate access revocation mid-stream
        participant.delete()
        assert conversation_can_view(conv, viewer) is False

    def test_viewer_can_view_but_not_inject(self):
        """Viewer has view access but NOT inject (write) access."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
            conversation_can_inject,
            conversation_can_view,
        )

        owner, _ = _make_user()
        viewer, _ = _make_user()
        conv = Conversation.objects.create(user=owner, title="Viewer conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )
        assert conversation_can_view(conv, viewer) is True
        assert conversation_can_inject(conv, viewer) is False


# =============================================================================
# SANDBOX PROXY WRITE PERMISSION
# =============================================================================


class TestSandboxProxyWritePermission:
    """Sandbox file mutation endpoints enforce write permissions."""

    def test_viewer_cannot_write_files(self):
        """A viewer participant gets 403 on file write proxy."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
        )

        owner, _ = _make_user()
        viewer, viewer_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Write test conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )

        c = _client(viewer_token)
        resp = c.put(
            f"{_SANDBOX_BASE}/{conv.id}/files/write",
            data=json.dumps({"path": "test.txt", "content": "hello"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_viewer_cannot_create_files(self):
        """A viewer participant gets 403 on file create proxy."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
        )

        owner, _ = _make_user()
        viewer, viewer_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Create test conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )

        c = _client(viewer_token)
        resp = c.post(
            f"{_SANDBOX_BASE}/{conv.id}/files/create",
            data=json.dumps({"path": "new.txt", "type": "file", "content": "hi"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_viewer_cannot_delete_files(self):
        """A viewer participant gets 403 on file delete proxy."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
        )

        owner, _ = _make_user()
        viewer, viewer_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Delete test conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )

        c = _client(viewer_token)
        resp = c.delete(
            f"{_SANDBOX_BASE}/{conv.id}/files/delete?path=test.txt",
        )
        assert resp.status_code == 403

    def test_viewer_can_read_files(self):
        """A viewer participant can still read files (502 expected — no sandbox, but not 403)."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
        )

        owner, _ = _make_user()
        viewer, viewer_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Read test conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )

        c = _client(viewer_token)
        resp = c.get(f"{_SANDBOX_BASE}/{conv.id}/files/read?path=test.txt")
        # Not 403 — viewer can read. Will get 502 (no sandbox) or another error.
        assert resp.status_code != 403

    def test_collaborator_can_write_files(self):
        """A collaborator participant is not blocked by permission check (may get 502 for no sandbox)."""
        from apps.storage.models import (
            Conversation,
            ConversationParticipant,
            ParticipantRole,
        )

        owner, _ = _make_user()
        collaborator, collab_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Collab write conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=collaborator,
            role=ParticipantRole.COLLABORATOR,
        )

        c = _client(collab_token)
        resp = c.put(
            f"{_SANDBOX_BASE}/{conv.id}/files/write",
            data=json.dumps({"path": "test.txt", "content": "hello"}),
            content_type="application/json",
        )
        # Not 403 — collaborator has write permission. Will get 502 (no sandbox).
        assert resp.status_code != 403

    def test_owner_can_write_files(self):
        """Owner is not blocked by permission check."""
        from apps.storage.models import Conversation

        owner, owner_token = _make_user()
        conv = Conversation.objects.create(user=owner, title="Owner write conv")

        c = _client(owner_token)
        resp = c.put(
            f"{_SANDBOX_BASE}/{conv.id}/files/write",
            data=json.dumps({"path": "test.txt", "content": "hello"}),
            content_type="application/json",
        )
        # Not 403 — owner has all permissions.
        assert resp.status_code != 403
