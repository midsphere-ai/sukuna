"""Celery background tasks for billing operations.

Includes scheduled tasks for expiring subscriptions, retrying failed payments,
processing plan changes, syncing with Dodo Payments, managing trials, and reporting.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone

from .models import (
    FailedPayment,
    Payment,
    SubscriptionHistory,
    SubscriptionPlan,
    TrialPeriod,
    UserSubscription,
    WebhookEvent,
)

logger = logging.getLogger(__name__)


def _get_dodo_client():
    """Create a Dodo Payments client on demand (avoids import-time settings access)."""
    from dodopayments import DodoPayments

    return DodoPayments(
        bearer_token=settings.DODO_PAYMENTS_API_KEY,
        environment=settings.DODO_PAYMENTS_ENVIRONMENT,
    )


# 1. CHECK AND EXPIRE SUBSCRIPTIONS
@shared_task
def check_expired_subscriptions():
    """
    Run every hour to check for expired subscriptions
    Schedule: '0 * * * *' (every hour)
    """
    now = timezone.now()

    expired_subscriptions = UserSubscription.objects.filter(
        status="active", end_date__lt=now, auto_renew=False
    )

    count = 0
    for subscription in expired_subscriptions:
        if subscription.dodo_subscription_id:
            try:
                dodo_client = _get_dodo_client()
                dodo_sub = dodo_client.subscriptions.retrieve(
                    subscription.dodo_subscription_id
                )
                if dodo_sub.status not in ("cancelled", "expired"):
                    dodo_client.subscriptions.update(
                        subscription.dodo_subscription_id,
                        status="cancelled",
                    )
            except Exception as e:
                logger.error(f"Error cancelling subscription {subscription.id}: {e}")

        old_plan = subscription.plan
        subscription.status = "expired"
        subscription.save()

        SubscriptionHistory.objects.get_or_create(
            subscription=subscription,
            action="expired",
            old_plan=old_plan,
            defaults={"notes": "Subscription expired automatically"},
        )

        # Downgrade to free plan
        free_plan = SubscriptionPlan.objects.filter(tier="free").first()
        if free_plan:
            subscription.plan = free_plan
            subscription.dodo_subscription_id = None
            subscription.end_date = None
            subscription.status = "active"
            subscription.save()

        send_subscription_email(subscription.user, "expired", subscription=subscription)

        count += 1

    return f"Expired {count} subscriptions"


# 2. CHECK SUBSCRIPTIONS EXPIRING SOON
@shared_task
def notify_expiring_subscriptions():
    """
    Run daily to notify users of expiring subscriptions
    Schedule: '0 9 * * *' (9 AM daily)
    """
    now = timezone.now()
    three_days_later = now + timedelta(days=3)

    expiring_soon = UserSubscription.objects.filter(
        status="active", end_date__range=(now, three_days_later), auto_renew=False
    )

    count = 0
    for subscription in expiring_soon:
        days_remaining = max(0, (subscription.end_date - now).days)

        send_subscription_email(
            subscription.user,
            "expiring_soon",
            subscription=subscription,
            days_remaining=days_remaining,
        )
        count += 1

    return f"Notified {count} users about expiring subscriptions"


# 3. PROCESS SCHEDULED PLAN CHANGES
@shared_task
def process_scheduled_plan_changes():
    """
    Run daily to process scheduled plan changes
    Schedule: '0 0 * * *' (midnight daily)
    """
    now = timezone.now()

    scheduled_changes = UserSubscription.objects.filter(
        scheduled_plan_change__isnull=False,
        scheduled_change_date__lte=now,
        status="active",
    )

    count = 0
    for subscription in scheduled_changes:
        old_plan = subscription.plan
        new_plan = subscription.scheduled_plan_change

        if new_plan.tier == "free":
            # Cancel Dodo subscription and downgrade
            if subscription.dodo_subscription_id:
                try:
                    dodo_client = _get_dodo_client()
                    dodo_client.subscriptions.update(
                        subscription.dodo_subscription_id,
                        cancel_at_next_billing_date=True,
                    )
                except Exception as e:
                    logger.error(f"Error cancelling old subscription: {e}")

            subscription.plan = new_plan
            subscription.scheduled_plan_change = None
            subscription.scheduled_change_date = None
            subscription.dodo_subscription_id = None
            subscription.end_date = None
            subscription.save()
        else:
            # Change plan via Dodo
            if subscription.dodo_subscription_id:
                try:
                    dodo_client = _get_dodo_client()
                    dodo_client.subscriptions.change_plan(
                        subscription_id=subscription.dodo_subscription_id,
                        product_id=new_plan.dodo_product_id,
                        proration_billing_mode="do_not_bill",
                        quantity=1,
                    )
                    subscription.plan = new_plan
                    subscription.scheduled_plan_change = None
                    subscription.scheduled_change_date = None
                    subscription.save()
                except Exception as e:
                    logger.error(f"Error changing plan: {e}")
                    continue
            else:
                subscription.plan = new_plan
                subscription.scheduled_plan_change = None
                subscription.scheduled_change_date = None
                subscription.save()

        # Log history
        old_price = old_plan.price if old_plan else 0
        new_price = new_plan.price if new_plan else 0
        action = "upgraded" if new_price > old_price else "downgraded"
        SubscriptionHistory.objects.get_or_create(
            subscription=subscription,
            action=action,
            old_plan=old_plan,
            new_plan=new_plan,
            defaults={"notes": "Scheduled plan change executed"},
        )

        send_subscription_email(
            subscription.user,
            action,
            subscription=subscription,
            old_plan=old_plan,
            new_plan=new_plan,
        )

        count += 1

    return f"Processed {count} scheduled plan changes"


# 4. RETRY FAILED PAYMENTS (DUNNING)
@shared_task
def retry_failed_payments():
    """
    Run daily to retry failed payments
    Schedule: '0 10 * * *' (10 AM daily)
    """
    now = timezone.now()

    failed_payments = FailedPayment.objects.filter(
        resolved=False, retry_count__lt=3, next_retry_at__lte=now
    )

    count = 0
    for failed_payment in failed_payments:
        try:
            subscription = failed_payment.subscription

            if subscription.status != "active":
                failed_payment.resolved = True
                failed_payment.save()
                continue

            if subscription.dodo_subscription_id:
                send_subscription_email(
                    subscription.user,
                    "payment_retry",
                    subscription=subscription,
                    retry_count=failed_payment.retry_count + 1,
                )

            # Update retry info with exponential backoff
            failed_payment.retry_count += 1
            failed_payment.last_retry_at = now
            hours_until_next = 24 * failed_payment.retry_count
            failed_payment.next_retry_at = now + timedelta(hours=hours_until_next)
            failed_payment.save()

            count += 1

        except Exception as e:
            logger.error(f"Error retrying payment {failed_payment.id}: {e}")

    return f"Attempted retry for {count} failed payments"


# 5. END GRACE PERIODS
@shared_task
def end_grace_periods():
    """
    Run hourly to end grace periods and cancel subscriptions
    Schedule: '30 * * * *' (every hour at 30 minutes)
    """
    now = timezone.now()

    expired_grace = UserSubscription.objects.filter(
        grace_period_end__lt=now, grace_period_end__isnull=False, status="active"
    )

    count = 0
    for subscription in expired_grace:
        if subscription.dodo_subscription_id:
            try:
                dodo_client = _get_dodo_client()
                dodo_sub = dodo_client.subscriptions.retrieve(
                    subscription.dodo_subscription_id
                )
                if dodo_sub.status not in ("cancelled", "expired"):
                    dodo_client.subscriptions.update(
                        subscription.dodo_subscription_id,
                        status="cancelled",
                    )
            except Exception as e:
                logger.error(f"Error cancelling subscription: {e}")

        old_plan = subscription.plan
        subscription.status = "cancelled"
        subscription.grace_period_end = None
        subscription.save()

        SubscriptionHistory.objects.get_or_create(
            subscription=subscription,
            action="cancelled",
            old_plan=old_plan,
            defaults={"notes": "Cancelled after grace period expired"},
        )

        # Downgrade to free
        free_plan = SubscriptionPlan.objects.filter(tier="free").first()
        if free_plan:
            subscription.plan = free_plan
            subscription.dodo_subscription_id = None
            subscription.status = "active"
            subscription.save()

        send_subscription_email(
            subscription.user, "cancelled_after_grace", subscription=subscription
        )

        count += 1

    return f"Ended grace period for {count} subscriptions"


# 6. CONVERT TRIAL SUBSCRIPTIONS
@shared_task
def check_trial_conversions():
    """
    Run daily to check for trial periods ending
    Schedule: '0 8 * * *' (8 AM daily)
    """
    now = timezone.now()
    tomorrow = now + timedelta(days=1)

    trials_ending = TrialPeriod.objects.filter(
        trial_end__range=(now, tomorrow), converted_to_paid=False
    )

    reminder_count = 0
    for trial in trials_ending:
        send_subscription_email(
            trial.subscription.user,
            "trial_ending",
            subscription=trial.subscription,
            trial=trial,
        )
        reminder_count += 1

    expired_trials = TrialPeriod.objects.filter(
        trial_end__lt=now, converted_to_paid=False
    )

    expired_count = 0
    for trial in expired_trials:
        subscription = trial.subscription

        if subscription.status == "active" and not trial.converted_to_paid:
            subscription.status = "expired"
            subscription.save()

            free_plan = SubscriptionPlan.objects.filter(tier="free").first()
            if free_plan:
                subscription.plan = free_plan
                subscription.status = "active"
                subscription.save()

            send_subscription_email(
                subscription.user, "trial_expired", subscription=subscription
            )

            expired_count += 1
            trial.converted_to_paid = True
            trial.save()

    return f"Sent {reminder_count} trial reminders, expired {expired_count} trials"


# 7. SYNC WITH DODO PAYMENTS
@shared_task
def sync_subscriptions_with_dodo():
    """
    Run daily to sync subscription status with Dodo Payments
    Schedule: '0 2 * * *' (2 AM daily)
    """
    active_subscriptions = UserSubscription.objects.filter(
        status="active", dodo_subscription_id__isnull=False
    )

    synced_count = 0
    error_count = 0

    for subscription in active_subscriptions:
        try:
            dodo_client = _get_dodo_client()
            dodo_sub = dodo_client.subscriptions.retrieve(
                subscription.dodo_subscription_id
            )

            dodo_status = dodo_sub.status

            status_mapping = {
                "active": "active",
                "cancelled": "cancelled",
                "on_hold": "cancelled",
                "expired": "expired",
            }

            local_status = status_mapping.get(dodo_status, subscription.status)

            if local_status != subscription.status:
                old_status = subscription.status
                subscription.status = local_status
                subscription.save()

                SubscriptionHistory.objects.get_or_create(
                    subscription=subscription,
                    action="synced",
                    defaults={
                        "notes": f"Status synced from Dodo: {old_status} -> {local_status}"
                    },
                )

                synced_count += 1

        except Exception as e:
            logger.error(f"Error syncing subscription {subscription.id}: {e}")
            error_count += 1

    return f"Synced {synced_count} subscriptions, {error_count} errors"


# 8. CLEANUP OLD DATA
@shared_task
def cleanup_old_data():
    """
    Run weekly to cleanup old records
    Schedule: '0 3 * * 0' (3 AM every Sunday)
    """
    ninety_days_ago = timezone.now() - timedelta(days=90)
    deleted_webhooks = WebhookEvent.objects.filter(
        created_at__lt=ninety_days_ago, processed=True
    ).delete()

    sixty_days_ago = timezone.now() - timedelta(days=60)
    deleted_payments = FailedPayment.objects.filter(
        created_at__lt=sixty_days_ago, resolved=True
    ).delete()

    return f"Deleted {deleted_webhooks[0]} webhook events, {deleted_payments[0]} failed payments"


# 9. GENERATE SUBSCRIPTION REPORTS
@shared_task
def generate_daily_report():
    """
    Run daily to generate subscription reports
    Schedule: '0 23 * * *' (11 PM daily)
    """
    from django.db.models import Sum

    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    report = {
        "date": today_start.date(),
        "new_subscriptions": UserSubscription.objects.filter(
            created_at__gte=today_start
        ).count(),
        "cancelled_subscriptions": UserSubscription.objects.filter(
            status="cancelled", updated_at__gte=today_start
        ).count(),
        "failed_payments": FailedPayment.objects.filter(
            created_at__gte=today_start
        ).count(),
        "total_revenue": Payment.objects.filter(
            created_at__gte=today_start, status="captured"
        ).aggregate(total=Sum("amount"))["total"]
        or 0,
    }

    admin_email = getattr(settings, "ADMIN_EMAIL", None)
    if admin_email:
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
        send_mail(
            subject=f"Daily Subscription Report - {today_start.date()}",
            message=f"""
            Daily Subscription Report

            Date: {report["date"]}
            New Subscriptions: {report["new_subscriptions"]}
            Cancelled: {report["cancelled_subscriptions"]}
            Failed Payments: {report["failed_payments"]}
            Total Revenue: ${report["total_revenue"]}
            """,
            from_email=from_email,
            recipient_list=[admin_email],
        )

    return f"Generated report for {today_start.date()}"


# HELPER FUNCTION
def send_subscription_email(user, event_type, **context):
    """Send subscription-related emails based on event type."""
    templates = {
        "expired": "emails/subscription_expired.html",
        "expiring_soon": "emails/subscription_expiring.html",
        "upgraded": "emails/subscription_upgraded.html",
        "downgraded": "emails/subscription_downgraded.html",
        "payment_retry": "emails/payment_retry.html",
        "cancelled_after_grace": "emails/cancelled_after_grace.html",
        "trial_ending": "emails/trial_ending.html",
        "trial_expired": "emails/trial_expired.html",
    }

    subjects = {
        "expired": "Your subscription has expired",
        "expiring_soon": "Your subscription is expiring soon",
        "upgraded": "Subscription upgraded successfully",
        "downgraded": "Subscription plan changed",
        "payment_retry": "Payment retry attempt",
        "cancelled_after_grace": "Subscription cancelled",
        "trial_ending": "Your trial is ending soon",
        "trial_expired": "Your trial has expired",
    }

    template = templates.get(event_type)
    subject = subjects.get(event_type)

    if template and subject:
        try:
            html_content = render_to_string(template, context)
            from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
            send_mail(
                subject=subject,
                message="",
                from_email=from_email,
                recipient_list=[user.email],
                html_message=html_content,
            )
        except Exception as e:
            logger.error(f"Error sending email to {user.email}: {e}")
