"""Celery tasks for notification delivery — email, Slack, Discord.

Email delivery is batched: at most 1 email per 5 minutes per user via
a Redis timestamp check. SMTP failures retry 3× with exponential backoff.

Slack and Discord use incoming webhooks. Invalid webhook URLs are logged
and the task does not retry.
"""

import json
import logging
import urllib.error
import urllib.request

from celery import shared_task
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Email batching: max 1 email per user per 5 minutes
EMAIL_BATCH_WINDOW = 300  # seconds


def _email_batch_key(user_id: str) -> str:
    return f"notif_email_batch:{user_id}"


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
)
def send_notification_email(
    self,
    user_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict | None = None,
):
    """Send a notification email to a user, respecting batching window.

    Re-reads preferences at delivery time so preference changes between
    event creation and async delivery are honoured.
    """
    from apps.users.models import User
    from apps.workspace.models import NotificationPreference

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning("Notification email: user %s not found, skipping", user_id)
        return

    # Re-check preference at delivery time
    try:
        pref = NotificationPreference.objects.get(
            user=user, notification_type=notification_type
        )
        if not pref.email:
            logger.debug(
                "Email disabled for %s/%s at delivery time", user_id, notification_type
            )
            return
    except NotificationPreference.DoesNotExist:
        pass  # Default: email enabled

    # Batching: skip if we emailed this user recently
    batch_key = _email_batch_key(user_id)
    if cache.get(batch_key):
        logger.debug("Email batching: skipping for user %s (within window)", user_id)
        return

    # Send the email
    from django.conf import settings as django_settings
    from django.core.mail import send_mail

    try:
        user_email = user.email
    except Exception:
        logger.warning("Cannot read email for user %s, skipping", user_id)
        return

    subject = f"[Jatayu AI] {title}"
    message = (
        f"{title}\n\n"
        f"{body}\n\n"
        f"—\n"
        f"You can manage your notification preferences in Settings > Notifications.\n"
        f"Jatayu AI — https://app.midsphere.com"
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(
                django_settings, "DEFAULT_FROM_EMAIL", "noreply@midsphere.com"
            ),
            recipient_list=[user_email],
            fail_silently=False,
        )
        # Mark batch window
        cache.set(batch_key, "1", timeout=EMAIL_BATCH_WINDOW)
        logger.info("Notification email sent to user %s: %s", user_id, title)
    except Exception as exc:
        logger.exception("Failed to send notification email to user %s", user_id)
        raise self.retry(exc=exc)


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=10,
)
def send_webhook_notification(
    self,
    organization_id: str,
    notification_type: str,
    title: str,
    body: str,
    data: dict | None = None,
    send_slack: bool = False,
    send_discord: bool = False,
):
    """Send notification to Slack and/or Discord webhooks for an org."""
    data = data or {}

    if send_slack:
        _send_slack(organization_id, notification_type, title, body, data)

    if send_discord:
        _send_discord(organization_id, notification_type, title, body, data)


def _send_slack(org_id: str, notification_type: str, title: str, body: str, data: dict):
    """Post a notification to the org's Slack webhook as a formatted block message."""
    from apps.workspace.models import OrgSlackIntegration

    try:
        integration = OrgSlackIntegration.objects.get(
            organization_id=org_id, is_active=True
        )
    except OrgSlackIntegration.DoesNotExist:
        logger.debug("No active Slack integration for org %s", org_id)
        return

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body or "_No details_"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"Type: `{notification_type}`"},
                ],
            },
        ]
    }

    try:
        req = urllib.request.Request(
            integration.webhook_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Slack notification sent for org %s: %s", org_id, title)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        logger.warning("Slack webhook failed for org %s: %s", org_id, exc)


def _send_discord(
    org_id: str, notification_type: str, title: str, body: str, data: dict
):
    """Post a notification to the org's Discord webhook as an embed message."""
    from apps.workspace.models import OrgDiscordIntegration

    try:
        integration = OrgDiscordIntegration.objects.get(
            organization_id=org_id, is_active=True
        )
    except OrgDiscordIntegration.DoesNotExist:
        logger.debug("No active Discord integration for org %s", org_id)
        return

    payload = {
        "embeds": [
            {
                "title": title,
                "description": body or "No details",
                "color": 5814783,  # Midsphere blue
                "footer": {"text": f"Type: {notification_type}"},
            }
        ]
    }

    try:
        req = urllib.request.Request(
            integration.webhook_url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info("Discord notification sent for org %s: %s", org_id, title)
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        logger.warning("Discord webhook failed for org %s: %s", org_id, exc)


# ── Outbound Webhook Delivery ───────────────────────────────────────────────

# Retry delays: 1s, 10s, 60s
_WEBHOOK_RETRY_DELAYS = [1, 10, 60]
_WEBHOOK_MAX_RETRIES = 3
_WEBHOOK_AUTO_DISABLE_THRESHOLD = 10


def _hmac_signature(secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 hex digest for webhook signing."""
    import hashlib
    import hmac as hmac_mod

    return hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _format_slack_payload(event_type: str, data: dict, org_id: str) -> dict:
    """Format payload as Slack Block Kit message."""
    title = event_type.replace(".", " ").replace("_", " ").title()
    description = data.get("description", data.get("message", ""))
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🔔 {title}"},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": description or "_No details_"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Event: `{event_type}` | Org: `{org_id}`"},
            ],
        },
    ]
    # Add deep link button if conversation_id is present
    conversation_id = data.get("conversation_id")
    if conversation_id:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Conversation"},
                        "url": f"https://app.midsphere.com/conversations/{conversation_id}",
                    }
                ],
            }
        )
    return {"blocks": blocks}


def _format_discord_payload(event_type: str, data: dict, org_id: str) -> dict:
    """Format payload as Discord embed with color-coded sidebar."""
    title = event_type.replace(".", " ").replace("_", " ").title()
    description = data.get("description", data.get("message", ""))
    # Color coding: green=completed, red=failed, blue=info
    color_map = {
        "agent_run.completed": 0x2ECC71,  # green
        "agent_run.failed": 0xE74C3C,  # red
        "dlp.violation": 0xE74C3C,  # red
        "audit.security_event": 0xE74C3C,  # red
    }
    color = color_map.get(event_type, 0x3498DB)  # blue default
    return {
        "embeds": [
            {
                "title": title,
                "description": description or "No details",
                "color": color,
                "footer": {"text": f"Event: {event_type} | Org: {org_id}"},
            }
        ]
    }


@shared_task
def deliver_webhook_event(
    webhook_id: str,
    event_type: str,
    payload: dict,
    retry_count: int = 0,
):
    """Deliver a webhook event with HMAC signing, retry logic, and auto-disable.

    Retry schedule: 1s, 10s, 60s. After 10 consecutive failures the webhook
    is auto-disabled and an audit log entry is created.
    """
    import time

    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgWebhook, WebhookDeliveryLog

    try:
        webhook = OrgWebhook.objects.select_related("organization").get(pk=webhook_id)
    except OrgWebhook.DoesNotExist:
        logger.warning("Webhook %s not found, skipping delivery", webhook_id)
        return

    if not webhook.is_active:
        logger.debug("Webhook %s is inactive, skipping delivery", webhook_id)
        return

    # Build payload based on destination type
    org_id = str(webhook.organization_id)
    if webhook.destination_type == "slack":
        body_dict = _format_slack_payload(event_type, payload.get("data", {}), org_id)
    elif webhook.destination_type == "discord":
        body_dict = _format_discord_payload(event_type, payload.get("data", {}), org_id)
    else:
        body_dict = payload

    body_bytes = json.dumps(body_dict).encode()
    signature = _hmac_signature(webhook.secret, body_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-Midsphere-Signature": signature,
        "X-Midsphere-Event": event_type,
    }

    start_time = time.monotonic()
    status_code = None
    error_msg = ""
    success = False

    try:
        req = urllib.request.Request(
            webhook.url,
            data=body_bytes,
            headers=headers,
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        status_code = resp.status
        success = 200 <= status_code < 300
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        error_msg = str(exc)
    except (urllib.error.URLError, OSError) as exc:
        error_msg = str(exc)

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # Log delivery attempt
    WebhookDeliveryLog.objects.create(
        webhook=webhook,
        event_type=event_type,
        status_code=status_code,
        response_time_ms=elapsed_ms,
        success=success,
        error_message=error_msg,
    )

    # Prune old logs: keep last 100
    excess_ids = (
        WebhookDeliveryLog.objects.filter(webhook=webhook)
        .order_by("-created_at")
        .values_list("pk", flat=True)[100:]
    )
    if excess_ids:
        WebhookDeliveryLog.objects.filter(pk__in=list(excess_ids)).delete()

    if success:
        # Reset failure count on success
        if webhook.failure_count > 0:
            OrgWebhook.objects.filter(pk=webhook.pk).update(failure_count=0)
        logger.info(
            "Webhook %s delivered %s (HTTP %s)", webhook_id, event_type, status_code
        )
        return

    # Increment failure count
    new_failure_count = webhook.failure_count + 1
    OrgWebhook.objects.filter(pk=webhook.pk).update(failure_count=new_failure_count)

    # Auto-disable after threshold
    if new_failure_count >= _WEBHOOK_AUTO_DISABLE_THRESHOLD:
        OrgWebhook.objects.filter(pk=webhook.pk).update(is_active=False)
        AuditLog.log(
            action="webhook_auto_disabled",
            resource_type="webhook",
            resource_id=str(webhook.pk),
            metadata={
                "organization_id": org_id,
                "url": webhook.url,
                "failure_count": new_failure_count,
            },
        )
        logger.warning(
            "Webhook %s auto-disabled after %d consecutive failures",
            webhook_id,
            new_failure_count,
        )
        return

    # Retry with backoff
    if retry_count < _WEBHOOK_MAX_RETRIES:
        delay = _WEBHOOK_RETRY_DELAYS[retry_count]
        deliver_webhook_event.apply_async(
            args=[webhook_id, event_type, payload, retry_count + 1],
            countdown=delay,
        )
        logger.info(
            "Webhook %s delivery failed, retrying in %ds (attempt %d/%d)",
            webhook_id,
            delay,
            retry_count + 1,
            _WEBHOOK_MAX_RETRIES,
        )


def fire_webhook_event(organization_id: str, event_type: str, data: dict):
    """Dispatch a webhook event to all active webhooks subscribed to the event type.

    Called from application code when events occur. Enqueues delivery tasks
    for each matching webhook.
    """
    from apps.workspace.models import OrgWebhook

    webhooks = OrgWebhook.objects.filter(
        organization_id=organization_id,
        is_active=True,
    )

    from django.utils import timezone as tz

    payload = {
        "event_type": event_type,
        "timestamp": tz.now().isoformat(),
        "data": data,
        "organization_id": organization_id,
    }

    for webhook in webhooks:
        if event_type in (webhook.events or []):
            deliver_webhook_event.delay(
                str(webhook.pk),
                event_type,
                payload,
            )


@shared_task
def send_test_webhook_event(webhook_id: str):
    """Send a test event to a webhook to verify it's reachable."""
    from apps.workspace.models import OrgWebhook

    try:
        webhook = OrgWebhook.objects.select_related("organization").get(pk=webhook_id)
    except OrgWebhook.DoesNotExist:
        return {"ok": False, "message": "Webhook not found"}

    from django.utils import timezone as tz

    payload = {
        "event_type": "test",
        "timestamp": tz.now().isoformat(),
        "data": {"message": "This is a test webhook event from Jatayu AI."},
        "organization_id": str(webhook.organization_id),
    }

    org_id = str(webhook.organization_id)
    if webhook.destination_type == "slack":
        body_dict = _format_slack_payload("test", payload["data"], org_id)
    elif webhook.destination_type == "discord":
        body_dict = _format_discord_payload("test", payload["data"], org_id)
    else:
        body_dict = payload

    body_bytes = json.dumps(body_dict).encode()
    signature = _hmac_signature(webhook.secret, body_bytes)

    headers = {
        "Content-Type": "application/json",
        "X-Midsphere-Signature": signature,
        "X-Midsphere-Event": "test",
    }

    try:
        req = urllib.request.Request(
            webhook.url,
            data=body_bytes,
            headers=headers,
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return {"ok": True, "message": f"Test event delivered (HTTP {resp.status})"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"HTTP {exc.code}: {exc.reason}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "message": str(exc)}


@shared_task(name="reset-project-budgets-monthly")
def reset_project_budgets_monthly():
    """Reset ProjectBudget.current_month_usage to 0 for all projects.

    Scheduled to run on the 1st of each month via CELERY_BEAT_SCHEDULE.
    """
    from apps.spaces.models import ProjectBudget

    count = ProjectBudget.objects.filter(current_month_usage__gt=0).update(
        current_month_usage=0
    )
    logger.info("Monthly budget reset: %d project budgets zeroed", count)
