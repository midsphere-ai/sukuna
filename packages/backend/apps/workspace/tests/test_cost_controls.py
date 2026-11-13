"""Tests for cost controls: member limits, project budgets, spending alerts, monthly reset."""

import pytest
from django.test import Client

from apps.spaces.models import Project, ProjectBudget
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Notification,
    NotificationType,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgCostPolicy,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_org_with_member(role=OrganizationRole.MEMBER):
    """Create an org with an owner and a member user. Returns (org, owner, member)."""
    owner = UserFactory()
    member = UserFactory()
    org = Organization.objects.create(name="Test Org")
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    OrganizationMembership.objects.create(organization=org, user=member, role=role)
    return org, owner, member


def _make_project_in_org(org, user):
    """Create a project owned by user in the given org."""
    return Project.objects.create(title="Org Project", user=user, organization=org)


def _create_debit_transactions(user, project, amount, count=1):
    """Create debit CreditTransactions linked to runs in the given project."""
    from apps.billing.models import CreditHold, CreditTransaction, CreditWallet
    from apps.storage.models import AgentRun, Conversation

    wallet, _ = CreditWallet.objects.get_or_create(
        user=user,
        defaults={
            "monthly_credits": 10000,
            "monthly_credits_remaining": 10000,
            "free_credits": 1000,
        },
    )

    conv = Conversation.objects.create(user=user, title="test conv", project=project)
    for i in range(count):
        run = AgentRun.objects.create(
            user=user, conversation=conv, task="test", status="completed"
        )
        hold = CreditHold.objects.create(
            wallet=wallet,
            run=run,
            amount_reserved=amount,
            amount_consumed=amount,
            status="settled",
        )
        CreditTransaction.objects.create(
            wallet=wallet,
            hold=hold,
            amount=-amount,
            balance_after=wallet.total_available,
            category="llm",
            description="test debit",
        )


# ── Model Tests ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestOrgCostPolicyModel:
    def test_create_cost_policy(self):
        org = Organization.objects.create(name="Org")
        policy = OrgCostPolicy.objects.create(
            organization=org, member_monthly_credit_limit=5000
        )
        assert policy.member_monthly_credit_limit == 5000
        assert policy.alert_threshold_percent == 80
        assert str(policy) == "Cost policy for Org: 5000/member/month"

    def test_unlimited_policy(self):
        org = Organization.objects.create(name="Org")
        policy = OrgCostPolicy.objects.create(organization=org)
        assert policy.member_monthly_credit_limit is None
        assert "unlimited" in str(policy)


@pytest.mark.django_db
class TestProjectBudgetModel:
    def test_create_budget(self):
        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        budget = ProjectBudget.objects.create(
            project=project, monthly_credit_limit=10000
        )
        assert budget.monthly_credit_limit == 10000
        assert budget.alert_threshold_percent == 80
        assert budget.current_month_usage == 0

    def test_unlimited_budget(self):
        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        budget = ProjectBudget.objects.create(project=project)
        assert budget.monthly_credit_limit is None


# ── Enforcement Tests ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestMemberLimitEnforcement:
    def test_no_policy_allows_run(self):
        from apps.workspace.cost_controls import check_member_limit

        org, owner, member = _make_org_with_member()
        assert check_member_limit(member, org) is None

    def test_unlimited_policy_allows_run(self):
        from apps.workspace.cost_controls import check_member_limit

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(organization=org)  # limit=None
        assert check_member_limit(member, org) is None

    def test_under_limit_allows_run(self):
        from apps.workspace.cost_controls import check_member_limit

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(organization=org, member_monthly_credit_limit=5000)
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 100, count=3)  # 300 < 5000
        assert check_member_limit(member, org) is None

    def test_at_limit_blocks_run(self):
        from apps.workspace.cost_controls import check_member_limit

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(organization=org, member_monthly_credit_limit=500)
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 500)  # 500 >= 500
        error = check_member_limit(member, org)
        assert error == "Monthly credit limit reached for this organization"

    def test_over_limit_blocks_run(self):
        from apps.workspace.cost_controls import check_member_limit

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(organization=org, member_monthly_credit_limit=500)
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 600)  # 600 > 500
        error = check_member_limit(member, org)
        assert error is not None


@pytest.mark.django_db
class TestProjectBudgetEnforcement:
    def test_no_budget_allows_run(self):
        from apps.workspace.cost_controls import check_project_budget

        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        assert check_project_budget(project) is None

    def test_unlimited_budget_allows_run(self):
        from apps.workspace.cost_controls import check_project_budget

        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        ProjectBudget.objects.create(project=project)  # limit=None
        assert check_project_budget(project) is None

    def test_under_budget_allows_run(self):
        from apps.workspace.cost_controls import check_project_budget

        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        ProjectBudget.objects.create(
            project=project, monthly_credit_limit=1000, current_month_usage=500
        )
        assert check_project_budget(project) is None

    def test_at_budget_blocks_run(self):
        from apps.workspace.cost_controls import check_project_budget

        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        ProjectBudget.objects.create(
            project=project, monthly_credit_limit=1000, current_month_usage=1000
        )
        error = check_project_budget(project)
        assert error == "Project budget exhausted for this month"

    def test_over_budget_blocks_run(self):
        from apps.workspace.cost_controls import check_project_budget

        user = UserFactory()
        project = Project.objects.create(title="P1", user=user)
        ProjectBudget.objects.create(
            project=project, monthly_credit_limit=1000, current_month_usage=1500
        )
        error = check_project_budget(project)
        assert error is not None


@pytest.mark.django_db
class TestOrgCostLimitsIntegration:
    """Test check_org_cost_limits which combines member + project checks."""

    def test_personal_run_never_blocked(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import check_org_cost_limits

        user = UserFactory()
        conv = Conversation.objects.create(user=user, title="personal")
        assert check_org_cost_limits(conv, user) is None

    def test_org_run_no_limits(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import check_org_cost_limits

        org, owner, member = _make_org_with_member()
        project = _make_project_in_org(org, member)
        conv = Conversation.objects.create(
            user=member, title="org conv", project=project
        )
        assert check_org_cost_limits(conv, member) is None

    def test_member_limit_hit(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import check_org_cost_limits

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(organization=org, member_monthly_credit_limit=100)
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 100)
        conv = Conversation.objects.create(
            user=member, title="org conv", project=project
        )
        error = check_org_cost_limits(conv, member)
        assert "Monthly credit limit" in error

    def test_project_budget_hit(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import check_org_cost_limits

        org, owner, member = _make_org_with_member()
        project = _make_project_in_org(org, member)
        ProjectBudget.objects.create(
            project=project, monthly_credit_limit=200, current_month_usage=200
        )
        conv = Conversation.objects.create(
            user=member, title="org conv", project=project
        )
        error = check_org_cost_limits(conv, member)
        assert "Project budget" in error


# ── Multi-Org Tests ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestMultiOrgLimits:
    """User in multiple orgs: each org's limit applies only to that org's projects."""

    def test_different_org_limits_independent(self):
        from apps.workspace.cost_controls import check_member_limit

        user = UserFactory()
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=org_a, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_b, user=user, role=OrganizationRole.MEMBER
        )

        OrgCostPolicy.objects.create(
            organization=org_a, member_monthly_credit_limit=500
        )
        OrgCostPolicy.objects.create(
            organization=org_b, member_monthly_credit_limit=1000
        )

        proj_a = _make_project_in_org(org_a, user)
        proj_b = _make_project_in_org(org_b, user)

        # Spend 400 in org A
        _create_debit_transactions(user, proj_a, 400)

        # Org A: 400 < 500, still OK
        assert check_member_limit(user, org_a) is None
        # Org B: 0 < 1000, still OK
        assert check_member_limit(user, org_b) is None

    def test_one_org_blocked_other_ok(self):
        from apps.workspace.cost_controls import check_member_limit

        user = UserFactory()
        org_a = Organization.objects.create(name="Org A")
        org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=org_a, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org_b, user=user, role=OrganizationRole.MEMBER
        )

        OrgCostPolicy.objects.create(
            organization=org_a, member_monthly_credit_limit=100
        )
        OrgCostPolicy.objects.create(
            organization=org_b, member_monthly_credit_limit=1000
        )

        proj_a = _make_project_in_org(org_a, user)

        # Spend 100 in org A — hits limit
        _create_debit_transactions(user, proj_a, 100)

        assert check_member_limit(user, org_a) is not None
        assert check_member_limit(user, org_b) is None


# ── Alert Tests ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSpendingAlerts:
    def test_member_alert_fires_at_threshold(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import maybe_send_spending_alert

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(
            organization=org,
            member_monthly_credit_limit=1000,
            alert_threshold_percent=80,
        )
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 800)  # 80% of 1000

        conv = Conversation.objects.create(user=member, title="conv", project=project)
        maybe_send_spending_alert(member, conv)

        alerts = Notification.objects.filter(
            type=NotificationType.SPENDING_ALERT,
            user_id=owner.id,
        )
        assert alerts.count() == 1
        assert "spending alert" in alerts.first().title.lower()

    def test_project_alert_fires_at_threshold(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import maybe_send_spending_alert

        org, owner, member = _make_org_with_member()
        project = _make_project_in_org(org, member)
        ProjectBudget.objects.create(
            project=project,
            monthly_credit_limit=1000,
            alert_threshold_percent=50,
            current_month_usage=500,
        )

        conv = Conversation.objects.create(user=member, title="conv", project=project)
        maybe_send_spending_alert(member, conv)

        alerts = Notification.objects.filter(
            type=NotificationType.SPENDING_ALERT,
            user_id=owner.id,
            title__icontains="budget",
        )
        assert alerts.count() == 1

    def test_no_alert_below_threshold(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import maybe_send_spending_alert

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(
            organization=org,
            member_monthly_credit_limit=10000,
            alert_threshold_percent=80,
        )
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 100)  # 1% of 10000

        conv = Conversation.objects.create(user=member, title="conv", project=project)
        maybe_send_spending_alert(member, conv)

        assert (
            Notification.objects.filter(type=NotificationType.SPENDING_ALERT).count()
            == 0
        )

    def test_personal_run_no_alert(self):
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import maybe_send_spending_alert

        user = UserFactory()
        conv = Conversation.objects.create(user=user, title="personal")
        maybe_send_spending_alert(user, conv)

        assert (
            Notification.objects.filter(type=NotificationType.SPENDING_ALERT).count()
            == 0
        )

    def test_alert_deduplication(self):
        """Duplicate alert for same title/user is not created (get_or_create)."""
        from apps.storage.models import Conversation
        from apps.workspace.cost_controls import maybe_send_spending_alert

        org, owner, member = _make_org_with_member()
        OrgCostPolicy.objects.create(
            organization=org,
            member_monthly_credit_limit=100,
            alert_threshold_percent=50,
        )
        project = _make_project_in_org(org, member)
        _create_debit_transactions(member, project, 80)

        conv = Conversation.objects.create(user=member, title="conv", project=project)
        maybe_send_spending_alert(member, conv)
        maybe_send_spending_alert(member, conv)  # second call

        alerts = Notification.objects.filter(
            type=NotificationType.SPENDING_ALERT,
            user_id=owner.id,
        )
        # get_or_create deduplicates on (user, type, title)
        assert alerts.filter(title__icontains="spending alert").count() == 1


# ── Monthly Reset Tests ──────────────────────────────────────────────────────


@pytest.mark.django_db
class TestMonthlyReset:
    def test_reset_zeroes_usage(self):
        from apps.workspace.tasks import reset_project_budgets_monthly

        user = UserFactory()
        p1 = Project.objects.create(title="P1", user=user)
        p2 = Project.objects.create(title="P2", user=user)
        ProjectBudget.objects.create(
            project=p1, monthly_credit_limit=1000, current_month_usage=750
        )
        ProjectBudget.objects.create(
            project=p2, monthly_credit_limit=2000, current_month_usage=1500
        )

        reset_project_budgets_monthly()

        assert ProjectBudget.objects.get(project=p1).current_month_usage == 0
        assert ProjectBudget.objects.get(project=p2).current_month_usage == 0

    def test_reset_skips_zero_usage(self):
        from apps.workspace.tasks import reset_project_budgets_monthly

        user = UserFactory()
        p1 = Project.objects.create(title="P1", user=user)
        ProjectBudget.objects.create(
            project=p1, monthly_credit_limit=1000, current_month_usage=0
        )

        reset_project_budgets_monthly()
        assert ProjectBudget.objects.get(project=p1).current_month_usage == 0

    def test_beat_schedule_entry(self):
        from django.conf import settings

        entry = settings.CELERY_BEAT_SCHEDULE.get("reset-project-budgets-monthly")
        assert entry is not None
        assert entry["task"] == "apps.workspace.tasks.reset_project_budgets_monthly"


# ── API Tests ────────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCostPolicyAPI:
    def _auth_client(self, user):
        from rest_framework.authtoken.models import Token

        token, _ = Token.objects.get_or_create(user=user)
        return Client(headers={"authorization": f"Bearer {token.key}"})

    def test_update_cost_policy_admin(self):
        org, owner, _ = _make_org_with_member()
        client = self._auth_client(owner)

        resp = client.patch(
            f"/api/v1/workspace/organizations/{org.id}/cost-policy",
            data='{"member_monthly_credit_limit": 5000, "alert_threshold_percent": 70}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_monthly_credit_limit"] == 5000
        assert data["alert_threshold_percent"] == 70

    def test_update_cost_policy_member_forbidden(self):
        org, _, member = _make_org_with_member()
        client = self._auth_client(member)

        resp = client.patch(
            f"/api/v1/workspace/organizations/{org.id}/cost-policy",
            data='{"member_monthly_credit_limit": 100}',
            content_type="application/json",
        )
        assert resp.status_code == 401  # UnauthorizedAccessError → 401

    def test_get_cost_status(self):
        org, owner, member = _make_org_with_member()
        project = _make_project_in_org(org, member)
        OrgCostPolicy.objects.create(organization=org, member_monthly_credit_limit=5000)
        _create_debit_transactions(member, project, 200)

        client = self._auth_client(owner)
        resp = client.get(
            f"/api/v1/workspace/organizations/{org.id}/cost-status",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_monthly_credit_limit"] == 5000
        assert len(data["members"]) == 2  # owner + member
        assert len(data["projects"]) == 1

    def test_cost_status_not_found(self):
        user = UserFactory()
        client = self._auth_client(user)
        resp = client.get(
            "/api/v1/workspace/organizations/00000000-0000-0000-0000-000000000000/cost-status",
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestProjectBudgetAPI:
    def _auth_client(self, user):
        from rest_framework.authtoken.models import Token

        token, _ = Token.objects.get_or_create(user=user)
        return Client(headers={"authorization": f"Bearer {token.key}"})

    def test_set_project_budget(self):
        org, owner, _ = _make_org_with_member()
        project = _make_project_in_org(org, owner)
        client = self._auth_client(owner)

        resp = client.patch(
            f"/api/v1/spaces/projects/{project.id}/budget",
            data='{"monthly_credit_limit": 3000}',
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["monthly_credit_limit"] == 3000
        assert data["current_month_usage"] == 0

    def test_budget_non_org_project_forbidden(self):
        user = UserFactory()
        project = Project.objects.create(title="Personal", user=user)
        client = self._auth_client(user)

        resp = client.patch(
            f"/api/v1/spaces/projects/{project.id}/budget",
            data='{"monthly_credit_limit": 1000}',
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_budget_member_forbidden(self):
        org, _, member = _make_org_with_member()
        project = _make_project_in_org(org, member)
        client = self._auth_client(member)

        resp = client.patch(
            f"/api/v1/spaces/projects/{project.id}/budget",
            data='{"monthly_credit_limit": 1000}',
            content_type="application/json",
        )
        assert resp.status_code == 401  # UnauthorizedAccessError → 401
