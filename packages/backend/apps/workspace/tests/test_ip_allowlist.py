"""Tests for IP allowlist feature: model, API endpoints, and enforcement middleware.

Covers:
- CIDR validation (IPv4, IPv6, /32, /24, /16)
- API: POST (add), GET (list), DELETE (remove) with RBAC
- Middleware enforcement: blocking, multi-org isolation, empty allowlist
- X-Forwarded-For handling
- Self-lockout warning (your_ip in response)
- AuditLog entries for add/remove/blocked
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.ip_middleware import (
    get_client_ip,
    ip_in_cidrs,
)
from apps.workspace.models import (
    IPAllowlistEntry,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear rate-limit cache between tests."""
    cache.clear()
    yield
    cache.clear()


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _delete(client, path, data=None):
    kwargs = {"content_type": "application/json"}
    if data is not None:
        kwargs["data"] = json.dumps(data)
    return client.delete(path, **kwargs)


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


# ── Unit tests: CIDR matching ─────────────────────────────────────────────


class TestCIDRMatching:
    def test_ipv4_in_range(self):
        assert ip_in_cidrs("10.0.0.5", ["10.0.0.0/24"]) is True

    def test_ipv4_not_in_range(self):
        assert ip_in_cidrs("10.0.1.5", ["10.0.0.0/24"]) is False

    def test_ipv4_exact_host(self):
        assert ip_in_cidrs("192.168.1.1", ["192.168.1.1/32"]) is True
        assert ip_in_cidrs("192.168.1.2", ["192.168.1.1/32"]) is False

    def test_ipv4_broad_range(self):
        assert ip_in_cidrs("10.255.255.255", ["10.0.0.0/8"]) is True
        assert ip_in_cidrs("11.0.0.1", ["10.0.0.0/8"]) is False

    def test_ipv4_slash_16(self):
        assert ip_in_cidrs("172.16.5.100", ["172.16.0.0/16"]) is True
        assert ip_in_cidrs("172.17.0.1", ["172.16.0.0/16"]) is False

    def test_ipv6_in_range(self):
        assert ip_in_cidrs("2001:db8::1", ["2001:db8::/32"]) is True

    def test_ipv6_not_in_range(self):
        assert ip_in_cidrs("2001:db9::1", ["2001:db8::/32"]) is False

    def test_ipv6_exact_host(self):
        assert ip_in_cidrs("::1", ["::1/128"]) is True
        assert ip_in_cidrs("::2", ["::1/128"]) is False

    def test_multiple_cidrs(self):
        cidrs = ["10.0.0.0/24", "192.168.1.0/24"]
        assert ip_in_cidrs("10.0.0.5", cidrs) is True
        assert ip_in_cidrs("192.168.1.100", cidrs) is True
        assert ip_in_cidrs("172.16.0.1", cidrs) is False

    def test_invalid_ip(self):
        assert ip_in_cidrs("not-an-ip", ["10.0.0.0/24"]) is False

    def test_invalid_cidr_skipped(self):
        # Invalid CIDR is skipped, valid one still matches
        assert ip_in_cidrs("10.0.0.1", ["bad-cidr", "10.0.0.0/24"]) is True

    def test_empty_cidrs(self):
        assert ip_in_cidrs("10.0.0.1", []) is False


# ── Unit tests: get_client_ip ─────────────────────────────────────────────


class TestGetClientIP:
    def test_remote_addr(self):
        factory = RequestFactory()
        request = factory.get("/", REMOTE_ADDR="1.2.3.4")
        assert get_client_ip(request) == "1.2.3.4"

    def test_x_forwarded_for_single(self):
        factory = RequestFactory()
        request = factory.get(
            "/", HTTP_X_FORWARDED_FOR="5.6.7.8", REMOTE_ADDR="127.0.0.1"
        )
        assert get_client_ip(request) == "5.6.7.8"

    def test_x_forwarded_for_chain(self):
        factory = RequestFactory()
        request = factory.get(
            "/",
            HTTP_X_FORWARDED_FOR="5.6.7.8, 10.0.0.1, 172.16.0.1",
            REMOTE_ADDR="127.0.0.1",
        )
        # With trusted proxy depth 1, should get the last entry (closest proxy)
        ip = get_client_ip(request)
        assert ip == "172.16.0.1"


# ── API tests ─────────────────────────────────────────────────────────────


class TestIPAllowlistAPI:
    def test_add_entry_success(self):
        org, _, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "10.0.0.0/24",
                "description": "Office network",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["cidr_range"] == "10.0.0.0/24"
        assert data["description"] == "Office network"
        assert data["is_active"] is True
        assert data["organization_id"] == str(org.pk)

    def test_add_entry_invalid_cidr(self):
        org, _, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "not-a-cidr",
            },
        )
        assert resp.status_code == 400
        assert "Invalid CIDR" in resp.json()["detail"]

    def test_add_entry_ipv6(self):
        org, _, token = _create_org()
        c = _client(token)
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "2001:db8::/32",
                "description": "IPv6 range",
            },
        )
        assert resp.status_code == 201
        assert resp.json()["cidr_range"] == "2001:db8::/32"

    def test_list_entries(self):
        org, _, token = _create_org()
        c = _client(token)
        # Include loopback so middleware doesn't block the test client
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "127.0.0.0/8"})
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "10.0.0.0/24"})
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "192.168.1.0/24"})

        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entries"]) == 3
        # Response includes the requester's IP for self-lockout warning
        assert "your_ip" in data

    def test_delete_entry(self):
        org, _, token = _create_org()
        c = _client(token)
        # Add loopback to keep test client unblocked
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "127.0.0.0/8"})
        add_resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "10.0.0.0/24",
            },
        )
        entry_id = add_resp.json()["id"]

        resp = _delete(c, f"{_BASE}/{org.pk}/ip-allowlist/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert IPAllowlistEntry.objects.filter(pk=entry_id).count() == 0

    def test_delete_nonexistent_entry(self):
        org, _, token = _create_org()
        c = _client(token)
        fake_id = str(uuid.uuid4())
        resp = _delete(c, f"{_BASE}/{org.pk}/ip-allowlist/{fake_id}")
        assert resp.status_code == 404

    def test_member_cannot_manage(self):
        org, _, _ = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        c = _client(member_token)

        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 401

        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "10.0.0.0/24",
            },
        )
        assert resp.status_code == 401

    def test_admin_can_manage(self):
        org, _, _ = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        c = _client(admin_token)

        # Include loopback so middleware doesn't block subsequent requests
        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "127.0.0.0/8",
            },
        )
        assert resp.status_code == 201

        resp = _post(
            c,
            f"{_BASE}/{org.pk}/ip-allowlist",
            {
                "cidr_range": "10.0.0.0/24",
            },
        )
        assert resp.status_code == 201

        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200
        assert len(resp.json()["entries"]) == 2

    def test_no_auth_returns_401(self):
        org, _, _ = _create_org()
        c = Client()
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist", content_type="application/json")
        assert resp.status_code == 401

    def test_audit_log_on_add(self):
        org, _, token = _create_org()
        c = _client(token)
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "10.0.0.0/24"})
        log = AuditLog.objects.filter(action="ip_allowlist_added").first()
        assert log is not None
        assert log.metadata["cidr_range"] == "10.0.0.0/24"

    def test_audit_log_on_remove(self):
        org, _, token = _create_org()
        c = _client(token)
        # Add loopback to keep test client unblocked
        _post(c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "127.0.0.0/8"})
        add_resp = _post(
            c, f"{_BASE}/{org.pk}/ip-allowlist", {"cidr_range": "10.0.0.0/24"}
        )
        entry_id = add_resp.json()["id"]
        _delete(c, f"{_BASE}/{org.pk}/ip-allowlist/{entry_id}")
        log = AuditLog.objects.filter(action="ip_allowlist_removed").first()
        assert log is not None
        assert log.metadata["cidr_range"] == "10.0.0.0/24"


# ── Middleware enforcement tests ──────────────────────────────────────────


class TestIPAllowlistMiddleware:
    """Test enforcement of IP allowlists via the middleware.

    These tests create allowlist entries directly in DB and make requests
    through the test client to verify middleware behavior.
    """

    def test_no_entries_no_restriction(self):
        """Org with zero allowlist entries → all IPs allowed."""
        org, _, token = _create_org()
        c = _client(token)
        # Access org endpoint — should work from any IP
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_matching_ip_allowed(self):
        """Request IP in allowlist → allowed."""
        org, _, token = _create_org()
        # Add allowlist entry for 127.0.0.0/8 (test client uses 127.0.0.1)
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="127.0.0.0/8",
            is_active=True,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_non_matching_ip_blocked(self):
        """Request IP NOT in allowlist → 403."""
        org, _, token = _create_org()
        # Add allowlist entry that doesn't match 127.0.0.1
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 403
        assert resp.json()["code"] == "ip_not_allowed"

    def test_inactive_entries_ignored(self):
        """Inactive entries are not enforced."""
        org, _, token = _create_org()
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=False,
        )
        c = _client(token)
        # No active entries → no restriction
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_empty_allowlist_after_deletion(self):
        """All entries deleted → no restriction (not 'block everyone')."""
        org, _, token = _create_org()
        entry = IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )
        # First, this should block
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 403

        # Delete the entry
        entry.delete()

        # Now should be allowed
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_multi_org_isolation(self):
        """User in Org A (has allowlist) and Org B (no allowlist).
        Allowlist only enforced for Org A calls. Org B works from any IP.
        """
        org_a, owner_a, token_a = _create_org("Org A")
        org_b, owner_b, token_b = _create_org("Org B")

        # Add restrictive allowlist to Org A only
        IPAllowlistEntry.objects.create(
            organization=org_a,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )

        # Org A endpoint → blocked (127.0.0.1 not in 10.0.0.0/8)
        c_a = _client(token_a)
        resp = c_a.get(f"{_BASE}/{org_a.pk}/ip-allowlist")
        assert resp.status_code == 403

        # Org B endpoint → allowed (no allowlist)
        c_b = _client(token_b)
        resp = c_b.get(f"{_BASE}/{org_b.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_non_org_path_not_affected(self):
        """Non-org-scoped API paths are never blocked by IP allowlist."""
        org, owner, token = _create_org()
        # Add restrictive allowlist
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )
        c = _client(token)
        # Non-org path should still work
        resp = c.get("/api/v1/workspace/organizations/")
        assert resp.status_code == 200  # List orgs endpoint, not org-scoped

    def test_blocked_access_creates_audit_log(self):
        """Blocked IP access attempts are audit-logged."""
        org, _, token = _create_org()
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )
        initial_count = AuditLog.objects.filter(action="ip_access_blocked").count()

        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 403

        blocked_logs = AuditLog.objects.filter(action="ip_access_blocked")
        assert blocked_logs.count() == initial_count + 1
        log = blocked_logs.latest("timestamp")
        assert log.resource_id == str(org.pk)

    def test_x_forwarded_for_used(self):
        """Middleware respects X-Forwarded-For header."""
        org, _, token = _create_org()
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="5.6.7.0/24",
            is_active=True,
        )
        c = Client(
            headers={
                "authorization": f"Bearer {token}",
                "x-forwarded-for": "5.6.7.8",
            },
        )
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200

    def test_self_lockout_warning(self):
        """List response includes your_ip so admin can see if they'd lock themselves out."""
        org, _, token = _create_org()
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/ip-allowlist")
        assert resp.status_code == 200
        data = resp.json()
        assert data["your_ip"] is not None
