"""Cost control enforcement and spending alert utilities.

Provides functions to check per-member credit limits and per-project budgets
before agent runs start, and to fire spending alerts when thresholds are crossed.
"""

import logging
from datetime import datetime

from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def get_member_monthly_usage(user, org, month_start: datetime | None = None) -> int:
    """Return total credits consumed by *user* in *org*'s projects this month.

    Credits are counted as the absolute value of debit CreditTransactions linked
    to agent runs in org-scoped projects.
    """
    from apps.billing.models import CreditTransaction

    if month_start is None:
        now = timezone.now()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    result = CreditTransaction.objects.filter(
        wallet__user=user,
        amount__lt=0,
        created_at__gte=month_start,
        hold__run__conversation__project__organization=org,
    ).aggregate(total=Sum("amount"))
    return abs(result["total"] or 0)


def check_member_limit(user, org) -> str | None:
    """Check if user has exceeded their org's member monthly credit limit.

    Returns an error message if the limit is exceeded, or None if OK.
    """
    from apps.workspace.models import OrgCostPolicy

    try:
        policy = org.cost_policy
    except OrgCostPolicy.DoesNotExist:
        return None

    limit = policy.member_monthly_credit_limit
    if limit is None:
        return None

    usage = get_member_monthly_usage(user, org)
    if usage >= limit:
        return "Monthly credit limit reached for this organization"
    return None


def check_project_budget(project) -> str | None:
    """Check if a project has exhausted its monthly budget.

    Returns an error message if the budget is exceeded, or None if OK.
    """
    from apps.spaces.models import ProjectBudget

    try:
        budget = project.budget
    except ProjectBudget.DoesNotExist:
        return None

    if budget.monthly_credit_limit is None:
        return None

    if budget.current_month_usage >= budget.monthly_credit_limit:
        return "Project budget exhausted for this month"
    return None


def check_org_cost_limits(conv, user) -> str | None:
    """Check all org cost limits for a conversation's project context.

    Returns an error message string if any limit is breached, or None if all OK.
    Personal runs (no project or no org) are never blocked.
    """
    project = getattr(conv, "project", None)
    if project is None:
        return None

    org = getattr(project, "organization", None)
    if org is None:
        return None

    # Check member monthly limit
    member_error = check_member_limit(user, org)
    if member_error is not None:
        return member_error

    # Check project budget
    project_error = check_project_budget(project)
    if project_error is not None:
        return project_error

    return None


def maybe_send_spending_alert(user, conv) -> None:
    """Fire spending alert notifications if thresholds are crossed.

    Checks both member-level and project-level thresholds after a run starts.
    Alerts are sent to all org admins/owners. Runs in a try/except so it never
    blocks the agent run.
    """
    try:
        _send_spending_alerts_inner(user, conv)
    except Exception:
        logger.warning("Spending alert check failed", exc_info=True)


def _send_spending_alerts_inner(user, conv) -> None:
    from apps.spaces.models import ProjectBudget
    from apps.workspace.models import (
        OrganizationRole,
        OrgCostPolicy,
    )

    project = getattr(conv, "project", None)
    if project is None:
        return

    org = getattr(project, "organization", None)
    if org is None:
        return

    admin_users = list(
        org.memberships.filter(
            role__in=[OrganizationRole.ADMIN, OrganizationRole.OWNER]
        ).values_list("user_id", flat=True)
    )
    if not admin_users:
        return

    # Member threshold alert
    try:
        policy = org.cost_policy
    except OrgCostPolicy.DoesNotExist:
        policy = None

    if policy and policy.member_monthly_credit_limit:
        usage = get_member_monthly_usage(user, org)
        threshold = (
            policy.member_monthly_credit_limit * policy.alert_threshold_percent / 100
        )
        if usage >= threshold:
            user_email = getattr(user, "email", str(user.id))
            pct = round(usage / policy.member_monthly_credit_limit * 100)
            _notify_admins(
                admin_users,
                title=f"Member spending alert: {user_email}",
                body=f"{user_email} has used {pct}% of their monthly credit limit in {org.name}.",
                data={
                    "organization_id": str(org.id),
                    "user_id": user.id,
                    "usage": usage,
                    "limit": policy.member_monthly_credit_limit,
                    "alert_type": "member_limit",
                },
            )

    # Project threshold alert
    try:
        budget = project.budget
    except ProjectBudget.DoesNotExist:
        budget = None

    if budget and budget.monthly_credit_limit:
        threshold = budget.monthly_credit_limit * budget.alert_threshold_percent / 100
        if budget.current_month_usage >= threshold:
            pct = round(budget.current_month_usage / budget.monthly_credit_limit * 100)
            _notify_admins(
                admin_users,
                title=f"Project budget alert: {project.title}",
                body=f"Project '{project.title}' has used {pct}% of its monthly budget in {org.name}.",
                data={
                    "organization_id": str(org.id),
                    "project_id": str(project.id),
                    "usage": budget.current_month_usage,
                    "limit": budget.monthly_credit_limit,
                    "alert_type": "project_budget",
                },
            )


def _notify_admins(admin_user_ids: list, title: str, body: str, data: dict) -> None:
    """Create in-app spending alert notifications for org admins."""
    from apps.workspace.models import Notification, NotificationType

    for uid in admin_user_ids:
        Notification.objects.get_or_create(
            user_id=uid,
            type=NotificationType.SPENDING_ALERT,
            title=title,
            defaults={"body": body, "data": data},
        )
