"""Notification API — list, mark read, preferences management.

Endpoints:
    GET  /api/v1/notifications/                 — paginated list
    PATCH /api/v1/notifications/read-all        — mark all read
    GET  /api/v1/notifications/preferences      — get preferences
    PATCH /api/v1/notifications/preferences      — update preferences
    PATCH /api/v1/notifications/{id}            — mark single read
"""

import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from ninja import NinjaAPI, Schema

from apps.users.adapters import NinjaAuthAdapter
from apps.workspace.models import (
    Notification,
    NotificationPreference,
    NotificationType,
)
from config.errors.common import NotFoundError
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

notification_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="notifications")
register_error_handlers(notification_api)


# ── Schemas ──────────────────────────────────────────────────────────────────


class NotificationOut(Schema):
    id: UUID
    type: str
    title: str
    body: str
    data: dict
    is_read: bool
    created_at: datetime


class NotificationListOut(Schema):
    notifications: list[NotificationOut]
    total: int
    unread_count: int


class MarkReadRequest(Schema):
    is_read: bool = True


class PreferenceItemOut(Schema):
    notification_type: str
    in_app: bool
    email: bool
    push: bool
    slack: bool
    discord: bool
    muted_project_ids: list


class PreferencesOut(Schema):
    preferences: list[PreferenceItemOut]


class UpdatePreferenceRequest(Schema):
    notification_type: str
    in_app: Optional[bool] = None
    email: Optional[bool] = None
    push: Optional[bool] = None
    slack: Optional[bool] = None
    discord: Optional[bool] = None
    muted_project_ids: Optional[list] = None


class UpdatePreferencesRequest(Schema):
    preferences: list[UpdatePreferenceRequest]


class ActionOut(Schema):
    detail: str


class ErrorOut(Schema):
    detail: str


# ── Notification endpoints ───────────────────────────────────────────────────
# NOTE: Specific paths (/read-all, /preferences) MUST be defined before
# the parametric path (/{notification_id}) so Django-Ninja matches them first.


@notification_api.get(
    "/",
    response={200: NotificationListOut},
    summary="List notifications (paginated)",
)
def list_notifications(request, offset: int = 0, limit: int = 50):
    user = request.auth
    qs = Notification.objects.filter(user=user)
    total = qs.count()
    unread_count = qs.filter(is_read=False).count()
    notifications = list(qs[offset : offset + limit])
    return {
        "notifications": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "data": n.data,
                "is_read": n.is_read,
                "created_at": n.created_at,
            }
            for n in notifications
        ],
        "total": total,
        "unread_count": unread_count,
    }


@notification_api.patch(
    "/read-all",
    response={200: ActionOut},
    summary="Mark all notifications as read",
)
def mark_all_read(request):
    user = request.auth
    updated = Notification.objects.filter(user=user, is_read=False).update(is_read=True)
    return {"detail": f"Marked {updated} notifications as read."}


# ── Preference endpoints ─────────────────────────────────────────────────────


@notification_api.get(
    "/preferences",
    response={200: PreferencesOut},
    summary="Get notification preferences",
)
def get_preferences(request):
    user = request.auth
    existing = {
        p.notification_type: p for p in NotificationPreference.objects.filter(user=user)
    }

    result = []
    for nt_value, _label in NotificationType.choices:
        if nt_value in existing:
            p = existing[nt_value]
            result.append(
                {
                    "notification_type": nt_value,
                    "in_app": p.in_app,
                    "email": p.email,
                    "push": p.push,
                    "slack": p.slack,
                    "discord": p.discord,
                    "muted_project_ids": p.muted_project_ids or [],
                }
            )
        else:
            # Defaults
            result.append(
                {
                    "notification_type": nt_value,
                    "in_app": True,
                    "email": True,
                    "push": False,
                    "slack": False,
                    "discord": False,
                    "muted_project_ids": [],
                }
            )
    return {"preferences": result}


@notification_api.patch(
    "/preferences",
    response={200: PreferencesOut},
    summary="Update notification preferences",
)
def update_preferences(request, body: UpdatePreferencesRequest):
    user = request.auth
    for pref_update in body.preferences:
        nt = pref_update.notification_type
        # Validate notification type
        valid_types = [c[0] for c in NotificationType.choices]
        if nt not in valid_types:
            continue

        obj, _created = NotificationPreference.objects.get_or_create(
            user=user,
            notification_type=nt,
            defaults={
                "in_app": True,
                "email": True,
                "push": False,
                "slack": False,
                "discord": False,
            },
        )

        update_fields = []
        for field in (
            "in_app",
            "email",
            "push",
            "slack",
            "discord",
            "muted_project_ids",
        ):
            val = getattr(pref_update, field, None)
            if val is not None:
                setattr(obj, field, val)
                update_fields.append(field)

        if update_fields:
            obj.save(update_fields=update_fields)

    # Return full preferences
    return get_preferences(request)


# ── Parametric route LAST ────────────────────────────────────────────────────


@notification_api.patch(
    "/{notification_id}",
    response={200: NotificationOut, 404: ErrorOut},
    summary="Mark a notification as read/unread",
)
def mark_notification(request, notification_id: UUID, body: MarkReadRequest):
    user = request.auth
    try:
        notification = Notification.objects.get(id=notification_id, user=user)
    except Notification.DoesNotExist:
        raise NotFoundError("Notification not found.")
    notification.is_read = body.is_read
    notification.save(update_fields=["is_read"])
    return notification
