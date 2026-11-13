"""
Dashboard callback for Sukuna Admin.
This module provides the dashboard_callback function that populates
the admin dashboard with comprehensive statistics and analytics.
"""

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.utils import timezone


def dashboard_callback(request, context):
    """
    Callback to prepare custom variables for the admin dashboard.
    This function is called by Unfold to populate the admin/index.html template.
    """
    from apps.agents.models import (
        E2bSandbox,
        UserCustomMCPConfig,
    )
    from apps.billing.models import (
        CustomerSupportTicket,
        FailedPayment,
        Payment,
        PromoCoupon,
        SubscriptionPause,
        SubscriptionPlan,
        TrialPeriod,
        UserSubscription,
        WebhookEvent,
    )
    from apps.spaces.models import Project
    from apps.storage.models import (
        AgentRun,
        Conversation,
        MarketplaceAddon,
        StoredFile,
        UserMarketplaceAddons,
    )
    from apps.users.models import User

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    thirty_days_ago = now - timedelta(days=30)
    twenty_four_hours_ago = now - timedelta(hours=24)

    # =====================
    # USER STATISTICS
    # =====================
    total_users = User.objects.count()
    new_users_today = User.objects.filter(date_joined__gte=today_start).count()
    new_users_week = User.objects.filter(date_joined__gte=week_ago).count()

    # Users with conversations in last 7 days
    active_users_week = (
        Conversation.objects.filter(date_created__gte=week_ago)
        .values("user")
        .distinct()
        .count()
    )
    active_user_rate = round(
        (active_users_week / total_users * 100) if total_users > 0 else 0, 1
    )

    # Recent users with conversation count
    recent_users = User.objects.annotate(
        conversation_count=Count("speaking_to")
    ).order_by("-date_joined")[:10]

    # =====================
    # CONVERSATION STATISTICS
    # =====================
    total_conversations = Conversation.objects.count()
    ongoing_conversations = (
        AgentRun.objects.filter(status__in=["pending", "running"])
        .values("conversation")
        .distinct()
        .count()
    )
    error_conversations = (
        AgentRun.objects.filter(status="failed")
        .values("conversation")
        .distinct()
        .count()
    )
    completed_conversations = (
        total_conversations - ongoing_conversations - error_conversations
    )
    recent_conversations = Conversation.objects.select_related("user").order_by(
        "-date_created"
    )[:10]

    # Conversation success rate (not errored)
    conversation_success_rate = round(
        ((total_conversations - error_conversations) / total_conversations * 100)
        if total_conversations > 0
        else 0,
        1,
    )

    # =====================
    # TASK STATISTICS
    # =====================
    total_tasks = AgentRun.objects.count()
    tasks_today = AgentRun.objects.filter(created_at__gte=today_start).count()
    tasks_week = AgentRun.objects.filter(created_at__gte=week_ago).count()
    recent_tasks = AgentRun.objects.select_related("conversation", "user").order_by(
        "-created_at"
    )[:10]

    # Average tasks per user
    avg_tasks_per_user = round(total_tasks / total_users, 1) if total_users > 0 else 0

    # =====================
    # SUBSCRIPTION STATISTICS
    # =====================
    active_subscriptions = UserSubscription.objects.filter(status="active").count()
    trial_subscriptions = TrialPeriod.objects.filter(
        trial_end__gte=now, converted_to_paid=False
    ).count()
    paused_subscriptions = SubscriptionPause.objects.filter(is_active=True).count()

    # Trial conversion rate
    total_trials = TrialPeriod.objects.count()
    converted_trials = TrialPeriod.objects.filter(converted_to_paid=True).count()
    trial_conversion_rate = round(
        (converted_trials / total_trials * 100) if total_trials > 0 else 0, 1
    )

    # Churn rate (cancelled in last 30 days / active at start of period)
    cancelled_30d = UserSubscription.objects.filter(
        status="cancelled", updated_at__gte=thirty_days_ago
    ).count()
    churn_rate = round(
        (cancelled_30d / active_subscriptions * 100) if active_subscriptions > 0 else 0,
        1,
    )

    # =====================
    # PAYMENT STATISTICS
    # =====================
    total_payments = Payment.objects.filter(status="captured").count()
    total_revenue_val = (
        Payment.objects.filter(status="captured").aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    total_revenue = f"{total_revenue_val:.2f}"
    recent_payments = Payment.objects.select_related("user").order_by("-created_at")[
        :10
    ]
    failed_payments = FailedPayment.objects.filter(resolved=False).count()

    # MRR calculation (sum of active subscription plan prices)
    mrr_val = (
        UserSubscription.objects.filter(status="active", plan__isnull=False).aggregate(
            total=Sum("plan__price")
        )["total"]
        or 0
    )
    mrr = f"{mrr_val:.2f}"

    # Active coupons
    active_coupons = PromoCoupon.objects.filter(
        is_active=True, valid_until__gte=now
    ).count()

    # =====================
    # SANDBOX STATISTICS
    # =====================
    active_sandboxes = (
        E2bSandbox.objects.get_queryset()
        .by_state(E2bSandbox.SandboxState.READY)
        .count()
    )
    total_sandbox_seconds = (
        E2bSandbox.objects.aggregate(total=Sum("usage_in_seconds"))["total"] or 0
    )
    total_sandbox_hours = round(total_sandbox_seconds / 3600, 1)

    # =====================
    # FILE STATISTICS
    # =====================
    total_files = StoredFile.objects.count()
    total_file_size = StoredFile.objects.aggregate(total=Sum("size"))["total"] or 0
    total_file_size_mb = round(total_file_size / (1024 * 1024), 2)

    # =====================
    # SYSTEM HEALTH
    # =====================
    webhook_events_24h = WebhookEvent.objects.filter(
        created_at__gte=twenty_four_hours_ago
    ).count()
    failed_webhooks_24h = WebhookEvent.objects.filter(
        created_at__gte=twenty_four_hours_ago, processed=False
    ).count()
    total_addons = MarketplaceAddon.objects.count()
    user_addon_connections = UserMarketplaceAddons.objects.filter(
        auth_complete=True
    ).count()
    total_mcp_configs = UserCustomMCPConfig.objects.count()
    total_spaces = Project.objects.count()

    # =====================
    # CUSTOMER SUPPORT STATISTICS
    # =====================
    total_support_tickets = CustomerSupportTicket.objects.count()
    open_tickets = CustomerSupportTicket.objects.filter(status="open").count()
    in_progress_tickets = CustomerSupportTicket.objects.filter(
        status="in_progress"
    ).count()
    resolved_tickets = CustomerSupportTicket.objects.filter(status="resolved").count()
    closed_tickets = CustomerSupportTicket.objects.filter(status="closed").count()
    tickets_today = CustomerSupportTicket.objects.filter(
        created_at__gte=today_start
    ).count()
    tickets_week = CustomerSupportTicket.objects.filter(
        created_at__gte=week_ago
    ).count()
    recent_tickets = CustomerSupportTicket.objects.select_related("user").order_by(
        "-created_at"
    )[:10]

    # =====================
    # CHART DATA - CONVERSATIONS (14 days)
    # =====================
    conv_chart_labels = []
    conv_chart_data = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = Conversation.objects.filter(
            date_created__gte=day_start, date_created__lt=day_end
        ).count()
        conv_chart_labels.append(day.strftime("%m/%d"))
        conv_chart_data.append(count)

    # =====================
    # CHART DATA - TASKS (14 days)
    # =====================
    task_chart_labels = []
    task_chart_data = []
    for i in range(13, -1, -1):
        day = now - timedelta(days=i)
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        count = AgentRun.objects.filter(
            created_at__gte=day_start, created_at__lt=day_end
        ).count()
        task_chart_labels.append(day.strftime("%m/%d"))
        task_chart_data.append(count)

    # =====================
    # PLAN DISTRIBUTION
    # =====================
    plan_distribution = (
        SubscriptionPlan.objects.annotate(
            user_count=Count(
                "usersubscription", filter=Q(usersubscription__status="active")
            )
        )
        .values("name", "user_count")
        .order_by("-user_count")
    )

    plan_labels = [p["name"] for p in plan_distribution] or ["None"]
    plan_data = [p["user_count"] for p in plan_distribution] or [0]

    plan_usage = [
        {"name": p["name"], "count": p["user_count"]} for p in plan_distribution
    ]

    context.update(
        {
            # User stats
            "total_users": total_users,
            "new_users_today": new_users_today,
            "new_users_week": new_users_week,
            "active_user_rate": active_user_rate,
            "recent_users": recent_users,
            # Conversation stats
            "total_conversations": total_conversations,
            "ongoing_conversations": ongoing_conversations,
            "error_conversations": error_conversations,
            "completed_conversations": completed_conversations,
            "recent_conversations": recent_conversations,
            "conversation_success_rate": conversation_success_rate,
            # Task stats
            "total_tasks": total_tasks,
            "tasks_today": tasks_today,
            "tasks_week": tasks_week,
            "recent_tasks": recent_tasks,
            "avg_tasks_per_user": avg_tasks_per_user,
            # Subscription stats
            "active_subscriptions": active_subscriptions,
            "trial_subscriptions": trial_subscriptions,
            "paused_subscriptions": paused_subscriptions,
            "trial_conversion_rate": trial_conversion_rate,
            "churn_rate": churn_rate,
            # Payment stats
            "total_payments": total_payments,
            "total_revenue": total_revenue,
            "recent_payments": recent_payments,
            "failed_payments": failed_payments,
            "mrr": mrr,
            "active_coupons": active_coupons,
            # Sandbox stats
            "active_sandboxes": active_sandboxes,
            "total_sandbox_hours": total_sandbox_hours,
            # File stats
            "total_files": total_files,
            "total_file_size_mb": total_file_size_mb,
            # System health
            "webhook_events_24h": webhook_events_24h,
            "failed_webhooks_24h": failed_webhooks_24h,
            "total_addons": total_addons,
            "user_addon_connections": user_addon_connections,
            "total_mcp_configs": total_mcp_configs,
            "total_spaces": total_spaces,
            # Chart data
            "conv_chart_labels": conv_chart_labels,
            "conv_chart_data": conv_chart_data,
            "task_chart_labels": task_chart_labels,
            "task_chart_data": task_chart_data,
            # Plan data
            "plan_labels": plan_labels,
            "plan_data": plan_data,
            "plan_usage": plan_usage,
            # Customer support stats
            "total_support_tickets": total_support_tickets,
            "open_tickets": open_tickets,
            "in_progress_tickets": in_progress_tickets,
            "resolved_tickets": resolved_tickets,
            "closed_tickets": closed_tickets,
            "tickets_today": tickets_today,
            "tickets_week": tickets_week,
            "recent_tickets": recent_tickets,
        }
    )

    return context
