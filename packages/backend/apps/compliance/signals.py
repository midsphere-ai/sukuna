"""Django signals for automatic audit log capture.

Listens to model lifecycle events and auth signals to create
immutable AuditLog records without requiring manual instrumentation
at every call site.
"""

import logging

from allauth.socialaccount.signals import social_account_added, social_account_removed
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _get_client_ip(request) -> str | None:
    """Extract client IP from request, handling proxied requests."""
    if request is None:
        return None
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_request_id(request) -> str:
    """Extract request ID from request if available."""
    if request is None:
        return ""
    return getattr(request, "request_id", "")


def _safe_log(
    *,
    action,
    resource_type,
    resource_id="",
    actor_id=None,
    actor_email="",
    actor_ip=None,
    request_id="",
    changes=None,
    metadata=None,
):
    """Create an audit log entry, swallowing exceptions to never break the main flow."""
    from .models import AuditLog

    try:
        AuditLog.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_ip=actor_ip,
            request_id=request_id,
            changes=changes,
            metadata=metadata,
        )
    except Exception:
        logger.exception(
            "Failed to write audit log: %s %s/%s", action, resource_type, resource_id
        )


# ---------------------------------------------------------------------------
# Auth signals
# ---------------------------------------------------------------------------


@receiver(user_logged_in)
def on_user_logged_in(sender, request, user, **kwargs):
    """Audit successful login."""
    _safe_log(
        action="login",
        resource_type="user",
        resource_id=str(user.pk),
        actor_id=user.pk,
        actor_email=getattr(user, "email", ""),
        actor_ip=_get_client_ip(request),
        request_id=_get_request_id(request),
    )


@receiver(user_logged_out)
def on_user_logged_out(sender, request, user, **kwargs):
    """Audit logout."""
    if user is None:
        return
    _safe_log(
        action="logout",
        resource_type="user",
        resource_id=str(user.pk),
        actor_id=user.pk,
        actor_email=getattr(user, "email", ""),
        actor_ip=_get_client_ip(request),
        request_id=_get_request_id(request),
    )


@receiver(user_login_failed)
def on_user_login_failed(sender, credentials, request, **kwargs):
    """Audit failed login attempt."""
    _safe_log(
        action="login_failed",
        resource_type="user",
        actor_ip=_get_client_ip(request),
        request_id=_get_request_id(request),
        metadata={
            "username": credentials.get("username", credentials.get("email", ""))
        },
    )


# ---------------------------------------------------------------------------
# Social account signals
# ---------------------------------------------------------------------------


@receiver(social_account_added)
def on_social_account_added(request, sociallogin, **kwargs):
    """Audit when a social account is linked to a user."""
    user = sociallogin.user
    provider = sociallogin.account.provider
    _safe_log(
        action="social_account_added",
        resource_type="social_account",
        resource_id=str(sociallogin.account.pk) if sociallogin.account.pk else "",
        actor_id=user.pk if user and user.pk else None,
        actor_email=getattr(user, "email", ""),
        actor_ip=_get_client_ip(request),
        request_id=_get_request_id(request),
        metadata={"provider": provider, "uid": sociallogin.account.uid},
    )


@receiver(social_account_removed)
def on_social_account_removed(request, socialaccount, **kwargs):
    """Audit when a social account is unlinked from a user."""
    user = socialaccount.user
    _safe_log(
        action="social_account_removed",
        resource_type="social_account",
        resource_id=str(socialaccount.pk),
        actor_id=user.pk if user and user.pk else None,
        actor_email=getattr(user, "email", ""),
        actor_ip=_get_client_ip(request),
        request_id=_get_request_id(request),
        metadata={"provider": socialaccount.provider, "uid": socialaccount.uid},
    )


# ---------------------------------------------------------------------------
# User model signals
# ---------------------------------------------------------------------------


@receiver(post_save, sender="users.User")
def on_user_saved(sender, instance, created, **kwargs):
    """Audit user creation and updates."""
    _safe_log(
        action="create" if created else "update",
        resource_type="user",
        resource_id=str(instance.pk),
        actor_id=instance.pk,
        actor_email=getattr(instance, "email", ""),
    )


@receiver(post_delete, sender="users.User")
def on_user_deleted(sender, instance, **kwargs):
    """Audit user deletion."""
    _safe_log(
        action="delete",
        resource_type="user",
        resource_id=str(instance.pk),
        actor_id=instance.pk,
        actor_email=getattr(instance, "email", ""),
    )


# ---------------------------------------------------------------------------
# Conversation signals
# ---------------------------------------------------------------------------


@receiver(post_save, sender="storage.Conversation")
def on_conversation_saved(sender, instance, created, **kwargs):
    """Audit conversation creation."""
    if not created:
        return
    user = getattr(instance, "user", None)
    _safe_log(
        action="create",
        resource_type="conversation",
        resource_id=str(instance.pk),
        actor_id=getattr(user, "pk", None),
        actor_email=getattr(user, "email", ""),
    )


@receiver(post_delete, sender="storage.Conversation")
def on_conversation_deleted(sender, instance, **kwargs):
    """Audit conversation deletion."""
    # user FK is nullable and may reference an already-deleted user during
    # CASCADE, so guard against DoesNotExist.
    try:
        user = instance.user
    except Exception:
        user = None
    _safe_log(
        action="delete",
        resource_type="conversation",
        resource_id=str(instance.pk),
        actor_id=getattr(user, "pk", None),
        actor_email=getattr(user, "email", ""),
    )


# ---------------------------------------------------------------------------
# AgentRun signals
# ---------------------------------------------------------------------------


_AGENT_RUN_ACTION_MAP = {
    "completed": "agent_run_complete",
    "failed": "agent_run_fail",
    "cancelled": "agent_run_cancel",
}


@receiver(post_save, sender="storage.AgentRun")
def on_agent_run_saved(sender, instance, created, **kwargs):
    """Audit agent run creation and terminal state transitions."""
    if created:
        user = getattr(instance, "user", None)
        _safe_log(
            action="agent_run_start",
            resource_type="agent_run",
            resource_id=str(instance.pk),
            actor_id=getattr(user, "pk", None),
            actor_email=getattr(user, "email", "") if user else "",
            metadata={"model": instance.model, "status": instance.status},
        )
        return

    action = _AGENT_RUN_ACTION_MAP.get(instance.status)
    if action:
        user = getattr(instance, "user", None)
        _safe_log(
            action=action,
            resource_type="agent_run",
            resource_id=str(instance.pk),
            actor_id=getattr(user, "pk", None),
            actor_email=getattr(user, "email", "") if user else "",
            metadata={
                "status": instance.status,
                "error": instance.error[:500] if instance.error else "",
            },
        )


# ---------------------------------------------------------------------------
# Developer API Key signals
# ---------------------------------------------------------------------------


@receiver(post_save, sender="users.DeveloperAPIKey")
def on_api_key_saved(sender, instance, created, **kwargs):
    """Audit API key creation."""
    if not created:
        return
    user = getattr(instance, "user", None)
    _safe_log(
        action="create",
        resource_type="api_key",
        resource_id=str(instance.pk),
        actor_id=getattr(user, "pk", None),
        actor_email=getattr(user, "email", "") if user else "",
        metadata={"key_name": getattr(instance, "name", "")},
    )


@receiver(post_delete, sender="users.DeveloperAPIKey")
def on_api_key_deleted(sender, instance, **kwargs):
    """Audit API key deletion."""
    user = getattr(instance, "user", None)
    _safe_log(
        action="delete",
        resource_type="api_key",
        resource_id=str(instance.pk),
        actor_id=getattr(user, "pk", None),
        actor_email=getattr(user, "email", "") if user else "",
    )


# ---------------------------------------------------------------------------
# Subscription signals
# ---------------------------------------------------------------------------


@receiver(post_save, sender="billing.UserSubscription")
def on_subscription_changed(sender, instance, created, **kwargs):
    """Audit subscription creation and plan changes."""
    user = getattr(instance, "user", None)
    _safe_log(
        action="subscription_change",
        resource_type="subscription",
        resource_id=str(instance.pk),
        actor_id=getattr(user, "pk", None),
        actor_email=getattr(user, "email", "") if user else "",
        metadata={
            "created": created,
            "plan_id": str(getattr(instance.plan, "pk", ""))
            if getattr(instance, "plan", None)
            else "",
            "status": getattr(instance, "status", ""),
        },
    )
