"""Notification service — create, coalesce, dispatch to enabled channels.

Usage::

    from apps.workspace.notifications import create_notification

    create_notification(
        user=user,
        type="injection",
        title="Alice sent a message",
        body="Hey, check this out",
        data={"conversation_id": str(conv.id), "actor_id": str(actor.id)},
    )

The service checks the user's NotificationPreference for the given type,
skips muted projects, coalesces rapid-fire events, and dispatches to
enabled channels (in-app DB save, email Celery task, Slack/Discord webhooks).
"""

import json
import logging
import time

from django.core.cache import cache

logger = logging.getLogger(__name__)

# Coalescing: if same (user, type, conversation_id) fires 5+ times in 60s,
# bundle into a single notification.
COALESCE_WINDOW = 60  # seconds
COALESCE_THRESHOLD = 5


def _coalesce_key(user_id, notification_type: str, conversation_id: str | None) -> str:
    conv = conversation_id or "global"
    return f"notif_coalesce:{user_id}:{notification_type}:{conv}"


def _check_coalesce(user_id, notification_type: str, data: dict) -> dict | None:
    """Check if this event should be coalesced.

    Returns None if the event should proceed normally, or a modified
    data dict with coalesce info if it should be bundled.
    """
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return None  # Only coalesce conversation-scoped events

    key = _coalesce_key(user_id, notification_type, conversation_id)
    raw = cache.get(key)

    if raw is None:
        # First event in window — start tracking
        cache.set(
            key,
            json.dumps(
                {
                    "count": 1,
                    "first_ts": time.time(),
                    "actor_name": data.get("actor_name", ""),
                }
            ),
            timeout=COALESCE_WINDOW,
        )
        return None

    info = json.loads(raw) if isinstance(raw, str) else raw
    count = info.get("count", 0) + 1
    info["count"] = count
    cache.set(key, json.dumps(info), timeout=COALESCE_WINDOW)

    if count == COALESCE_THRESHOLD:
        # Return coalesced info — the caller should create a bundled notification
        return {"coalesced_count": count, "actor_name": info.get("actor_name", "")}
    elif count > COALESCE_THRESHOLD:
        # Already coalesced, suppress further individual notifications
        return {"suppress": True}

    return None


def _get_preference(user, notification_type: str):
    """Get the user's preference for this notification type.

    Returns the preference object or None (which means defaults apply:
    in_app=True, email=True, push=False, slack=False, discord=False).
    """
    from apps.workspace.models import NotificationPreference

    try:
        return NotificationPreference.objects.get(
            user=user, notification_type=notification_type
        )
    except NotificationPreference.DoesNotExist:
        return None


def _is_project_muted(pref, data: dict) -> bool:
    """Check if notifications for this project are muted."""
    if pref is None:
        return False
    project_id = data.get("project_id")
    if not project_id:
        return False
    muted = pref.muted_project_ids or []
    return str(project_id) in [str(pid) for pid in muted]


def create_notification(
    user,
    type: str,
    title: str,
    body: str = "",
    data: dict | None = None,
) -> "Notification | None":
    """Create a notification for a user, respecting preferences and coalescing.

    Returns the created Notification, or None if suppressed/muted.
    """
    from apps.workspace.models import Notification

    data = data or {}

    # Check project mute
    pref = _get_preference(user, type)
    if _is_project_muted(pref, data):
        logger.debug("Notification muted for project %s", data.get("project_id"))
        return None

    # Check in-app preference (default True)
    in_app = pref.in_app if pref else True
    email_enabled = pref.email if pref else True
    slack_enabled = pref.slack if pref else False
    discord_enabled = pref.discord if pref else False

    # Coalescing check
    coalesce_result = _check_coalesce(user.id, type, data)
    if coalesce_result and coalesce_result.get("suppress"):
        return None

    if coalesce_result and "coalesced_count" in coalesce_result:
        actor = coalesce_result.get("actor_name", "Someone")
        count = coalesce_result["coalesced_count"]
        title = f"{actor} sent {count} messages"
        body = f"in conversation"
        data["coalesced"] = True
        data["coalesced_count"] = count

    notification = None

    # In-app: save to DB
    if in_app:
        notification = Notification.objects.create(
            user=user,
            type=type,
            title=title,
            body=body,
            data=data,
        )
        # Publish SSE event via cache (clients poll for new notifications)
        _publish_sse_event(user.id, notification)

    # Email: dispatch Celery task (batched)
    if email_enabled:
        try:
            from apps.workspace.tasks import send_notification_email

            send_notification_email.delay(
                user_id=str(user.id),
                notification_type=type,
                title=title,
                body=body,
                data=data,
            )
        except Exception:
            logger.exception("Failed to enqueue email notification task")

    # Slack/Discord: dispatch if org-scoped and enterprise enabled
    org_id = data.get("organization_id")
    if org_id and (slack_enabled or discord_enabled):
        try:
            from apps.workspace.tasks import send_webhook_notification

            send_webhook_notification.delay(
                organization_id=org_id,
                notification_type=type,
                title=title,
                body=body,
                data=data,
                send_slack=slack_enabled,
                send_discord=discord_enabled,
            )
        except Exception:
            logger.exception("Failed to enqueue webhook notification task")

    return notification


def _publish_sse_event(user_id, notification) -> None:
    """Store a notification event in cache for SSE delivery.

    Clients can poll ``GET /api/v1/notifications/`` for new items.
    The cache key signals that new notifications are available.
    """
    key = f"notification_signal:{user_id}"
    cache.set(key, str(notification.id), timeout=300)
