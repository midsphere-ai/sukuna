"""Invitation management API — token-based accept/info and ID-based revoke/resend.

These endpoints are NOT org-scoped (they operate on invitations by token or ID).
Org-scoped invitation endpoints (create, list) live in org_api.py.
"""

import logging

from django.db import transaction
from django.db.models import F
from ninja import NinjaAPI

from apps.users.adapters import NinjaAuthAdapter
from apps.workspace.enterprise import auto_enable_enterprise, require_enterprise
from apps.workspace.models import (
    Invitation,
    Organization,
    OrganizationMembership,
)
from apps.workspace.org_schemas import (
    ActionOut,
    ErrorOut,
    InvitationAcceptOut,
    InvitationInfoOut,
)
from apps.workspace.permissions import OrgPermission, check_org_permission
from config.errors.common import NotFoundError
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

invitation_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="invitations")
register_error_handlers(invitation_api)


def _get_client_ip(request) -> str | None:
    """Extract client IP from X-Forwarded-For or REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _get_invitation_or_404(token: str) -> Invitation:
    """Fetch an invitation by token UUID or raise NotFoundError."""
    try:
        return Invitation.objects.select_related("organization", "invited_by").get(
            token=token
        )
    except (Invitation.DoesNotExist, ValueError):
        raise NotFoundError("Invitation not found.")


@invitation_api.get(
    "/{token}",
    response={200: InvitationInfoOut, 404: ErrorOut, 410: ErrorOut},
    auth=None,
)
def get_invitation_info(request, token: str):
    """Get public invitation info for the accept page. No auth required."""
    inv = _get_invitation_or_404(token)

    if not inv.is_active:
        return 410, {"detail": "This invitation has been revoked."}
    if inv.is_expired:
        return 410, {"detail": "This invitation has expired."}
    if inv.max_uses is not None and inv.use_count >= inv.max_uses:
        return 410, {"detail": "This invitation has reached its usage limit."}

    # Check org still exists (CASCADE should handle, but be safe)
    try:
        org = inv.organization
    except Organization.DoesNotExist:
        return 404, {"detail": "Organization no longer exists."}

    return 200, {
        "organization_name": org.name,
        "organization_slug": org.slug,
        "role": inv.role,
        "invited_by_name": inv.invited_by.name if inv.invited_by else None,
        "expires_at": inv.expires_at,
    }


@invitation_api.post(
    "/{token}/accept",
    response={
        200: InvitationAcceptOut,
        400: ErrorOut,
        404: ErrorOut,
        410: ErrorOut,
        429: ErrorOut,
    },
)
def accept_invitation(request, token: str):
    """Accept an invitation. Requires authentication."""
    require_enterprise(request)

    # Rate limit: max 10 accepts per minute per IP
    from django.core.cache import cache

    client_ip = _get_client_ip(request) or "unknown"
    rate_key = f"invite_accept:{client_ip}"
    count = cache.get(rate_key, 0)
    if count >= 10:
        return 429, {"detail": "Too many requests. Please try again later."}
    cache.set(rate_key, count + 1, timeout=60)

    from apps.compliance.models import AuditLog

    inv = _get_invitation_or_404(token)
    user = request.auth

    if not inv.is_active:
        return 410, {"detail": "This invitation has been revoked."}
    if inv.is_expired:
        return 410, {"detail": "This invitation has expired."}

    org = inv.organization

    # Check if user is already a member
    if org.has_member(user):
        return 200, {
            "success": True,
            "message": "Already a member.",
            "organization_id": org.pk,
            "organization_name": org.name,
            "role": org.get_membership(user).role,
        }

    # Atomic increment use_count to prevent race conditions
    with transaction.atomic():
        updated = (
            Invitation.objects.filter(
                pk=inv.pk,
                is_active=True,
            )
            .exclude(
                # Exclude if max_uses reached (only when max_uses is set)
                max_uses__isnull=False,
                use_count__gte=F("max_uses"),
            )
            .update(use_count=F("use_count") + 1)
        )

        if not updated:
            return 410, {"detail": "This invitation has reached its usage limit."}

        membership = OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=inv.role,
            invited_by=inv.invited_by,
        )

    # Auto-enable enterprise mode for the accepting user
    auto_enable_enterprise(user)

    AuditLog.log(
        action="invitation_accepted",
        resource_type="invitation",
        resource_id=str(inv.pk),
        actor_id=user.pk,
        actor_email=user.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "organization_name": org.name,
            "role": inv.role,
            "invitation_token": str(inv.token),
        },
    )

    return 200, {
        "success": True,
        "message": f"You have joined {org.name} as {inv.role}.",
        "organization_id": org.pk,
        "organization_name": org.name,
        "role": membership.role,
    }


@invitation_api.delete(
    "/{invitation_id}/revoke",
    response={200: ActionOut, 400: ErrorOut, 404: ErrorOut},
)
def revoke_invitation(request, invitation_id: str):
    """Revoke an invitation. Requires admin+ role in the invitation's org."""
    require_enterprise(request)
    from apps.compliance.models import AuditLog

    try:
        inv = Invitation.objects.select_related("organization").get(pk=invitation_id)
    except (Invitation.DoesNotExist, ValueError):
        raise NotFoundError("Invitation not found.")

    check_org_permission(request.auth, inv.organization, OrgPermission.INVITE_MEMBERS)

    if not inv.is_active:
        return 400, {"detail": "Invitation is already revoked."}

    inv.is_active = False
    inv.save(update_fields=["is_active"])

    AuditLog.log(
        action="invitation_revoked",
        resource_type="invitation",
        resource_id=str(inv.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(inv.organization_id),
            "invited_email": inv.email,
            "role": inv.role,
        },
    )

    return 200, {"success": True, "message": "Invitation revoked."}


@invitation_api.post(
    "/{invitation_id}/resend",
    response={200: ActionOut, 400: ErrorOut, 404: ErrorOut},
)
def resend_invitation(request, invitation_id: str):
    """Resend an invitation email. Requires admin+ role in the invitation's org."""
    require_enterprise(request)

    try:
        inv = Invitation.objects.select_related("organization", "invited_by").get(
            pk=invitation_id
        )
    except (Invitation.DoesNotExist, ValueError):
        raise NotFoundError("Invitation not found.")

    check_org_permission(request.auth, inv.organization, OrgPermission.INVITE_MEMBERS)

    if not inv.is_active:
        return 400, {"detail": "Cannot resend a revoked invitation."}
    if inv.is_expired:
        return 400, {"detail": "Cannot resend an expired invitation."}
    if not inv.email:
        return 400, {"detail": "Cannot resend a link invitation (no email)."}

    # Re-send the email
    from apps.workspace.org_api import _send_invitation_email

    _send_invitation_email(inv)

    return 200, {"success": True, "message": f"Invitation resent to {inv.email}."}
