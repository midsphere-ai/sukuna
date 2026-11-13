"""Tests for compliance dashboard API endpoints.

Covers US-014 acceptance criteria:
- Dashboard summary, audit log (paginated + filterable), retention status,
  consent overview, MFA status, audit log CSV export.
- Permission enforcement (admin-only: superuser or org owner).
"""

import csv
import io
from unittest.mock import patch

import pytest
from django.test import RequestFactory
from django.utils import timezone

from apps.compliance.api import (
    audit_log_export,
    audit_log_list,
    consent_overview,
    dashboard_summary,
    mfa_status,
    retention_status,
)
from apps.compliance.models import (
    AuditLog,
    ConsentRecord,
    ConsentType,
    RetentionPolicy,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def superuser():
    return UserFactory(is_superuser=True)


@pytest.fixture
def regular_user():
    return UserFactory()


@pytest.fixture
def org_owner():
    user = UserFactory()
    org = Organization.objects.create(name="Dashboard Test Org")
    OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.OWNER
    )
    return user


def _req(rf, user, **query_params):
    """Build a GET request with auth set."""
    request = rf.get("/test/", query_params)
    request.auth = user
    request.request_id = "test-req"
    return request


# =============================================================================
# DASHBOARD SUMMARY
# =============================================================================


class TestDashboardSummary:
    def test_returns_all_fields(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user")
        RetentionPolicy.objects.create(
            resource_type="test", retention_days=30, action="delete"
        )

        request = _req(rf, superuser)
        status, body = dashboard_summary(request)
        assert status == 200
        assert "total_audit_entries" in body
        assert "active_retention_policies" in body
        assert "consent_coverage_percentage" in body
        assert "total_users" in body
        assert "mfa_enabled_count" in body
        assert "mfa_enabled_percentage" in body

    def test_audit_entry_count(self, rf, superuser):
        for i in range(5):
            AuditLog.log(action="login", resource_type="user", resource_id=str(i))
        request = _req(rf, superuser)
        status, body = dashboard_summary(request)
        assert body["total_audit_entries"] >= 5

    def test_active_retention_count(self, rf, superuser):
        RetentionPolicy.objects.create(
            resource_type="r1", retention_days=30, action="delete", is_active=True
        )
        RetentionPolicy.objects.create(
            resource_type="r2", retention_days=60, action="keep", is_active=False
        )
        request = _req(rf, superuser)
        status, body = dashboard_summary(request)
        assert body["active_retention_policies"] >= 1

    def test_consent_coverage(self, rf, superuser):
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        request = _req(rf, superuser)
        status, body = dashboard_summary(request)
        assert body["consent_coverage_percentage"] > 0

    def test_mfa_count_with_mock(self, rf, superuser):
        request = _req(rf, superuser)
        with patch("allauth.mfa.models.Authenticator") as MockAuth:
            MockAuth.objects.values.return_value.distinct.return_value.count.return_value = 3
            status, body = dashboard_summary(request)
        assert status == 200
        assert body["mfa_enabled_count"] == 3

    def test_permission_denied_regular_user(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = dashboard_summary(request)
        assert status == 403

    def test_org_owner_has_access(self, rf, org_owner):
        request = _req(rf, org_owner)
        status, body = dashboard_summary(request)
        assert status == 200


# =============================================================================
# AUDIT LOG LIST
# =============================================================================


class TestAuditLogList:
    def test_returns_paginated(self, rf, superuser):
        for i in range(10):
            AuditLog.log(action="login", resource_type="user", resource_id=str(i))

        request = _req(rf, superuser, page=1, page_size=5)
        status, body = audit_log_list(request, page=1, page_size=5)
        assert status == 200
        assert body["page"] == 1
        assert body["page_size"] == 5
        assert len(body["results"]) == 5
        assert body["total"] >= 10
        assert body["total_pages"] >= 2

    def test_page_2(self, rf, superuser):
        for i in range(10):
            AuditLog.log(action="login", resource_type="user", resource_id=str(i))

        request = _req(rf, superuser, page=2, page_size=5)
        status, body = audit_log_list(request, page=2, page_size=5)
        assert status == 200
        assert body["page"] == 2
        assert len(body["results"]) == 5

    def test_filter_by_action(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user")
        AuditLog.log(action="create", resource_type="conversation")

        request = _req(rf, superuser, action="login")
        status, body = audit_log_list(request, action="login")
        assert status == 200
        assert all(r["action"] == "login" for r in body["results"])

    def test_filter_by_actor_email(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user", actor_email="alice@test.com")
        AuditLog.log(action="login", resource_type="user", actor_email="bob@test.com")

        request = _req(rf, superuser, actor_email="alice")
        status, body = audit_log_list(request, actor_email="alice")
        assert status == 200
        assert all("alice" in r["actor_email"] for r in body["results"])

    def test_filter_by_resource_type(self, rf, superuser):
        AuditLog.log(action="create", resource_type="conversation")
        AuditLog.log(action="create", resource_type="user")

        request = _req(rf, superuser, resource_type="conversation")
        status, body = audit_log_list(request, resource_type="conversation")
        assert status == 200
        assert all(r["resource_type"] == "conversation" for r in body["results"])

    def test_filter_by_date_range(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user")
        now = timezone.now()
        date_from = (now - timezone.timedelta(hours=1)).isoformat()
        date_to = (now + timezone.timedelta(hours=1)).isoformat()

        request = _req(rf, superuser, date_from=date_from, date_to=date_to)
        status, body = audit_log_list(request, date_from=date_from, date_to=date_to)
        assert status == 200
        assert len(body["results"]) >= 1

    def test_keyword_search(self, rf, superuser):
        AuditLog.log(
            action="create",
            resource_type="user",
            metadata={"special_keyword_xyz": True},
        )
        AuditLog.log(action="login", resource_type="user")

        request = _req(rf, superuser, q="special_keyword_xyz")
        status, body = audit_log_list(request, q="special_keyword_xyz")
        assert status == 200
        assert len(body["results"]) >= 1

    def test_result_shape(self, rf, superuser):
        AuditLog.log(
            action="login",
            resource_type="user",
            actor_email="test@test.com",
            actor_ip="1.2.3.4",
            request_id="req-1",
        )
        request = _req(rf, superuser)
        status, body = audit_log_list(request)
        assert status == 200
        entry = body["results"][0]
        assert "id" in entry
        assert "timestamp" in entry
        assert "actor_email" in entry
        assert "action" in entry
        assert "resource_type" in entry
        assert "changes" in entry
        assert "metadata" in entry

    def test_permission_denied(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = audit_log_list(request)
        assert status == 403

    def test_page_size_clamped(self, rf, superuser):
        request = _req(rf, superuser, page_size=999)
        status, body = audit_log_list(request, page_size=999)
        assert status == 200
        assert body["page_size"] == 200  # max


# =============================================================================
# RETENTION STATUS
# =============================================================================


class TestRetentionStatus:
    def test_returns_all_policies(self, rf, superuser):
        RetentionPolicy.objects.create(
            resource_type="rs1", retention_days=30, action="delete"
        )
        RetentionPolicy.objects.create(
            resource_type="rs2", retention_days=60, action="keep", is_active=False
        )

        request = _req(rf, superuser)
        status, body = retention_status(request)
        assert status == 200
        types = [p["resource_type"] for p in body]
        assert "rs1" in types
        assert "rs2" in types

    def test_next_scheduled_run_for_active(self, rf, superuser):
        RetentionPolicy.objects.create(
            resource_type="rs3", retention_days=30, action="delete", is_active=True
        )
        request = _req(rf, superuser)
        status, body = retention_status(request)
        active = [p for p in body if p["resource_type"] == "rs3"][0]
        assert active["next_scheduled_run"] is not None

    def test_next_scheduled_run_null_for_inactive(self, rf, superuser):
        RetentionPolicy.objects.create(
            resource_type="rs4", retention_days=30, action="delete", is_active=False
        )
        request = _req(rf, superuser)
        status, body = retention_status(request)
        inactive = [p for p in body if p["resource_type"] == "rs4"][0]
        assert inactive["next_scheduled_run"] is None

    def test_includes_last_run_fields(self, rf, superuser):
        now = timezone.now()
        RetentionPolicy.objects.create(
            resource_type="rs5",
            retention_days=30,
            action="delete",
            last_run_at=now,
            records_affected_last_run=42,
        )
        request = _req(rf, superuser)
        status, body = retention_status(request)
        p = [p for p in body if p["resource_type"] == "rs5"][0]
        assert p["last_run_at"] is not None
        assert p["records_affected_last_run"] == 42

    def test_permission_denied(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = retention_status(request)
        assert status == 403


# =============================================================================
# CONSENT OVERVIEW
# =============================================================================


class TestConsentOverview:
    def test_returns_all_consent_types(self, rf, superuser):
        request = _req(rf, superuser)
        status, body = consent_overview(request)
        assert status == 200
        assert "total_users" in body
        assert "consent_types" in body
        for ct_value, _ in ConsentType.choices:
            assert ct_value in body["consent_types"]

    def test_granted_count(self, rf, superuser):
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        request = _req(rf, superuser)
        status, body = consent_overview(request)
        assert body["consent_types"]["analytics"]["granted_count"] >= 1

    def test_coverage_percentage(self, rf, superuser):
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type="analytics",
            version="1.0",
            action="granted",
        )
        request = _req(rf, superuser)
        status, body = consent_overview(request)
        assert body["consent_types"]["analytics"]["coverage_percentage"] > 0

    def test_permission_denied(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = consent_overview(request)
        assert status == 403


# =============================================================================
# MFA STATUS
# =============================================================================


class TestMFAStatus:
    def test_returns_expected_fields(self, rf, superuser):
        request = _req(rf, superuser)
        status, body = mfa_status(request)
        assert status == 200
        assert "total_users" in body
        assert "mfa_enabled_count" in body
        assert "mfa_enabled_percentage" in body
        assert "organizations" in body

    def test_org_enforcement_info(self, rf, superuser):
        org = Organization.objects.create(name="MFA Test Org", mfa_required=True)
        OrganizationMembership.objects.create(
            organization=org,
            user=superuser,
            role=OrganizationRole.OWNER,
        )
        request = _req(rf, superuser)
        status, body = mfa_status(request)
        org_entry = [o for o in body["organizations"] if o["name"] == "MFA Test Org"]
        assert len(org_entry) == 1
        assert org_entry[0]["mfa_required"] is True
        assert org_entry[0]["member_count"] == 1

    def test_permission_denied(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = mfa_status(request)
        assert status == 403


# =============================================================================
# AUDIT LOG EXPORT
# =============================================================================


class TestAuditLogExport:
    def test_returns_csv(self, rf, superuser):
        AuditLog.log(
            action="login",
            resource_type="user",
            actor_email="export@test.com",
        )
        request = _req(rf, superuser)
        response = audit_log_export(request)
        assert response["Content-Type"] == "text/csv"
        assert "audit_log_export.csv" in response["Content-Disposition"]

    def test_csv_has_header_and_rows(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user", actor_email="csv@test.com")
        AuditLog.log(action="create", resource_type="conv", actor_email="csv@test.com")

        request = _req(rf, superuser)
        response = audit_log_export(request)
        content = response.content.decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        header = rows[0]
        assert "id" in header
        assert "timestamp" in header
        assert "actor_email" in header
        assert "action" in header
        assert len(rows) >= 3  # header + at least 2 data rows

    def test_filter_applied_to_export(self, rf, superuser):
        AuditLog.log(action="login", resource_type="user", actor_email="keep@test.com")
        AuditLog.log(
            action="create", resource_type="conversation", actor_email="skip@test.com"
        )

        request = _req(rf, superuser, action="login")
        response = audit_log_export(request, action="login")
        content = response.content.decode("utf-8")
        assert "keep@test.com" in content
        # The create action should be filtered out
        lines = content.strip().split("\n")
        data_lines = lines[1:]  # skip header
        for line in data_lines:
            assert "login" in line

    def test_permission_denied(self, rf, regular_user):
        request = _req(rf, regular_user)
        status, body = audit_log_export(request)
        assert status == 403

    def test_empty_export(self, rf, superuser):
        # Filter that matches nothing
        request = _req(rf, superuser, action="nonexistent_action")
        response = audit_log_export(request, action="nonexistent_action")
        content = response.content.decode("utf-8")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        assert len(rows) == 1  # header only
