"""Tests for org usage analytics endpoints (US-041)."""

from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)


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


BASE = "/api/v1/workspace/organizations"


def _create_org_with_admin():
    """Create org with owner + admin. Returns (org, owner, owner_token, admin, admin_token)."""
    owner, owner_tok = _make_user()
    admin, admin_tok = _make_user()
    viewer, viewer_tok = _make_user()

    org = Organization.objects.create(name="Analytics Org")
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    OrganizationMembership.objects.create(
        organization=org, user=admin, role=OrganizationRole.ADMIN
    )
    OrganizationMembership.objects.create(
        organization=org, user=viewer, role=OrganizationRole.VIEWER
    )

    return org, owner, owner_tok, admin, admin_tok, viewer, viewer_tok


def _create_test_data(org, user):
    """Create agent runs, conversations, credit transactions for analytics."""
    from apps.billing.models import CreditTransaction, CreditWallet
    from apps.spaces.models import Project
    from apps.storage.models import AgentRun, Conversation

    project = Project.objects.create(title="Test Project", user=user, organization=org)
    conv = Conversation.objects.create(title="Test Conv", user=user, project=project)

    # Create agent runs
    runs = []
    for i in range(3):
        run = AgentRun.objects.create(
            conversation=conv,
            user=user,
            task=f"Task {i}",
            status="completed",
        )
        runs.append(run)

    # Create credit wallet + debit transactions
    wallet, _ = CreditWallet.objects.get_or_create(user=user)
    wallet.free_credits = 1000
    wallet.save()
    for i in range(3):
        CreditTransaction.objects.create(
            wallet=wallet,
            amount=-10,
            balance_after=1000 - (i + 1) * 10,
            category="llm",
            description=f"Test debit {i}",
        )

    return project, conv, runs


# ── Summary endpoint tests ─────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyticsSummary:
    def test_summary_returns_counts(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agent_runs"] == 3
        assert data["total_conversations"] == 1
        assert data["total_credits_consumed"] == 30
        assert data["active_members"] == 1
        assert "period_start" in data
        assert "period_end" in data

    def test_summary_date_range_7d(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/summary?period=7d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agent_runs"] == 3  # All recent

    def test_summary_date_range_excludes_old_data(self):
        org, owner, tok, *_ = _create_org_with_admin()
        from apps.spaces.models import Project
        from apps.storage.models import AgentRun, Conversation

        project = Project.objects.create(
            title="Old Project", user=owner, organization=org
        )
        conv = Conversation.objects.create(
            title="Old Conv", user=owner, project=project
        )

        # Create an old run (60 days ago)
        run = AgentRun.objects.create(
            conversation=conv, user=owner, task="Old task", status="completed"
        )
        AgentRun.objects.filter(pk=run.pk).update(
            created_at=timezone.now() - timedelta(days=60)
        )

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/summary?period=30d")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_agent_runs"] == 0

    def test_summary_permission_admin_required(self):
        org, _, _, _, _, viewer, viewer_tok = _create_org_with_admin()

        resp = _client(viewer_tok).get(f"{BASE}/{org.pk}/analytics/summary")
        assert resp.status_code == 401  # UnauthorizedAccessError

    def test_summary_non_member_denied(self):
        org, *_ = _create_org_with_admin()
        outsider, outsider_tok = _make_user()

        resp = _client(outsider_tok).get(f"{BASE}/{org.pk}/analytics/summary")
        assert resp.status_code == 401  # UnauthorizedAccessError

    def test_summary_custom_date_range(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        now = timezone.now()
        start = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        end = now.strftime("%Y-%m-%d")
        resp = _client(tok).get(
            f"{BASE}/{org.pk}/analytics/summary?start_date={start}&end_date={end}"
        )
        assert resp.status_code == 200


# ── Members endpoint tests ─────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyticsMembers:
    def test_members_per_user_stats(self):
        org, owner, tok, admin, _, _, _ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/members")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        # Find the owner entry
        owner_entry = next(
            (r for r in data["results"] if r["user_id"] == owner.pk), None
        )
        assert owner_entry is not None
        assert owner_entry["agent_runs_count"] == 3
        assert owner_entry["credits_consumed"] == 30

    def test_members_pagination(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/members?page=1&page_size=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 1
        assert len(data["results"]) <= 1
        assert data["total_pages"] >= 1

    def test_members_sort_by_credits(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(
            f"{BASE}/{org.pk}/analytics/members?sort_by=credits_consumed&sort_order=desc"
        )
        assert resp.status_code == 200

    def test_members_csv_export(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/members?format=csv")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        assert "member_analytics.csv" in resp["Content-Disposition"]
        content = resp.content.decode()
        assert "Email" in content
        assert "Agent Runs" in content

    def test_members_removed_member_attribution(self):
        """Removed members should still appear with '(removed)' in name."""
        org, owner, tok, *_ = _create_org_with_admin()
        # Create a user who will be removed
        removed_user, _ = _make_user()
        membership = OrganizationMembership.objects.create(
            organization=org, user=removed_user, role=OrganizationRole.MEMBER
        )
        _create_test_data(org, removed_user)

        # Remove the member
        membership.delete()

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/members")
        assert resp.status_code == 200
        data = resp.json()
        removed_entry = next(
            (r for r in data["results"] if r["user_id"] == removed_user.pk),
            None,
        )
        assert removed_entry is not None
        assert "(removed)" in removed_entry["name"]

    def test_members_permission_denied_viewer(self):
        org, _, _, _, _, viewer, viewer_tok = _create_org_with_admin()

        resp = _client(viewer_tok).get(f"{BASE}/{org.pk}/analytics/members")
        assert resp.status_code == 401


# ── Projects endpoint tests ────────────────────────────────────────────


@pytest.mark.django_db
class TestAnalyticsProjects:
    def test_projects_per_project_stats(self):
        org, owner, tok, *_ = _create_org_with_admin()
        project, conv, runs = _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        proj_entry = next(
            (r for r in data["results"] if str(r["project_id"]) == str(project.pk)),
            None,
        )
        assert proj_entry is not None
        assert proj_entry["agent_runs"] == 3
        assert proj_entry["unique_users"] == 1

    def test_projects_pagination(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(
            f"{BASE}/{org.pk}/analytics/projects?page=1&page_size=1"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["page"] == 1
        assert data["page_size"] == 1

    def test_projects_csv_export(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(f"{BASE}/{org.pk}/analytics/projects?format=csv")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        assert "project_analytics.csv" in resp["Content-Disposition"]
        content = resp.content.decode()
        assert "Project ID" in content
        assert "Agent Runs" in content

    def test_projects_sort_by_title(self):
        org, owner, tok, *_ = _create_org_with_admin()
        _create_test_data(org, owner)

        resp = _client(tok).get(
            f"{BASE}/{org.pk}/analytics/projects?sort_by=title&sort_order=asc"
        )
        assert resp.status_code == 200

    def test_projects_permission_denied_viewer(self):
        org, _, _, _, _, viewer, viewer_tok = _create_org_with_admin()

        resp = _client(viewer_tok).get(f"{BASE}/{org.pk}/analytics/projects")
        assert resp.status_code == 401

    def test_projects_not_found(self):
        _, owner, tok, *_ = _create_org_with_admin()
        import uuid

        resp = _client(tok).get(f"{BASE}/{uuid.uuid4()}/analytics/projects")
        assert resp.status_code == 404
