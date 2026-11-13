"""Tests for conditional access policies: model, API endpoints, and middleware.

Covers:
- CRUD API: create, list, update, delete with RBAC
- Condition validation (ip_range, time_of_day, day_of_week, user_agent_pattern)
- Middleware enforcement: blocking, allow, require_mfa
- Priority ordering (first match wins)
- Multi-org isolation
- Edge cases: admin self-block warning, invalid conditions
- AuditLog entries
"""

import json
import uuid
from datetime import datetime

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.ip_middleware import (
    _check_day_of_week,
    _check_ip_range,
    _check_time_of_day,
    _check_user_agent,
    evaluate_conditions,
)
from apps.workspace.models import (
    ConditionalAccessPolicy,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


@pytest.fixture(autouse=True)
def _clear_cache():
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


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _delete(client, path):
    return client.delete(path, content_type="application/json")


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


# ── Unit tests: condition evaluation ──────────────────────────────────────


class TestIPRangeCondition:
    def test_matches_cidr(self):
        assert _check_ip_range({"cidr": "10.0.0.0/24"}, "10.0.0.5") is True

    def test_no_match(self):
        assert _check_ip_range({"cidr": "10.0.0.0/24"}, "192.168.1.1") is False

    def test_no_client_ip(self):
        assert _check_ip_range({"cidr": "10.0.0.0/24"}, None) is False

    def test_no_cidr(self):
        assert _check_ip_range({}, "10.0.0.1") is False


class TestTimeOfDayCondition:
    def test_within_range(self):
        import zoneinfo

        tz = zoneinfo.ZoneInfo("UTC")
        now = datetime.now(tz)
        cond = {"start_hour": now.hour, "end_hour": now.hour, "timezone": "UTC"}
        assert _check_time_of_day(cond) is True

    def test_outside_range(self):
        import zoneinfo

        tz = zoneinfo.ZoneInfo("UTC")
        now = datetime.now(tz)
        # Pick a range that excludes the current hour
        start = (now.hour + 2) % 24
        end = (now.hour + 3) % 24
        if start == end:
            end = (end + 1) % 24
        cond = {"start_hour": start, "end_hour": end, "timezone": "UTC"}
        # Make sure the current hour is really excluded
        if start <= end:
            if start <= now.hour <= end:
                pytest.skip("Edge case: current hour coincidentally in range")
        assert _check_time_of_day(cond) is False

    def test_wraps_midnight(self):
        import zoneinfo

        tz = zoneinfo.ZoneInfo("UTC")
        now = datetime.now(tz)
        # 22..6 wraps midnight
        cond = {"start_hour": 22, "end_hour": 6, "timezone": "UTC"}
        result = _check_time_of_day(cond)
        expected = now.hour >= 22 or now.hour <= 6
        assert result == expected

    def test_invalid_timezone_falls_back_to_utc(self):
        import zoneinfo

        tz = zoneinfo.ZoneInfo("UTC")
        now = datetime.now(tz)
        cond = {"start_hour": 0, "end_hour": 23, "timezone": "Invalid/TZ"}
        assert _check_time_of_day(cond) is True


class TestDayOfWeekCondition:
    def test_today_matches(self):
        import zoneinfo

        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        cond = {"days": [now.weekday()], "timezone": "UTC"}
        assert _check_day_of_week(cond) is True

    def test_today_not_in_days(self):
        import zoneinfo

        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        other_day = (now.weekday() + 1) % 7
        cond = {"days": [other_day], "timezone": "UTC"}
        assert _check_day_of_week(cond) is False


class TestUserAgentCondition:
    def test_matches_pattern(self):
        assert (
            _check_user_agent({"pattern": ".*Mobile.*"}, "Mozilla/5.0 Mobile Safari")
            is True
        )

    def test_no_match(self):
        assert (
            _check_user_agent({"pattern": ".*Mobile.*"}, "Mozilla/5.0 Desktop Chrome")
            is False
        )

    def test_empty_pattern(self):
        assert _check_user_agent({"pattern": ""}, "anything") is False
        assert _check_user_agent({}, "anything") is False

    def test_invalid_regex(self):
        assert _check_user_agent({"pattern": "[invalid"}, "anything") is False


class TestEvaluateConditions:
    def test_all_conditions_and_logic(self):
        """All conditions must match (AND)."""
        import zoneinfo

        now = datetime.now(zoneinfo.ZoneInfo("UTC"))
        conditions = [
            {"type": "ip_range", "cidr": "10.0.0.0/8"},
            {"type": "day_of_week", "days": [now.weekday()], "timezone": "UTC"},
        ]
        assert evaluate_conditions(conditions, "10.0.0.1", "") is True

    def test_one_fails_all_fail(self):
        conditions = [
            {"type": "ip_range", "cidr": "10.0.0.0/8"},
            {"type": "ip_range", "cidr": "192.168.0.0/16"},
        ]
        # IP 10.0.0.1 matches first but not second
        assert evaluate_conditions(conditions, "10.0.0.1", "") is False

    def test_empty_conditions_matches(self):
        """Policy with no conditions always matches."""
        assert evaluate_conditions([], "1.2.3.4", "any-ua") is True

    def test_user_agent_condition(self):
        conditions = [{"type": "user_agent_pattern", "pattern": "^curl/"}]
        assert evaluate_conditions(conditions, None, "curl/7.68.0") is True
        assert evaluate_conditions(conditions, None, "Mozilla/5.0") is False


# ── API tests: CRUD ─────────────────────────────────────────────────────


class TestAccessPolicyAPI:
    def test_create_policy(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Block external IPs",
                "conditions": [{"type": "ip_range", "cidr": "192.168.0.0/16"}],
                "action": "block",
                "priority": 10,
            },
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["name"] == "Block external IPs"
        assert data["action"] == "block"
        assert data["priority"] == 10
        assert len(data["conditions"]) == 1
        assert data["conditions"][0]["cidr"] == "192.168.0.0/16"

    def test_list_policies(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Policy A",
                "conditions": [{"type": "ip_range", "cidr": "10.0.0.0/8"}],
                "action": "allow",
                "priority": 1,
            },
        )
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Policy B",
                "conditions": [{"type": "user_agent_pattern", "pattern": ".*Bot.*"}],
                "action": "block",
                "priority": 2,
            },
        )
        resp = _client(token).get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["policies"]) == 2
        # Sorted by priority
        assert data["policies"][0]["name"] == "Policy A"
        assert data["policies"][1]["name"] == "Policy B"
        assert "your_ip" in data

    def test_update_policy(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Original",
                "conditions": [{"type": "ip_range", "cidr": "10.0.0.0/8"}],
                "action": "block",
            },
        )
        pid = resp.json()["id"]
        resp2 = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies/{pid}",
            {
                "name": "Updated",
                "action": "allow",
                "priority": 5,
            },
        )
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Updated"
        assert resp2.json()["action"] == "allow"
        assert resp2.json()["priority"] == 5

    def test_delete_policy(self):
        org, owner, token = _create_org()
        # Use a non-matching condition so middleware doesn't block the delete request
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "To Delete",
                "conditions": [{"type": "ip_range", "cidr": "203.0.113.0/24"}],
                "action": "block",
            },
        )
        pid = resp.json()["id"]
        resp2 = _delete(_client(token), f"{_BASE}/{org.pk}/access-policies/{pid}")
        assert resp2.status_code == 200
        assert resp2.json()["success"] is True
        assert ConditionalAccessPolicy.objects.filter(pk=pid).count() == 0

    def test_delete_not_found(self):
        org, owner, token = _create_org()
        fake_id = uuid.uuid4()
        resp = _delete(_client(token), f"{_BASE}/{org.pk}/access-policies/{fake_id}")
        assert resp.status_code == 404

    def test_rbac_viewer_cannot_create(self):
        org, owner, owner_token = _create_org()
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER, invited_by=owner)
        resp = _post(
            _client(viewer_token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Blocked",
                "conditions": [],
                "action": "block",
            },
        )
        assert resp.status_code in (401, 403)

    def test_rbac_member_cannot_create(self):
        org, owner, owner_token = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER, invited_by=owner)
        resp = _post(
            _client(member_token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Blocked",
                "conditions": [],
                "action": "block",
            },
        )
        assert resp.status_code in (401, 403)

    def test_rbac_admin_can_create(self):
        org, owner, owner_token = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN, invited_by=owner)
        resp = _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Admin Policy",
                "conditions": [{"type": "ip_range", "cidr": "10.0.0.0/8"}],
                "action": "block",
            },
        )
        assert resp.status_code == 201

    def test_invalid_action(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad Action",
                "conditions": [],
                "action": "invalid",
            },
        )
        assert resp.status_code == 400

    def test_invalid_cidr(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad CIDR",
                "conditions": [{"type": "ip_range", "cidr": "not-a-cidr"}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_invalid_condition_type(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad Type",
                "conditions": [{"type": "nonexistent"}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_invalid_time_range(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad Hours",
                "conditions": [
                    {"type": "time_of_day", "start_hour": 25, "end_hour": 10}
                ],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_invalid_day_of_week(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad Days",
                "conditions": [{"type": "day_of_week", "days": [7, 8]}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_invalid_regex_pattern(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Bad Regex",
                "conditions": [{"type": "user_agent_pattern", "pattern": "[invalid"}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_missing_cidr_field(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Missing CIDR",
                "conditions": [{"type": "ip_range"}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_missing_hours(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Missing Hours",
                "conditions": [{"type": "time_of_day"}],
                "action": "block",
            },
        )
        assert resp.status_code == 400

    def test_update_conditions_validation(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Test",
                "conditions": [{"type": "ip_range", "cidr": "10.0.0.0/8"}],
                "action": "block",
            },
        )
        pid = resp.json()["id"]
        resp2 = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies/{pid}",
            {
                "conditions": [{"type": "ip_range", "cidr": "bad"}],
            },
        )
        assert resp2.status_code == 400

    def test_update_not_found(self):
        org, owner, token = _create_org()
        fake_id = uuid.uuid4()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies/{fake_id}",
            {
                "name": "No Such",
            },
        )
        assert resp.status_code == 404


# ── Audit log tests ──────────────────────────────────────────────────────


class TestAccessPolicyAuditLog:
    def test_create_logs_audit(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Audit Test",
                "conditions": [{"type": "ip_range", "cidr": "10.0.0.0/8"}],
                "action": "block",
            },
        )
        assert resp.status_code == 201
        log = AuditLog.objects.filter(action="access_policy_created").first()
        assert log is not None
        assert log.metadata["policy_name"] == "Audit Test"

    def test_update_logs_audit(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Before",
                "conditions": [{"type": "ip_range", "cidr": "203.0.113.0/24"}],
                "action": "block",
            },
        )
        pid = resp.json()["id"]
        _patch(
            _client(token), f"{_BASE}/{org.pk}/access-policies/{pid}", {"name": "After"}
        )
        log = AuditLog.objects.filter(action="access_policy_updated").first()
        assert log is not None

    def test_delete_logs_audit(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/access-policies",
            {
                "name": "Deleted",
                "conditions": [{"type": "ip_range", "cidr": "203.0.113.0/24"}],
                "action": "block",
            },
        )
        pid = resp.json()["id"]
        _delete(_client(token), f"{_BASE}/{org.pk}/access-policies/{pid}")
        log = AuditLog.objects.filter(action="access_policy_deleted").first()
        assert log is not None
        assert log.metadata["policy_name"] == "Deleted"


# ── Middleware tests ─────────────────────────────────────────────────────


class TestConditionalAccessMiddleware:
    def _setup_org_with_policy(self, conditions, action="block", priority=0):
        """Helper: create org + owner + policy, return (org, owner, token)."""
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Test Policy",
            conditions=conditions,
            action=action,
            is_active=True,
            priority=priority,
        )
        return org, owner, token

    def test_block_action_returns_403(self):
        """Policy with action=block returns 403 when conditions match."""
        # Empty conditions = always matches
        org, owner, token = self._setup_org_with_policy([], action="block")
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 403
        assert "access_policy_blocked" in resp.json().get("code", "")

    def test_allow_action_passes_through(self):
        org, owner, token = self._setup_org_with_policy([], action="allow")
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_no_policies_passes_through(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_inactive_policy_ignored(self):
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Inactive Block",
            conditions=[],
            action="block",
            is_active=False,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_ip_range_block(self):
        """Block requests not from allowed IP range."""
        org, owner, token = _create_org()
        # Block requests from 127.0.0.0/8 (test client IP)
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block localhost",
            conditions=[{"type": "ip_range", "cidr": "127.0.0.0/8"}],
            action="block",
            is_active=True,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 403

    def test_ip_range_no_match_passes(self):
        """Non-matching IP condition → policy doesn't fire → pass through."""
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block external only",
            conditions=[{"type": "ip_range", "cidr": "203.0.113.0/24"}],
            action="block",
            is_active=True,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_user_agent_block(self):
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block bots",
            conditions=[{"type": "user_agent_pattern", "pattern": ".*Bot.*"}],
            action="block",
            is_active=True,
        )
        c = Client(
            headers={"authorization": f"Bearer {token}"},
            HTTP_USER_AGENT="Mozilla/5.0 Bot/1.0",
        )
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 403

    def test_user_agent_no_match_passes(self):
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block bots",
            conditions=[{"type": "user_agent_pattern", "pattern": ".*Bot.*"}],
            action="block",
            is_active=True,
        )
        c = Client(
            headers={"authorization": f"Bearer {token}"},
            HTTP_USER_AGENT="Mozilla/5.0 Chrome/120",
        )
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_priority_ordering_first_match_wins(self):
        """Lower priority number = higher priority. First match wins."""
        org, owner, token = _create_org()
        # Priority 1: allow all
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Allow All",
            conditions=[],
            action="allow",
            is_active=True,
            priority=1,
        )
        # Priority 2: block all (should never be reached)
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block All",
            conditions=[],
            action="block",
            is_active=True,
            priority=2,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 200

    def test_priority_ordering_block_first(self):
        """Block policy with higher priority overrides allow."""
        org, owner, token = _create_org()
        # Priority 1: block all
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block All",
            conditions=[],
            action="block",
            is_active=True,
            priority=1,
        )
        # Priority 2: allow all
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Allow All",
            conditions=[],
            action="allow",
            is_active=True,
            priority=2,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 403

    def test_multi_org_isolation(self):
        """Policies from one org don't affect another."""
        org1, owner1, token1 = _create_org("Org 1")
        org2, owner2, token2 = _create_org("Org 2")

        # Block all on org1
        ConditionalAccessPolicy.objects.create(
            organization=org1,
            name="Block Org1",
            conditions=[],
            action="block",
            is_active=True,
        )

        # Org2 should be unaffected
        c2 = _client(token2)
        resp = c2.get(f"{_BASE}/{org2.pk}/access-policies")
        assert resp.status_code == 200

    def test_non_org_path_not_affected(self):
        """Non-org-scoped paths are never blocked."""
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block All",
            conditions=[],
            action="block",
            is_active=True,
        )
        c = _client(token)
        # This is a non-org-scoped path
        resp = c.get("/api/v1/workspace/organizations/")
        # The list endpoint doesn't match /{uuid}/ pattern
        assert resp.status_code == 200

    def test_require_mfa_action(self):
        """action=require_mfa returns 403 with mfa_required code if not verified."""
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Require MFA",
            conditions=[],
            action="require_mfa",
            is_active=True,
        )
        c = _client(token)
        resp = c.get(f"{_BASE}/{org.pk}/access-policies")
        assert resp.status_code == 403
        assert "mfa_required" in resp.json().get("code", "")

    def test_block_logs_audit(self):
        """Blocked access creates an AuditLog entry."""
        org, owner, token = _create_org()
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block and Log",
            conditions=[],
            action="block",
            is_active=True,
        )
        AuditLog.objects.all().delete()
        c = _client(token)
        c.get(f"{_BASE}/{org.pk}/access-policies")
        log = AuditLog.objects.filter(action="access_policy_blocked").first()
        assert log is not None
        assert log.metadata["policy_name"] == "Block and Log"
