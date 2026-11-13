"""Organization management API with RBAC permission checks on every endpoint.

All endpoints require authentication. Org-scoped endpoints enforce role checks
via the permission utilities from apps.workspace.permissions.
"""

import logging

from django.db import transaction
from django.utils import timezone
from ninja import NinjaAPI

from apps.users.adapters import APIKeyAuthAdapter, NinjaAuthAdapter
from apps.users.models import User
from apps.workspace.enterprise import auto_enable_enterprise, require_enterprise
from apps.workspace.models import (
    ConditionalAccessPolicy,
    Invitation,
    IPAllowlistEntry,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgDiscordIntegration,
    OrgSlackIntegration,
)
from apps.workspace.org_schemas import (
    AccessPolicyListOut,
    AccessPolicyOut,
    ActionOut,
    AgentPolicyOut,
    AnalyticsSummaryOut,
    ChangeMemberRoleRequest,
    CostPolicyOut,
    CostStatusOut,
    CreateAccessPolicyRequest,
    CreateInvitationRequest,
    CreateIPAllowlistRequest,
    CreateLinkInvitationRequest,
    CreateOrganizationRequest,
    CreateOrgAPIKeyRequest,
    CreateSCIMTokenRequest,
    CreateSSOConfigRequest,
    DeleteOrganizationRequest,
    DeletionPreviewOut,
    DLPPolicyOut,
    DLPTestOut,
    DLPTestRequest,
    ErrorOut,
    IntegrationOut,
    IntegrationTestOut,
    InvitationOut,
    InviteMemberRequest,
    IPAllowlistEntryOut,
    IPAllowlistListOut,
    MemberAnalyticsOut,
    MemberOut,
    ModelPolicyOut,
    OrganizationListOut,
    OrganizationOut,
    OrgAPIKeyCreatedOut,
    OrgAPIKeyOut,
    OrgSlugChangeOut,
    ProjectAnalyticsOut,
    SCIMTokenCreatedOut,
    SCIMTokenOut,
    SecurityPolicyOut,
    SSOConfigOut,
    UpdateAccessPolicyRequest,
    UpdateAgentPolicyRequest,
    UpdateCostPolicyRequest,
    UpdateDLPPolicyRequest,
    UpdateIntegrationRequest,
    UpdateModelPolicyRequest,
    UpdateOrganizationRequest,
    UpdateOrgSlugRequest,
    UpdateSecurityPolicyRequest,
    UpdateSSOConfigRequest,
)
from apps.workspace.permissions import (
    OrgPermission,
    can_manage_member,
    check_org_permission,
    get_org_membership,
)
from apps.workspace.security import (
    ORG_SCOPE_ADMIN,
    ORG_SCOPE_READ,
    ORG_SCOPE_WRITE,
    check_api_key_org_scope,
)
from config.errors.common import NotFoundError, UnauthorizedAccessError
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

org_api = NinjaAPI(
    auth=[NinjaAuthAdapter(), APIKeyAuthAdapter()], urls_namespace="organizations"
)
register_error_handlers(org_api)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _require_org_access(request, scope=None):
    """Enterprise gate + API key scope enforcement for org endpoints.

    If no explicit scope is given, auto-detects from HTTP method:
    GET → org:read, mutations → org:write.
    Pass ORG_SCOPE_ADMIN explicitly for admin-only endpoints.
    """
    require_enterprise(request)
    if scope is None:
        scope = ORG_SCOPE_READ if request.method == "GET" else ORG_SCOPE_WRITE
    check_api_key_org_scope(request, scope)


def _check_org_admin_permission(request, user, org, permission):
    """check_org_permission wrapper that also enforces org:admin API key scope
    when the permission requires MANAGE_SETTINGS."""
    if permission == OrgPermission.MANAGE_SETTINGS:
        check_api_key_org_scope(request, ORG_SCOPE_ADMIN)
    return check_org_permission(user, org, permission)


def _get_org_or_404(org_id: str) -> Organization:
    """Fetch an organization by UUID or raise NotFoundError."""
    try:
        return Organization.objects.get(pk=org_id)
    except (Organization.DoesNotExist, ValueError):
        raise NotFoundError("Organization not found.")


def _serialize_org(org: Organization, role: str | None = None) -> dict:
    """Build an OrganizationOut-compatible dict."""
    return {
        "id": org.pk,
        "name": org.name,
        "slug": org.slug,
        "description": org.description,
        "created_at": org.created_at,
        "updated_at": org.updated_at,
        "member_count": org.member_count(),
        "your_role": role,
    }


def _serialize_member(membership: OrganizationMembership) -> dict:
    """Build a MemberOut-compatible dict."""
    return {
        "id": membership.pk,
        "user_id": membership.user_id,
        "email": membership.user.email,
        "name": membership.user.name,
        "role": membership.role,
        "joined_at": membership.joined_at,
    }


# ── Organization CRUD ───────────────────────────────────────────────────────


@org_api.post("/", response={201: OrganizationOut})
def create_organization(request, body: CreateOrganizationRequest):
    """Create a new organization. The authenticated user becomes the owner."""
    _require_org_access(request)
    user = request.auth
    name = body.name.strip()
    if not name:
        from ninja.errors import HttpError

        raise HttpError(400, "Organization name is required.")

    with transaction.atomic():
        org = Organization.objects.create(
            name=name,
            description=body.description.strip(),
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.OWNER,
            invited_by=None,
        )

    return 201, _serialize_org(org, role=OrganizationRole.OWNER)


@org_api.get("/", response=list[OrganizationListOut])
def list_organizations(request):
    """List all organizations the authenticated user belongs to."""
    _require_org_access(request)
    user = request.auth
    memberships = (
        OrganizationMembership.objects.filter(user=user)
        .select_related("organization")
        .order_by("organization__name")
    )
    results = []
    for m in memberships:
        org = m.organization
        results.append(
            {
                "id": org.pk,
                "name": org.name,
                "slug": org.slug,
                "description": org.description,
                "member_count": org.member_count(),
                "your_role": m.role,
            }
        )
    return results


@org_api.get("/{org_id}", response=OrganizationOut)
def get_organization(request, org_id: str):
    """Get organization details. Requires viewer+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    membership = check_org_permission(request.auth, org, OrgPermission.VIEW_ORG)
    return _serialize_org(org, role=membership.role)


@org_api.patch("/{org_id}", response=OrganizationOut)
def update_organization(request, org_id: str, body: UpdateOrganizationRequest):
    """Update organization name/description. Requires admin+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    membership = _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    if body.name is not None:
        name = body.name.strip()
        if not name:
            from ninja.errors import HttpError

            raise HttpError(400, "Organization name cannot be empty.")
        org.name = name
    if body.description is not None:
        org.description = body.description.strip()
    org.save()

    return _serialize_org(org, role=membership.role)


@org_api.delete("/{org_id}", response={200: ActionOut, 400: ErrorOut, 409: ErrorOut})
def delete_organization(request, org_id: str, body: DeleteOrganizationRequest):
    """Delete an organization. Requires owner role + name confirmation.

    cascade_mode: 'transfer' moves projects back to original creators,
    'destroy' cascade-deletes everything.
    """
    _require_org_access(request)
    from datetime import timedelta

    from apps.compliance.models import AuditLog
    from apps.storage.models import AgentRun

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.DELETE_ORG)

    # Validate confirmation name
    if body.confirm_name != org.name:
        return 400, {"detail": "confirm_name does not match the organization name."}

    # Validate cascade mode
    if body.cascade_mode not in ("transfer", "destroy"):
        return 400, {"detail": "cascade_mode must be 'transfer' or 'destroy'."}

    # Check for active agent runs
    active_runs = AgentRun.objects.filter(
        conversation__project__organization=org,
        status__in=[AgentRun.Status.RUNNING, AgentRun.Status.PROVISIONING],
    )
    if active_runs.exists():
        run_ids = list(active_runs.values_list("id", flat=True)[:20])
        return 409, {
            "detail": f"Cannot delete org with {len(run_ids)} active agent run(s). Wait for them to complete or cancel them first."
        }

    with transaction.atomic():
        org_name = org.name
        org_slug = org.slug
        org_pk = str(org.pk)

        if body.cascade_mode == "transfer":
            # Move all org projects back to their original creators as personal
            for project in org.projects.all():
                project.organization = None
                project.save(update_fields=["organization"])
        # For "destroy", Django CASCADE handles deletion

        # Reserve the slug for 90 days
        from apps.workspace.models import DeletedOrgSlug

        DeletedOrgSlug.objects.create(
            slug=org_slug,
            reserved_until=timezone.now() + timedelta(days=90),
        )

        # Delete SSO config and SCIM tokens are auto-cascaded
        org.delete()

    AuditLog.log(
        action="org_deleted",
        resource_type="organization",
        resource_id=org_pk,
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_name": org_name,
            "organization_slug": org_slug,
            "cascade_mode": body.cascade_mode,
        },
    )

    return 200, {"success": True, "message": f"Organization '{org_name}' deleted."}


@org_api.get("/{org_id}/deletion-preview", response=DeletionPreviewOut)
def deletion_preview(request, org_id: str):
    """Preview resources affected by org deletion. Requires owner role."""
    _require_org_access(request)
    from apps.storage.models import AgentRun, Conversation

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.DELETE_ORG)

    project_ids = org.projects.values_list("pk", flat=True)
    conversation_count = Conversation.objects.filter(project_id__in=project_ids).count()
    active_runs = AgentRun.objects.filter(
        conversation__project__organization=org,
        status__in=[AgentRun.Status.RUNNING, AgentRun.Status.PROVISIONING],
    ).count()

    try:
        has_sso = org.sso_config is not None
    except Exception:
        has_sso = False

    return {
        "organization_id": org.pk,
        "organization_name": org.name,
        "projects": org.projects.count(),
        "conversations": conversation_count,
        "members": org.member_count(),
        "active_agent_runs": active_runs,
        "scim_tokens": org.scim_tokens.count(),
        "has_sso_config": has_sso,
    }


@org_api.post("/{org_id}/freeze", response={200: ActionOut, 400: ErrorOut})
def freeze_organization(request, org_id: str):
    """Freeze an organization — no new runs, shares, or invites. Requires owner role."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.DELETE_ORG)

    if org.is_frozen:
        return 400, {"detail": "Organization is already frozen."}

    org.frozen_at = timezone.now()
    org.save(update_fields=["frozen_at"])

    AuditLog.log(
        action="org_frozen",
        resource_type="organization",
        resource_id=str(org.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={"organization_name": org.name},
    )

    return 200, {"success": True, "message": f"Organization '{org.name}' frozen."}


@org_api.post("/{org_id}/unfreeze", response={200: ActionOut, 400: ErrorOut})
def unfreeze_organization(request, org_id: str):
    """Unfreeze an organization. Requires owner role."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.DELETE_ORG)

    if not org.is_frozen:
        return 400, {"detail": "Organization is not frozen."}

    org.frozen_at = None
    org.save(update_fields=["frozen_at"])

    AuditLog.log(
        action="org_unfrozen",
        resource_type="organization",
        resource_id=str(org.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={"organization_name": org.name},
    )

    return 200, {"success": True, "message": f"Organization '{org.name}' unfrozen."}


@org_api.patch(
    "/{org_id}/slug", response={200: OrgSlugChangeOut, 400: ErrorOut, 409: ErrorOut}
)
def change_org_slug(request, org_id: str, body: UpdateOrgSlugRequest):
    """Change the org slug. Returns old + new endpoint URLs so admin can update IdP config. Requires admin+."""
    _require_org_access(request)
    from django.conf import settings as django_settings
    from django.utils.text import slugify as django_slugify

    from apps.compliance.models import AuditLog
    from apps.workspace.models import DeletedOrgSlug

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    new_slug = django_slugify(body.new_slug.strip())
    if not new_slug:
        return 400, {"detail": "Slug cannot be empty."}

    if new_slug == org.slug:
        return 400, {"detail": "New slug is the same as the current slug."}

    # Check against active orgs
    if Organization.objects.filter(slug=new_slug).exclude(pk=org.pk).exists():
        return 409, {"detail": f"Slug '{new_slug}' is already in use."}

    # Check against reserved deleted slugs
    reserved = DeletedOrgSlug.objects.filter(
        slug=new_slug, reserved_until__gt=timezone.now()
    ).first()
    if reserved:
        return 409, {"detail": f"Slug '{new_slug}' is reserved (was recently deleted)."}

    old_slug = org.slug
    org.slug = new_slug
    org.save(update_fields=["slug"])

    base_url = getattr(django_settings, "SITE_URL", "https://app.midsphere.com")

    AuditLog.log(
        action="org_slug_changed",
        resource_type="organization",
        resource_id=str(org.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        changes={"slug": {"old": old_slug, "new": new_slug}},
        metadata={"organization_name": org.name},
    )

    return 200, {
        "old_slug": old_slug,
        "new_slug": new_slug,
        "old_scim_url": f"{base_url}/api/v1/scim/v2/{old_slug}/",
        "new_scim_url": f"{base_url}/api/v1/scim/v2/{new_slug}/",
        "old_saml_entity_id": f"{base_url}/api/v1/auth/saml/{old_slug}",
        "new_saml_entity_id": f"{base_url}/api/v1/auth/saml/{new_slug}",
    }


# ── Member Management ───────────────────────────────────────────────────────


@org_api.get("/{org_id}/members", response=list[MemberOut])
def list_members(request, org_id: str):
    """List organization members. Requires viewer+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_MEMBERS)

    memberships = org.memberships.select_related("user").order_by("joined_at")
    return [_serialize_member(m) for m in memberships]


@org_api.post(
    "/{org_id}/members",
    response={201: MemberOut, 400: ErrorOut, 404: ErrorOut, 409: ErrorOut},
)
def invite_member(request, org_id: str, body: InviteMemberRequest):
    """Invite a user to the organization by email. Requires admin+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    actor_membership = check_org_permission(
        request.auth, org, OrgPermission.INVITE_MEMBERS
    )

    # Validate role
    valid_roles = {
        OrganizationRole.VIEWER,
        OrganizationRole.MEMBER,
        OrganizationRole.ADMIN,
    }
    if body.role not in valid_roles:
        return 400, {
            "detail": f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}"
        }

    # Admins cannot invite someone at or above their own level
    from apps.workspace.permissions import role_at_least

    if (
        role_at_least(body.role, actor_membership.role)
        and actor_membership.role != OrganizationRole.OWNER
    ):
        return 400, {
            "detail": "Cannot invite a member with a role equal to or higher than your own."
        }

    # Find the user
    email = body.email.strip().lower()
    try:
        target_user = User.objects.get_by_email(email)
    except User.DoesNotExist:
        return 404, {"detail": f"No user found with email '{email}'."}

    # Check not already a member
    if org.has_member(target_user):
        return 409, {
            "detail": f"User '{email}' is already a member of this organization."
        }

    membership = OrganizationMembership.objects.create(
        organization=org,
        user=target_user,
        role=body.role,
        invited_by=request.auth,
    )
    # Auto-enable enterprise mode for the invited user
    auto_enable_enterprise(target_user)
    return 201, _serialize_member(membership)


@org_api.patch(
    "/{org_id}/members/{membership_id}",
    response={200: MemberOut, 400: ErrorOut},
)
def change_member_role(
    request, org_id: str, membership_id: str, body: ChangeMemberRoleRequest
):
    """Change a member's role. Requires admin+ and must outrank the target."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    actor_membership = check_org_permission(
        request.auth, org, OrgPermission.MANAGE_MEMBERS
    )

    try:
        target_membership = org.memberships.select_related("user").get(pk=membership_id)
    except (OrganizationMembership.DoesNotExist, ValueError):
        raise NotFoundError("Membership not found.")

    # Check actor can manage target
    if not can_manage_member(actor_membership, target_membership):
        raise UnauthorizedAccessError("You cannot change this member's role.")

    # Validate new role
    valid_roles = {r.value for r in OrganizationRole}
    if body.role not in valid_roles:
        return 400, {
            "detail": f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}"
        }

    # Prevent non-owners from promoting to owner
    if (
        body.role == OrganizationRole.OWNER
        and actor_membership.role != OrganizationRole.OWNER
    ):
        return 400, {"detail": "Only owners can promote members to owner."}

    try:
        target_membership.change_role(body.role)
    except ValueError as e:
        return 400, {"detail": str(e)}

    target_membership.refresh_from_db()
    return 200, _serialize_member(target_membership)


@org_api.delete(
    "/{org_id}/members/{membership_id}",
    response={200: ActionOut, 400: ErrorOut},
)
def remove_member(request, org_id: str, membership_id: str):
    """Remove a member from the organization. Requires admin+ and must outrank the target."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    actor_membership = check_org_permission(
        request.auth, org, OrgPermission.REMOVE_MEMBERS
    )

    try:
        target_membership = org.memberships.select_related("user").get(pk=membership_id)
    except (OrganizationMembership.DoesNotExist, ValueError):
        raise NotFoundError("Membership not found.")

    # Check actor can manage target
    if not can_manage_member(actor_membership, target_membership):
        raise UnauthorizedAccessError("You cannot remove this member.")

    email = target_membership.user.email
    try:
        target_membership.delete()
    except ValueError as e:
        return 400, {"detail": str(e)}

    return 200, {"success": True, "message": f"Member '{email}' removed."}


@org_api.post("/{org_id}/leave", response={200: ActionOut, 400: ErrorOut})
def leave_organization(request, org_id: str):
    """Leave an organization. The last owner cannot leave."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    membership = get_org_membership(request.auth, org)
    if membership is None:
        raise UnauthorizedAccessError("You are not a member of this organization.")

    try:
        membership.delete()
    except ValueError as e:
        return 400, {"detail": str(e)}

    return 200, {"success": True, "message": f"You have left '{org.name}'."}


# ── Invitations ───────────────────────────────────────────────────────────


def _serialize_invitation(inv: Invitation) -> dict:
    """Build an InvitationOut-compatible dict."""
    return {
        "id": inv.pk,
        "organization_id": inv.organization_id,
        "organization_name": inv.organization.name,
        "email": inv.email,
        "role": inv.role,
        "token": inv.token,
        "invited_by_email": inv.invited_by.email if inv.invited_by else None,
        "created_at": inv.created_at,
        "expires_at": inv.expires_at,
        "max_uses": inv.max_uses,
        "use_count": inv.use_count,
        "is_active": inv.is_active,
    }


@org_api.post(
    "/{org_id}/invitations",
    response={201: InvitationOut, 400: ErrorOut, 409: ErrorOut},
)
def create_invitation(request, org_id: str, body: CreateInvitationRequest):
    """Create an email invitation to the organization. Requires admin+ role."""
    _require_org_access(request)
    from datetime import timedelta

    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)

    # Frozen orgs cannot send invites
    if org.is_frozen:
        return 400, {"detail": "Organization is frozen. Cannot send invitations."}

    actor_membership = check_org_permission(
        request.auth, org, OrgPermission.INVITE_MEMBERS
    )

    # Validate role
    valid_roles = {
        OrganizationRole.VIEWER,
        OrganizationRole.MEMBER,
        OrganizationRole.ADMIN,
    }
    if body.role not in valid_roles:
        return 400, {
            "detail": f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}"
        }

    # Admins cannot invite at or above their own level
    from apps.workspace.permissions import role_at_least

    if (
        role_at_least(body.role, actor_membership.role)
        and actor_membership.role != OrganizationRole.OWNER
    ):
        return 400, {
            "detail": "Cannot invite with a role equal to or higher than your own."
        }

    email = body.email.strip().lower()
    if not email:
        return 400, {"detail": "Email is required."}

    # Check if user is already a member
    try:
        existing_user = User.objects.get_by_email(email)
        if org.has_member(existing_user):
            return 409, {
                "detail": f"User '{email}' is already a member of this organization."
            }
    except User.DoesNotExist:
        pass  # OK — invite for user who hasn't signed up yet

    # Check for existing active invitation to same email in this org
    existing_invite = Invitation.objects.filter(
        organization=org,
        email=email,
        is_active=True,
    ).first()
    if existing_invite and existing_invite.is_usable:
        return 409, {"detail": f"An active invitation already exists for '{email}'."}

    # Create the invitation (expires in 7 days by default)
    inv = Invitation.objects.create(
        organization=org,
        email=email,
        role=body.role,
        invited_by=request.auth,
        expires_at=timezone.now() + timedelta(days=7),
        max_uses=1,
    )

    # Send invitation email
    _send_invitation_email(inv)

    AuditLog.log(
        action="invitation_created",
        resource_type="invitation",
        resource_id=str(inv.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "invited_email": email,
            "role": body.role,
        },
    )

    return 201, _serialize_invitation(inv)


@org_api.get("/{org_id}/invitations", response=list[InvitationOut])
def list_invitations(request, org_id: str):
    """List pending invitations for the organization. Requires admin+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.INVITE_MEMBERS)

    invitations = (
        Invitation.objects.filter(organization=org, is_active=True)
        .select_related("organization", "invited_by")
        .order_by("-created_at")
    )
    return [_serialize_invitation(inv) for inv in invitations]


@org_api.post(
    "/{org_id}/invitation-links",
    response={201: InvitationOut, 400: ErrorOut},
)
def create_link_invitation(request, org_id: str, body: CreateLinkInvitationRequest):
    """Create a shareable invitation link (no email). Requires admin+ role."""
    _require_org_access(request)
    from datetime import timedelta

    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)

    if org.is_frozen:
        return 400, {
            "detail": "Organization is frozen. Cannot create invitation links."
        }

    actor_membership = check_org_permission(
        request.auth, org, OrgPermission.INVITE_MEMBERS
    )

    # Validate role
    valid_roles = {
        OrganizationRole.VIEWER,
        OrganizationRole.MEMBER,
        OrganizationRole.ADMIN,
    }
    if body.role not in valid_roles:
        return 400, {
            "detail": f"Invalid role. Must be one of: {', '.join(sorted(valid_roles))}"
        }

    # Admins cannot invite at or above their own level
    from apps.workspace.permissions import role_at_least

    if (
        role_at_least(body.role, actor_membership.role)
        and actor_membership.role != OrganizationRole.OWNER
    ):
        return 400, {
            "detail": "Cannot create link with a role equal to or higher than your own."
        }

    # Parse expiry
    expiry_map = {
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
    }
    if body.expiry == "never":
        expires_at = None
    elif body.expiry in expiry_map:
        expires_at = timezone.now() + expiry_map[body.expiry]
    else:
        return 400, {"detail": "Invalid expiry. Must be one of: 1d, 7d, 30d, never"}

    # Validate max_uses
    if body.max_uses is not None and body.max_uses < 1:
        return 400, {"detail": "max_uses must be at least 1."}

    inv = Invitation.objects.create(
        organization=org,
        email=None,  # link invite — no email
        role=body.role,
        invited_by=request.auth,
        expires_at=expires_at,
        max_uses=body.max_uses,
    )

    AuditLog.log(
        action="invitation_link_created",
        resource_type="invitation",
        resource_id=str(inv.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "role": body.role,
            "expiry": body.expiry,
            "max_uses": body.max_uses,
            "token": str(inv.token),
        },
    )

    return 201, _serialize_invitation(inv)


def _send_invitation_email(invitation: Invitation) -> None:
    """Send an invitation email to the target address."""
    from django.conf import settings as django_settings
    from django.core.mail import send_mail

    base_url = getattr(django_settings, "SITE_URL", "https://app.midsphere.com")
    accept_url = f"{base_url}/invite/{invitation.token}"
    org_name = invitation.organization.name
    inviter_name = invitation.invited_by.name if invitation.invited_by else "Someone"

    subject = f"You've been invited to join {org_name}"
    message = (
        f"Hi,\n\n"
        f"{inviter_name} has invited you to join {org_name} as a {invitation.role}.\n\n"
        f"Click the link below to accept:\n{accept_url}\n\n"
        f"This invitation expires on {invitation.expires_at.strftime('%Y-%m-%d %H:%M UTC') if invitation.expires_at else 'never'}.\n\n"
        f"If you didn't expect this invitation, you can ignore this email."
    )

    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(
                django_settings, "DEFAULT_FROM_EMAIL", "noreply@midsphere.com"
            ),
            recipient_list=[invitation.email],
            fail_silently=True,
        )
    except Exception:
        logger.warning(
            "Failed to send invitation email to %s", invitation.email, exc_info=True
        )


# ── Security Policy ────────────────────────────────────────────────────────


@org_api.get("/{org_id}/security-policy", response=SecurityPolicyOut)
def get_security_policy(request, org_id: str):
    """Get the organization's security policy settings. Requires viewer+ role."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_ORG)
    return {
        "mfa_required": org.mfa_required,
        "session_timeout_minutes": org.session_timeout_minutes,
        "max_concurrent_sessions": org.max_concurrent_sessions,
    }


@org_api.patch(
    "/{org_id}/security-policy", response={200: SecurityPolicyOut, 400: ErrorOut}
)
def update_security_policy(request, org_id: str, body: UpdateSecurityPolicyRequest):
    """Update the organization's security policy. Requires admin+ role."""
    _require_org_access(request)
    from django.conf import settings as django_settings

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    min_timeout = getattr(django_settings, "SECURITY_MIN_SESSION_TIMEOUT_MINUTES", 5)
    max_timeout = getattr(
        django_settings, "SECURITY_MAX_SESSION_TIMEOUT_MINUTES", 43200
    )

    if body.mfa_required is not None:
        org.mfa_required = body.mfa_required

    if body.session_timeout_minutes is not None:
        if (
            body.session_timeout_minutes < min_timeout
            or body.session_timeout_minutes > max_timeout
        ):
            return 400, {
                "detail": f"session_timeout_minutes must be between {min_timeout} and {max_timeout}."
            }
        org.session_timeout_minutes = body.session_timeout_minutes

    if body.max_concurrent_sessions is not None:
        if body.max_concurrent_sessions < 1 or body.max_concurrent_sessions > 100:
            return 400, {"detail": "max_concurrent_sessions must be between 1 and 100."}
        org.max_concurrent_sessions = body.max_concurrent_sessions

    org.save()

    return 200, {
        "mfa_required": org.mfa_required,
        "session_timeout_minutes": org.session_timeout_minutes,
        "max_concurrent_sessions": org.max_concurrent_sessions,
    }


# ── SSO Configuration ─────────────────────────────────────────────────────


def _serialize_sso_config(sso_config) -> dict:
    """Build an SSOConfigOut-compatible dict."""
    return {
        "id": sso_config.pk,
        "organization_id": sso_config.organization_id,
        "provider_type": sso_config.provider_type,
        "metadata_url": sso_config.metadata_url,
        "entity_id": sso_config.entity_id,
        "certificate": sso_config.certificate,
        "is_active": sso_config.is_active,
        "enforce_sso": sso_config.enforce_sso,
        "emergency_bypass_enabled": sso_config.emergency_bypass_enabled,
        "created_at": sso_config.created_at,
        "updated_at": sso_config.updated_at,
    }


def _get_client_ip(request) -> str | None:
    """Extract client IP from X-Forwarded-For or REMOTE_ADDR."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


@org_api.post(
    "/{org_id}/sso", response={201: SSOConfigOut, 400: ErrorOut, 409: ErrorOut}
)
def create_sso_config(request, org_id: str, body: CreateSSOConfigRequest):
    """Create SSO configuration for an organization. Requires admin+ role."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import SSOConfiguration, SSOProviderType

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    # Validate provider_type
    valid_types = {t.value for t in SSOProviderType}
    if body.provider_type not in valid_types:
        return 400, {
            "detail": f"Invalid provider_type. Must be one of: {', '.join(sorted(valid_types))}"
        }

    # Check if SSO config already exists
    if hasattr(org, "sso_config"):
        try:
            org.sso_config
            return 409, {
                "detail": "SSO configuration already exists for this organization."
            }
        except SSOConfiguration.DoesNotExist:
            pass

    sso_config = SSOConfiguration.objects.create(
        organization=org,
        provider_type=body.provider_type,
        metadata_url=body.metadata_url,
        entity_id=body.entity_id,
        certificate=body.certificate,
        is_active=body.is_active,
        enforce_sso=body.enforce_sso,
    )

    AuditLog.log(
        action="sso_config_created",
        resource_type="sso_configuration",
        resource_id=str(sso_config.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "provider_type": sso_config.provider_type,
            "is_active": sso_config.is_active,
            "enforce_sso": sso_config.enforce_sso,
        },
    )

    return 201, _serialize_sso_config(sso_config)


@org_api.get("/{org_id}/sso", response={200: SSOConfigOut, 404: ErrorOut})
def get_sso_config(request, org_id: str):
    """Get SSO configuration for an organization. Requires admin+ role."""
    _require_org_access(request)
    from apps.workspace.models import SSOConfiguration

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        sso_config = org.sso_config
    except SSOConfiguration.DoesNotExist:
        return 404, {"detail": "No SSO configuration found for this organization."}

    return 200, _serialize_sso_config(sso_config)


@org_api.patch(
    "/{org_id}/sso", response={200: SSOConfigOut, 400: ErrorOut, 404: ErrorOut}
)
def update_sso_config(request, org_id: str, body: UpdateSSOConfigRequest):
    """Update SSO configuration for an organization. Requires admin+ role."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import SSOConfiguration, SSOProviderType

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        sso_config = org.sso_config
    except SSOConfiguration.DoesNotExist:
        return 404, {"detail": "No SSO configuration found for this organization."}

    changes = {}

    if body.provider_type is not None:
        valid_types = {t.value for t in SSOProviderType}
        if body.provider_type not in valid_types:
            return 400, {
                "detail": f"Invalid provider_type. Must be one of: {', '.join(sorted(valid_types))}"
            }
        changes["provider_type"] = {
            "old": sso_config.provider_type,
            "new": body.provider_type,
        }
        sso_config.provider_type = body.provider_type

    if body.metadata_url is not None:
        changes["metadata_url"] = {
            "old": sso_config.metadata_url,
            "new": body.metadata_url,
        }
        sso_config.metadata_url = body.metadata_url

    if body.entity_id is not None:
        changes["entity_id"] = {"old": sso_config.entity_id, "new": body.entity_id}
        sso_config.entity_id = body.entity_id

    if body.certificate is not None:
        changes["certificate"] = {"old": "***", "new": "***"}
        sso_config.certificate = body.certificate

    if body.is_active is not None:
        changes["is_active"] = {"old": sso_config.is_active, "new": body.is_active}
        sso_config.is_active = body.is_active

    if body.enforce_sso is not None:
        changes["enforce_sso"] = {
            "old": sso_config.enforce_sso,
            "new": body.enforce_sso,
        }
        sso_config.enforce_sso = body.enforce_sso

    if getattr(body, "emergency_bypass_enabled", None) is not None:
        changes["emergency_bypass_enabled"] = {
            "old": sso_config.emergency_bypass_enabled,
            "new": body.emergency_bypass_enabled,
        }
        sso_config.emergency_bypass_enabled = body.emergency_bypass_enabled

    sso_config.save()

    AuditLog.log(
        action="sso_config_updated",
        resource_type="sso_configuration",
        resource_id=str(sso_config.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        changes=changes,
        metadata={"organization_id": str(org.pk)},
    )

    return 200, _serialize_sso_config(sso_config)


@org_api.delete("/{org_id}/sso", response={200: ActionOut, 404: ErrorOut})
def delete_sso_config(request, org_id: str):
    """Delete SSO configuration for an organization. Requires admin+ role."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import SSOConfiguration

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        sso_config = org.sso_config
    except SSOConfiguration.DoesNotExist:
        return 404, {"detail": "No SSO configuration found for this organization."}

    config_id = str(sso_config.pk)
    sso_config.delete()

    AuditLog.log(
        action="sso_config_deleted",
        resource_type="sso_configuration",
        resource_id=config_id,
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={"organization_id": str(org.pk)},
    )

    return 200, {"success": True, "message": "SSO configuration deleted."}


@org_api.get("/{org_id}/sso/metadata", response={200: dict, 404: ErrorOut})
def get_sp_metadata(request, org_id: str):
    """Get SAML Service Provider metadata for the organization.

    Returns the SP metadata that admins provide to their IdP.
    Requires admin+ role.
    """
    _require_org_access(request)
    from django.conf import settings as django_settings

    from apps.workspace.models import SSOConfiguration

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        org.sso_config
    except SSOConfiguration.DoesNotExist:
        return 404, {"detail": "No SSO configuration found for this organization."}

    base_url = getattr(django_settings, "SITE_URL", "https://app.midsphere.com")
    sp_entity_id = f"{base_url}/api/v1/auth/saml/{org.slug}"
    acs_url = f"{base_url}/api/v1/auth/saml/{org.slug}/acs"
    slo_url = f"{base_url}/api/v1/auth/saml/{org.slug}/slo"

    return 200, {
        "entity_id": sp_entity_id,
        "acs_url": acs_url,
        "slo_url": slo_url,
        "name_id_format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        "org_slug": org.slug,
    }


# ── SCIM Token Management ─────────────────────────────────────────────────


@org_api.post(
    "/{org_id}/scim-tokens",
    response={201: SCIMTokenCreatedOut, 400: ErrorOut},
)
def create_scim_token(request, org_id: str, body: CreateSCIMTokenRequest):
    """Generate a new SCIM bearer token. Returns plaintext once. Requires admin+."""
    _require_org_access(request)
    import hashlib
    import ipaddress
    import secrets

    from apps.compliance.models import AuditLog
    from apps.workspace.models import SCIMToken

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    # Validate CIDRs
    for cidr in body.allowed_cidrs:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            return 400, {"detail": f"Invalid CIDR: {cidr}"}

    plaintext = secrets.token_hex(20)  # 40-char hex string
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()

    token = SCIMToken.objects.create(
        organization=org,
        name=body.name.strip(),
        token_hash=token_hash,
        prefix=plaintext[:8],
        allowed_cidrs=body.allowed_cidrs,
    )

    AuditLog.log(
        action="scim_token_created",
        resource_type="scim_token",
        resource_id=str(token.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "token_prefix": token.prefix,
            "allowed_cidrs": body.allowed_cidrs,
        },
    )

    return 201, {
        "id": token.pk,
        "name": token.name,
        "prefix": token.prefix,
        "token": plaintext,
        "is_active": token.is_active,
        "created_at": token.created_at,
        "allowed_cidrs": token.allowed_cidrs,
    }


@org_api.get("/{org_id}/scim-tokens", response=list[SCIMTokenOut])
def list_scim_tokens(request, org_id: str):
    """List all SCIM tokens for the organization (prefix + metadata only). Requires admin+."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    tokens = org.scim_tokens.order_by("-created_at")
    return [
        {
            "id": t.pk,
            "name": t.name,
            "prefix": t.prefix,
            "is_active": t.is_active,
            "created_at": t.created_at,
            "last_used_at": t.last_used_at,
            "last_used_ip": t.last_used_ip,
            "allowed_cidrs": t.allowed_cidrs,
        }
        for t in tokens
    ]


@org_api.delete(
    "/{org_id}/scim-tokens/{token_id}",
    response={200: ActionOut, 404: ErrorOut},
)
def revoke_scim_token(request, org_id: str, token_id: str):
    """Revoke (deactivate) a SCIM token. Requires admin+."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import SCIMToken

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        token = org.scim_tokens.get(pk=token_id)
    except (SCIMToken.DoesNotExist, ValueError):
        return 404, {"detail": "SCIM token not found."}

    token.is_active = False
    token.save(update_fields=["is_active"])

    AuditLog.log(
        action="scim_token_revoked",
        resource_type="scim_token",
        resource_id=str(token.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "token_prefix": token.prefix,
        },
    )

    return 200, {"success": True, "message": f"SCIM token {token.prefix}... revoked."}


# ── Force Logout ─────────────────────────────────────────────────────────


@org_api.post(
    "/{org_id}/force-logout",
    response={200: ActionOut, 400: ErrorOut},
)
def force_logout(request, org_id: str):
    """Force-logout all members of an organization. Requires admin+ role.

    Invalidates all Django sessions for org members and removes tracking records.
    """
    _require_org_access(request)
    from django.contrib.sessions.models import Session

    from apps.compliance.models import AuditLog, UserSession

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    # Get all org member user IDs
    member_user_ids = list(org.memberships.values_list("user_id", flat=True))

    # Delete tracked sessions for all org members
    tracked = UserSession.objects.filter(user_id__in=member_user_ids)
    session_keys = list(tracked.values_list("session_key", flat=True))
    session_count = len(session_keys)

    # Delete Django session records
    if session_keys:
        Session.objects.filter(session_key__in=session_keys).delete()

    # Delete tracking records
    tracked.delete()

    AuditLog.log(
        action="sso_force_logout",
        resource_type="organization",
        resource_id=str(org.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_name": org.name,
            "members_affected": len(member_user_ids),
            "sessions_invalidated": session_count,
        },
    )

    return 200, {
        "success": True,
        "message": f"Force-logged out {len(member_user_ids)} member(s), invalidated {session_count} session(s).",
    }


# ── Webhook integration endpoints ──────────────────────────────────────────


@org_api.get(
    "/{org_id}/integrations/slack",
    response={200: IntegrationOut, 404: ErrorOut},
    summary="Get Slack integration for an organization",
)
def get_slack_integration(request, org_id: str):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        integration = org.slack_integration
    except OrgSlackIntegration.DoesNotExist:
        raise NotFoundError("Slack integration not configured.")
    return {
        "webhook_url": integration.webhook_url,
        "channel_name": integration.channel_name,
        "is_active": integration.is_active,
    }


@org_api.put(
    "/{org_id}/integrations/slack",
    response={200: IntegrationOut},
    summary="Create or update Slack integration",
)
def upsert_slack_integration(request, org_id: str, body: UpdateIntegrationRequest):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    integration, _created = OrgSlackIntegration.objects.update_or_create(
        organization=org,
        defaults={
            "webhook_url": body.webhook_url,
            "channel_name": body.channel_name,
            "is_active": body.is_active,
        },
    )
    return {
        "webhook_url": integration.webhook_url,
        "channel_name": integration.channel_name,
        "is_active": integration.is_active,
    }


@org_api.delete(
    "/{org_id}/integrations/slack",
    response={200: ActionOut, 404: ErrorOut},
    summary="Delete Slack integration",
)
def delete_slack_integration(request, org_id: str):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        org.slack_integration.delete()
    except OrgSlackIntegration.DoesNotExist:
        raise NotFoundError("Slack integration not configured.")
    return {"detail": "Slack integration removed."}


@org_api.post(
    "/{org_id}/integrations/slack/test",
    response={200: IntegrationTestOut, 404: ErrorOut},
    summary="Send a test message to the Slack webhook",
)
def test_slack_integration(request, org_id: str):
    import requests as http_requests

    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        integration = org.slack_integration
    except OrgSlackIntegration.DoesNotExist:
        raise NotFoundError("Slack integration not configured.")
    try:
        resp = http_requests.post(
            integration.webhook_url,
            json={
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": "Jatayu AI Test"},
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"Test notification from *{org.name}*. If you see this, Slack is connected!",
                        },
                    },
                ]
            },
            timeout=10,
        )
        if resp.ok:
            return {"ok": True, "message": "Test message sent successfully."}
        return {
            "ok": False,
            "message": f"Slack returned {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:200]}


@org_api.get(
    "/{org_id}/integrations/discord",
    response={200: IntegrationOut, 404: ErrorOut},
    summary="Get Discord integration for an organization",
)
def get_discord_integration(request, org_id: str):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        integration = org.discord_integration
    except OrgDiscordIntegration.DoesNotExist:
        raise NotFoundError("Discord integration not configured.")
    return {
        "webhook_url": integration.webhook_url,
        "channel_name": integration.channel_name,
        "is_active": integration.is_active,
    }


@org_api.put(
    "/{org_id}/integrations/discord",
    response={200: IntegrationOut},
    summary="Create or update Discord integration",
)
def upsert_discord_integration(request, org_id: str, body: UpdateIntegrationRequest):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    integration, _created = OrgDiscordIntegration.objects.update_or_create(
        organization=org,
        defaults={
            "webhook_url": body.webhook_url,
            "channel_name": body.channel_name,
            "is_active": body.is_active,
        },
    )
    return {
        "webhook_url": integration.webhook_url,
        "channel_name": integration.channel_name,
        "is_active": integration.is_active,
    }


@org_api.delete(
    "/{org_id}/integrations/discord",
    response={200: ActionOut, 404: ErrorOut},
    summary="Delete Discord integration",
)
def delete_discord_integration(request, org_id: str):
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        org.discord_integration.delete()
    except OrgDiscordIntegration.DoesNotExist:
        raise NotFoundError("Discord integration not configured.")
    return {"detail": "Discord integration removed."}


@org_api.post(
    "/{org_id}/integrations/discord/test",
    response={200: IntegrationTestOut, 404: ErrorOut},
    summary="Send a test message to the Discord webhook",
)
def test_discord_integration(request, org_id: str):
    import requests as http_requests

    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    try:
        integration = org.discord_integration
    except OrgDiscordIntegration.DoesNotExist:
        raise NotFoundError("Discord integration not configured.")
    try:
        resp = http_requests.post(
            integration.webhook_url,
            json={
                "embeds": [
                    {
                        "title": "Jatayu AI Test",
                        "description": f"Test notification from **{org.name}**. If you see this, Discord is connected!",
                        "color": 5814783,
                    }
                ]
            },
            timeout=10,
        )
        if resp.ok:
            return {"ok": True, "message": "Test message sent successfully."}
        return {
            "ok": False,
            "message": f"Discord returned {resp.status_code}: {resp.text[:200]}",
        }
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:200]}


# ── IP Allowlist ───────────────────────────────────────────────────────────


def _validate_cidr(cidr_str: str) -> bool:
    """Return True if cidr_str is a valid IPv4 or IPv6 CIDR."""
    import ipaddress

    try:
        ipaddress.ip_network(cidr_str, strict=False)
        return True
    except ValueError:
        return False


def _serialize_ip_entry(entry: IPAllowlistEntry) -> dict:
    return {
        "id": entry.pk,
        "organization_id": entry.organization_id,
        "cidr_range": entry.cidr_range,
        "description": entry.description,
        "is_active": entry.is_active,
        "created_at": entry.created_at,
    }


@org_api.get(
    "/{org_id}/ip-allowlist",
    response=IPAllowlistListOut,
)
def list_ip_allowlist(request, org_id: str):
    """List IP allowlist entries for an organization. Admin+ only."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    entries = IPAllowlistEntry.objects.filter(organization=org)
    return {
        "entries": [_serialize_ip_entry(e) for e in entries],
        "your_ip": _get_client_ip(request),
    }


@org_api.post(
    "/{org_id}/ip-allowlist",
    response={201: IPAllowlistEntryOut, 400: ErrorOut},
)
def add_ip_allowlist_entry(request, org_id: str, body: CreateIPAllowlistRequest):
    """Add an IP allowlist entry to an organization. Admin+ only."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    cidr = body.cidr_range.strip()
    if not _validate_cidr(cidr):
        return 400, {"detail": f"Invalid CIDR range: {cidr}"}

    entry = IPAllowlistEntry.objects.create(
        organization=org,
        cidr_range=cidr,
        description=body.description.strip(),
        is_active=body.is_active,
    )

    AuditLog.log(
        action="ip_allowlist_added",
        resource_type="ip_allowlist",
        resource_id=str(entry.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "cidr_range": cidr,
            "description": entry.description,
        },
    )

    return 201, _serialize_ip_entry(entry)


@org_api.delete(
    "/{org_id}/ip-allowlist/{entry_id}",
    response={200: ActionOut, 404: ErrorOut},
)
def remove_ip_allowlist_entry(request, org_id: str, entry_id: str):
    """Remove an IP allowlist entry. Admin+ only."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        entry = IPAllowlistEntry.objects.get(pk=entry_id, organization=org)
    except (IPAllowlistEntry.DoesNotExist, ValueError):
        return 404, {"detail": "IP allowlist entry not found."}

    cidr = entry.cidr_range
    entry_pk = str(entry.pk)
    entry.delete()

    AuditLog.log(
        action="ip_allowlist_removed",
        resource_type="ip_allowlist",
        resource_id=entry_pk,
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "cidr_range": cidr,
        },
    )

    return 200, {"success": True, "message": f"IP allowlist entry {cidr} removed."}


# ── Analytics ──────────────────────────────────────────────────────────────


def _parse_date_range(request) -> tuple:
    """Parse date range from query params. Returns (start, end) datetimes."""
    from datetime import timedelta

    now = timezone.now()
    period = request.GET.get("period", "30d")
    start_date = request.GET.get("start_date")
    end_date = request.GET.get("end_date")

    if start_date and end_date:
        from datetime import datetime as dt

        try:
            start = timezone.make_aware(dt.fromisoformat(start_date))
            end = timezone.make_aware(dt.fromisoformat(end_date))
        except (ValueError, TypeError):
            start = now - timedelta(days=30)
            end = now
    else:
        period_days = {"7d": 7, "30d": 30, "90d": 90}.get(period, 30)
        start = now - timedelta(days=period_days)
        end = now

    return start, end


@org_api.get(
    "/{org_id}/analytics/summary",
    response={200: AnalyticsSummaryOut, 403: ErrorOut, 404: ErrorOut},
)
def analytics_summary(request, org_id: str):
    """Org usage analytics summary: runs, credits, members, conversations."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_ANALYTICS)

    from django.db.models import Sum

    from apps.billing.models import CreditTransaction
    from apps.storage.models import AgentRun, Conversation

    start, end = _parse_date_range(request)

    # Agent runs scoped to org projects
    total_runs = AgentRun.objects.filter(
        conversation__project__organization=org,
        created_at__gte=start,
        created_at__lte=end,
    ).count()

    # Conversations scoped to org projects
    total_conversations = Conversation.objects.filter(
        project__organization=org,
        date_created__gte=start,
        date_created__lte=end,
    ).count()

    # Credits consumed by org members (debit transactions only)
    member_user_ids = org.memberships.values_list("user_id", flat=True)
    credits_result = CreditTransaction.objects.filter(
        wallet__user_id__in=member_user_ids,
        amount__lt=0,
        created_at__gte=start,
        created_at__lte=end,
    ).aggregate(total=Sum("amount"))
    total_credits = abs(credits_result["total"] or 0)

    # Active members: had at least one agent run in period
    active_members = (
        AgentRun.objects.filter(
            conversation__project__organization=org,
            created_at__gte=start,
            created_at__lte=end,
            user__in=member_user_ids,
        )
        .values("user_id")
        .distinct()
        .count()
    )

    return 200, {
        "total_agent_runs": total_runs,
        "total_credits_consumed": total_credits,
        "active_members": active_members,
        "total_conversations": total_conversations,
        "period_start": start,
        "period_end": end,
    }


@org_api.get(
    "/{org_id}/analytics/members",
    response={200: MemberAnalyticsOut, 403: ErrorOut, 404: ErrorOut},
)
def analytics_members(request, org_id: str):
    """Per-member analytics: runs, credits, conversations. Paginated + sortable."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_ANALYTICS)

    from django.db.models import Sum

    from apps.billing.models import CreditTransaction
    from apps.storage.models import AgentRun, Conversation

    start, end = _parse_date_range(request)
    page = max(int(request.GET.get("page", 1)), 1)
    page_size = min(max(int(request.GET.get("page_size", 20)), 1), 100)
    sort_by = request.GET.get("sort_by", "agent_runs_count")
    sort_order = request.GET.get("sort_order", "desc")

    # Include current AND former members (for removed member attribution)
    # Current members from memberships
    current_memberships = org.memberships.select_related("user").all()
    current_user_ids = set(m.user_id for m in current_memberships)
    current_user_map = {m.user_id: m.user for m in current_memberships}

    # Former members: users who have runs in org projects but are not current members
    former_user_ids = set(
        AgentRun.objects.filter(
            conversation__project__organization=org,
            created_at__gte=start,
            created_at__lte=end,
        )
        .exclude(user_id__in=current_user_ids)
        .exclude(user_id__isnull=True)
        .values_list("user_id", flat=True)
        .distinct()
    )

    all_user_ids = current_user_ids | former_user_ids

    if not all_user_ids:
        return 200, {
            "page": page,
            "page_size": page_size,
            "total": 0,
            "total_pages": 0,
            "results": [],
        }

    # Build per-user stats
    results = []
    for uid in all_user_ids:
        # Agent runs
        runs = AgentRun.objects.filter(
            conversation__project__organization=org,
            user_id=uid,
            created_at__gte=start,
            created_at__lte=end,
        )
        runs_count = runs.count()
        last_run = (
            runs.order_by("-created_at").values_list("created_at", flat=True).first()
        )

        # Conversations
        convs_count = Conversation.objects.filter(
            project__organization=org,
            user_id=uid,
            date_created__gte=start,
            date_created__lte=end,
        ).count()

        # Credits consumed
        credits_agg = CreditTransaction.objects.filter(
            wallet__user_id=uid,
            amount__lt=0,
            created_at__gte=start,
            created_at__lte=end,
        ).aggregate(total=Sum("amount"))
        credits = abs(credits_agg["total"] or 0)

        # User info
        if uid in current_user_ids:
            user = current_user_map[uid]
            email = user.email
            name = user.name or ""
        else:
            # Former member — try to get user info
            from apps.users.models import User

            try:
                user = User.objects.get(pk=uid)
                email = user.email
                name = f"{user.name or ''} (removed)"
            except User.DoesNotExist:
                email = "unknown"
                name = "[Deleted User] (removed)"

        results.append(
            {
                "user_id": uid,
                "email": email,
                "name": name,
                "agent_runs_count": runs_count,
                "credits_consumed": credits,
                "conversations_count": convs_count,
                "last_active": last_run,
            }
        )

    # Sort
    valid_sorts = {
        "agent_runs_count",
        "credits_consumed",
        "conversations_count",
        "last_active",
        "name",
        "email",
    }
    if sort_by not in valid_sorts:
        sort_by = "agent_runs_count"
    reverse = sort_order == "desc"
    results.sort(
        key=lambda r: (
            r[sort_by] is None,
            r[sort_by] or 0 if isinstance(r[sort_by], int) else r[sort_by] or "",
        ),
        reverse=reverse,
    )

    # Paginate
    total = len(results)
    total_pages = max((total + page_size - 1) // page_size, 1)
    start_idx = (page - 1) * page_size
    page_results = results[start_idx : start_idx + page_size]

    # CSV export
    if request.GET.get("format") == "csv":
        import csv
        import io

        from django.http import HttpResponse

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Email",
                "Name",
                "Agent Runs",
                "Credits Consumed",
                "Conversations",
                "Last Active",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r["email"],
                    r["name"],
                    r["agent_runs_count"],
                    r["credits_consumed"],
                    r["conversations_count"],
                    r["last_active"] or "",
                ]
            )
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=member_analytics.csv"
        return response

    return 200, {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "results": page_results,
    }


@org_api.get(
    "/{org_id}/analytics/projects",
    response={200: ProjectAnalyticsOut, 403: ErrorOut, 404: ErrorOut},
)
def analytics_projects(request, org_id: str):
    """Per-project analytics: runs, credits, unique users. Paginated + sortable."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_ANALYTICS)

    from django.db.models import Sum

    from apps.billing.models import CreditHold, CreditTransaction
    from apps.spaces.models import Project
    from apps.storage.models import AgentRun

    start, end = _parse_date_range(request)
    page = max(int(request.GET.get("page", 1)), 1)
    page_size = min(max(int(request.GET.get("page_size", 20)), 1), 100)
    sort_by = request.GET.get("sort_by", "agent_runs")
    sort_order = request.GET.get("sort_order", "desc")

    # Current org projects
    current_projects = Project.objects.filter(organization=org)
    current_project_ids = set(current_projects.values_list("pk", flat=True))

    # Former org projects: had runs in org context but no longer belong to org
    # These are identified by AgentRuns whose conversation.project was once in this org
    # For now, we track only current projects and annotated moved projects via AgentRun metadata

    results = []
    for project in current_projects:
        runs = AgentRun.objects.filter(
            conversation__project=project,
            created_at__gte=start,
            created_at__lte=end,
        )
        runs_count = runs.count()
        unique_users = runs.values("user_id").distinct().count()
        last_activity = (
            runs.order_by("-created_at").values_list("created_at", flat=True).first()
        )

        # Credits: sum debit transactions associated with holds on runs in this project
        hold_ids = CreditHold.objects.filter(
            run__conversation__project=project,
            run__created_at__gte=start,
            run__created_at__lte=end,
        ).values_list("pk", flat=True)
        credits_agg = CreditTransaction.objects.filter(
            hold_id__in=hold_ids,
            amount__lt=0,
        ).aggregate(total=Sum("amount"))
        credits = abs(credits_agg["total"] or 0)

        results.append(
            {
                "project_id": project.pk,
                "title": project.title or "(untitled)",
                "agent_runs": runs_count,
                "credits_consumed": credits,
                "unique_users": unique_users,
                "last_activity": last_activity,
                "note": "",
            }
        )

    # Sort
    valid_sorts = {
        "agent_runs",
        "credits_consumed",
        "unique_users",
        "last_activity",
        "title",
    }
    if sort_by not in valid_sorts:
        sort_by = "agent_runs"
    reverse = sort_order == "desc"
    results.sort(
        key=lambda r: (
            r[sort_by] is None,
            r[sort_by] or 0 if isinstance(r[sort_by], int) else r[sort_by] or "",
        ),
        reverse=reverse,
    )

    # Paginate
    total = len(results)
    total_pages = max((total + page_size - 1) // page_size, 1)
    start_idx = (page - 1) * page_size
    page_results = results[start_idx : start_idx + page_size]

    # CSV export
    if request.GET.get("format") == "csv":
        import csv
        import io

        from django.http import HttpResponse

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Project ID",
                "Title",
                "Agent Runs",
                "Credits Consumed",
                "Unique Users",
                "Last Activity",
                "Note",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r["project_id"],
                    r["title"],
                    r["agent_runs"],
                    r["credits_consumed"],
                    r["unique_users"],
                    r["last_activity"] or "",
                    r["note"],
                ]
            )
        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = "attachment; filename=project_analytics.csv"
        return response

    return 200, {
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "results": page_results,
    }


# ── Cost Controls ────────────────────────────────────────────────────────────


@org_api.patch(
    "/{org_id}/cost-policy",
    response={200: CostPolicyOut, 403: ErrorOut, 404: ErrorOut},
)
def update_cost_policy(request, org_id: str, body: UpdateCostPolicyRequest):
    """Set member monthly credit limit and alert threshold for an org."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import OrgCostPolicy

    policy, _ = OrgCostPolicy.objects.get_or_create(organization=org)

    if body.member_monthly_credit_limit is not None:
        policy.member_monthly_credit_limit = body.member_monthly_credit_limit or None
    if body.alert_threshold_percent is not None:
        policy.alert_threshold_percent = body.alert_threshold_percent
    policy.save()

    return 200, {
        "member_monthly_credit_limit": policy.member_monthly_credit_limit,
        "alert_threshold_percent": policy.alert_threshold_percent,
    }


@org_api.get(
    "/{org_id}/cost-status",
    response={200: CostStatusOut, 403: ErrorOut, 404: ErrorOut},
)
def cost_status(request, org_id: str):
    """Current month usage per member and per project."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.VIEW_ANALYTICS)

    from apps.spaces.models import Project, ProjectBudget
    from apps.workspace.cost_controls import get_member_monthly_usage
    from apps.workspace.models import OrgCostPolicy

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get cost policy
    try:
        policy = org.cost_policy
        limit = policy.member_monthly_credit_limit
        alert_pct = policy.alert_threshold_percent
    except OrgCostPolicy.DoesNotExist:
        limit = None
        alert_pct = 80

    # Per-member usage
    members_data = []
    for membership in org.memberships.select_related("user").all():
        user = membership.user
        usage = get_member_monthly_usage(user, org, month_start)
        pct = round(usage / limit * 100, 1) if limit and limit > 0 else None
        members_data.append(
            {
                "user_id": user.id,
                "email": getattr(user, "email", ""),
                "name": getattr(user, "display_name", "") or getattr(user, "email", ""),
                "credits_consumed": usage,
                "limit": limit,
                "percent_used": pct,
            }
        )

    # Per-project usage
    projects_data = []
    org_projects = Project.objects.filter(organization=org)
    budgets = {
        b.project_id: b for b in ProjectBudget.objects.filter(project__organization=org)
    }

    for proj in org_projects:
        budget = budgets.get(proj.id)
        proj_usage = budget.current_month_usage if budget else 0
        proj_limit = budget.monthly_credit_limit if budget else None
        pct = (
            round(proj_usage / proj_limit * 100, 1)
            if proj_limit and proj_limit > 0
            else None
        )
        projects_data.append(
            {
                "project_id": proj.id,
                "title": proj.title,
                "current_month_usage": proj_usage,
                "monthly_credit_limit": proj_limit,
                "percent_used": pct,
            }
        )

    return 200, {
        "member_monthly_credit_limit": limit,
        "alert_threshold_percent": alert_pct,
        "members": members_data,
        "projects": projects_data,
    }


# ── Model Policy ─────────────────────────────────────────────────────────────


@org_api.get(
    "/{org_id}/model-policy",
    response={200: ModelPolicyOut, 403: ErrorOut, 404: ErrorOut},
)
def get_model_policy(request, org_id: str):
    """Return the org's model restriction policy."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import OrgModelPolicy

    try:
        policy = org.model_policy
    except OrgModelPolicy.DoesNotExist:
        return 200, {
            "allowed_models": [],
            "allowed_providers": [],
            "block_byom": False,
        }

    return 200, {
        "allowed_models": policy.allowed_models or [],
        "allowed_providers": policy.allowed_providers or [],
        "block_byom": policy.block_byom,
    }


@org_api.patch(
    "/{org_id}/model-policy",
    response={200: ModelPolicyOut, 403: ErrorOut, 404: ErrorOut},
)
def update_model_policy(request, org_id: str, body: UpdateModelPolicyRequest):
    """Set model restrictions for an org (admin+)."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import OrgModelPolicy

    policy, _ = OrgModelPolicy.objects.get_or_create(organization=org)

    if body.allowed_models is not None:
        policy.allowed_models = body.allowed_models
    if body.allowed_providers is not None:
        policy.allowed_providers = body.allowed_providers
    if body.block_byom is not None:
        policy.block_byom = body.block_byom
    policy.save()

    return 200, {
        "allowed_models": policy.allowed_models or [],
        "allowed_providers": policy.allowed_providers or [],
        "block_byom": policy.block_byom,
    }


# ── Agent Policy ─────────────────────────────────────────────────────


@org_api.get(
    "/{org_id}/agent-policy",
    response={200: AgentPolicyOut, 403: ErrorOut, 404: ErrorOut},
)
def get_agent_policy(request, org_id: str):
    """Return the org's agent guardrail policy."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import OrgAgentPolicy

    try:
        policy = org.agent_policy
    except OrgAgentPolicy.DoesNotExist:
        return 200, {
            "blocked_tools": [],
            "blocked_tool_groups": [],
            "require_hitl_for": [],
        }

    return 200, {
        "blocked_tools": policy.blocked_tools or [],
        "blocked_tool_groups": policy.blocked_tool_groups or [],
        "require_hitl_for": policy.require_hitl_for or [],
    }


@org_api.patch(
    "/{org_id}/agent-policy",
    response={200: AgentPolicyOut, 403: ErrorOut, 404: ErrorOut},
)
def update_agent_policy(request, org_id: str, body: UpdateAgentPolicyRequest):
    """Set agent guardrails for an org (admin+)."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import OrgAgentPolicy

    policy, _ = OrgAgentPolicy.objects.get_or_create(organization=org)

    if body.blocked_tools is not None:
        policy.blocked_tools = body.blocked_tools
    if body.blocked_tool_groups is not None:
        policy.blocked_tool_groups = body.blocked_tool_groups
    if body.require_hitl_for is not None:
        policy.require_hitl_for = body.require_hitl_for
    policy.save()

    return 200, {
        "blocked_tools": policy.blocked_tools or [],
        "blocked_tool_groups": policy.blocked_tool_groups or [],
        "require_hitl_for": policy.require_hitl_for or [],
    }


# ── DLP Policy Management ──────────────────────────────────────────────


@org_api.get(
    "/{org_id}/dlp-policy",
    response={200: DLPPolicyOut, 404: ErrorOut},
)
def get_dlp_policy(request, org_id: str):
    """Return the org's DLP scan policy."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    from apps.workspace.models import DLPPolicy

    try:
        policy = org.dlp_policy
    except DLPPolicy.DoesNotExist:
        return 200, {"scan_patterns": [], "is_active": True}

    return 200, {
        "scan_patterns": [
            {"name": p["name"], "regex": p["regex"], "action": p["action"]}
            for p in (policy.scan_patterns or [])
        ],
        "is_active": policy.is_active,
    }


@org_api.patch(
    "/{org_id}/dlp-policy",
    response={200: DLPPolicyOut, 400: ErrorOut, 404: ErrorOut},
)
def update_dlp_policy(request, org_id: str, body: UpdateDLPPolicyRequest):
    """Update DLP scan patterns for an org (admin+)."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    import re as re_mod

    from apps.workspace.dlp_policy import DEFAULT_SCAN_PATTERNS
    from apps.workspace.models import DLPPolicy

    policy, created = DLPPolicy.objects.get_or_create(
        organization=org,
        defaults={"scan_patterns": DEFAULT_SCAN_PATTERNS},
    )

    if body.scan_patterns is not None:
        # Validate regexes
        for p in body.scan_patterns:
            if p.action not in ("block", "redact"):
                return 400, {
                    "detail": f"Invalid action '{p.action}' for pattern '{p.name}'. Must be 'block' or 'redact'."
                }
            try:
                re_mod.compile(p.regex)
            except re_mod.error as exc:
                return 400, {"detail": f"Invalid regex for pattern '{p.name}': {exc}"}
        policy.scan_patterns = [
            {"name": p.name, "regex": p.regex, "action": p.action}
            for p in body.scan_patterns
        ]
    if body.is_active is not None:
        policy.is_active = body.is_active
    policy.save()

    return 200, {
        "scan_patterns": [
            {"name": p["name"], "regex": p["regex"], "action": p["action"]}
            for p in (policy.scan_patterns or [])
        ],
        "is_active": policy.is_active,
    }


@org_api.post(
    "/{org_id}/dlp-policy/test",
    response={200: DLPTestOut, 404: ErrorOut},
)
def test_dlp_policy(request, org_id: str, body: DLPTestRequest):
    """Test DLP patterns against sample text without sending.

    Returns which patterns match, the redacted text, and whether
    the message would be blocked.
    """
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    import re as re_mod

    from apps.workspace.models import DLPPolicy

    try:
        policy = org.dlp_policy
    except DLPPolicy.DoesNotExist:
        return 200, {
            "matches": [],
            "redacted_text": body.text,
            "would_block": False,
            "block_pattern": None,
        }

    patterns = policy.scan_patterns or []
    matches = []
    redacted_text = body.text
    would_block = False
    block_pattern = None

    for pattern in patterns:
        name = pattern.get("name", "Unknown")
        regex = pattern.get("regex", "")
        action = pattern.get("action", "redact")

        if not regex:
            matches.append({"pattern_name": name, "action": action, "matched": False})
            continue

        try:
            compiled = re_mod.compile(regex)
        except re_mod.error:
            matches.append({"pattern_name": name, "action": action, "matched": False})
            continue

        found = bool(compiled.search(body.text))
        matches.append({"pattern_name": name, "action": action, "matched": found})

        if found and action == "block":
            would_block = True
            if block_pattern is None:
                block_pattern = name
        elif found and action == "redact":
            redacted_text = compiled.sub("[REDACTED]", redacted_text)

    return 200, {
        "matches": matches,
        "redacted_text": redacted_text,
        "would_block": would_block,
        "block_pattern": block_pattern,
    }


# ── Org API Key Management ──────────────────────────────────────────────


@org_api.post(
    "/{org_id}/api-keys",
    response={201: OrgAPIKeyCreatedOut, 400: ErrorOut, 404: ErrorOut},
)
def create_org_api_key(request, org_id: str, body: CreateOrgAPIKeyRequest):
    """Create a new org-level API key. Returns plaintext once. Requires admin+."""
    _require_org_access(request)
    import hashlib
    import secrets

    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgAPIKey

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    # Determine billing user
    billing_user = request.auth
    if body.billing_user_id is not None:
        try:
            billing_user = User.objects.get(pk=body.billing_user_id)
            # billing user must be a member of the org
            if not get_org_membership(billing_user, org):
                return 400, {
                    "detail": "Billing user is not a member of this organization."
                }
        except User.DoesNotExist:
            return 400, {"detail": "Billing user not found."}

    plaintext = secrets.token_hex(20)  # 40-char hex string
    key_hash = hashlib.sha256(plaintext.encode()).hexdigest()

    api_key = OrgAPIKey.objects.create(
        organization=org,
        name=body.name.strip(),
        key_hash=key_hash,
        key_prefix=plaintext[:8],
        scopes=body.scopes,
        created_by=request.auth,
        billing_user=billing_user,
        rate_limit_per_minute=body.rate_limit_per_minute,
    )

    AuditLog.log(
        action="org_api_key_created",
        resource_type="org_api_key",
        resource_id=str(api_key.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "key_prefix": api_key.key_prefix,
            "scopes": body.scopes,
            "rate_limit_per_minute": body.rate_limit_per_minute,
        },
    )

    return 201, {
        "id": api_key.pk,
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "key": plaintext,
        "scopes": api_key.scopes or [],
        "is_active": api_key.is_active,
        "rate_limit_per_minute": api_key.rate_limit_per_minute,
        "created_at": api_key.created_at,
    }


@org_api.get("/{org_id}/api-keys", response=list[OrgAPIKeyOut])
def list_org_api_keys(request, org_id: str):
    """List all API keys for the organization. Requires admin+."""
    _require_org_access(request)

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    keys = org.api_keys.order_by("-created_at")
    return [
        {
            "id": k.pk,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "scopes": k.scopes or [],
            "is_active": k.is_active,
            "rate_limit_per_minute": k.rate_limit_per_minute,
            "created_by_email": k.created_by.email
            if k.created_by
            else "[removed user]",
            "billing_user_email": k.billing_user.email if k.billing_user else None,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
        }
        for k in keys.select_related("created_by", "billing_user")
    ]


@org_api.delete(
    "/{org_id}/api-keys/{key_id}",
    response={200: ActionOut, 404: ErrorOut},
)
def revoke_org_api_key(request, org_id: str, key_id: str):
    """Revoke (deactivate) an org API key. Requires admin+."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgAPIKey

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        api_key = org.api_keys.get(pk=key_id)
    except (OrgAPIKey.DoesNotExist, ValueError):
        return 404, {"detail": "API key not found."}

    api_key.is_active = False
    api_key.save(update_fields=["is_active"])

    AuditLog.log(
        action="org_api_key_revoked",
        resource_type="org_api_key",
        resource_id=str(api_key.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "key_prefix": api_key.key_prefix,
        },
    )

    return 200, {
        "success": True,
        "message": f"API key {api_key.key_prefix}... revoked.",
    }


# ── Outbound Webhooks ──────────────────────────────────────────────────────


from apps.workspace.org_schemas import (  # noqa: E402
    CreateWebhookRequest,
    UpdateWebhookRequest,
    WebhookDeliveryLogOut,
    WebhookOut,
)


def _serialize_webhook(wh) -> dict:
    """Build a WebhookOut-compatible dict (excluding secret)."""
    return {
        "id": wh.pk,
        "organization_id": wh.organization_id,
        "url": wh.url,
        "events": wh.events or [],
        "destination_type": wh.destination_type,
        "is_active": wh.is_active,
        "failure_count": wh.failure_count,
        "created_at": wh.created_at,
        "updated_at": wh.updated_at,
    }


_VALID_WEBHOOK_EVENTS = {
    "agent_run.completed",
    "agent_run.failed",
    "member.joined",
    "member.removed",
    "project.created",
    "project.shared",
    "audit.security_event",
    "dlp.violation",
}

_VALID_DESTINATION_TYPES = {"generic", "slack", "discord"}


@org_api.get(
    "/{org_id}/webhooks",
    response=list[WebhookOut],
)
def list_webhooks(request, org_id: str):
    """List all outbound webhooks for an organization. Requires admin+."""
    _require_org_access(request)
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    webhooks = OrgWebhook.objects.filter(organization=org).order_by("-created_at")
    return [_serialize_webhook(wh) for wh in webhooks]


@org_api.post(
    "/{org_id}/webhooks",
    response={201: WebhookOut, 400: ErrorOut},
)
def create_webhook(request, org_id: str, body: CreateWebhookRequest):
    """Create an outbound webhook subscription. Requires admin+."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    # Validate events
    invalid = set(body.events) - _VALID_WEBHOOK_EVENTS
    if invalid:
        return 400, {"detail": f"Invalid event types: {', '.join(sorted(invalid))}"}

    if not body.events:
        return 400, {"detail": "At least one event type is required."}

    # Validate destination type
    dest = body.destination_type
    if dest not in _VALID_DESTINATION_TYPES:
        return 400, {"detail": f"Invalid destination_type: {dest}"}

    wh = OrgWebhook.objects.create(
        organization=org,
        url=body.url,
        secret=body.secret,
        events=body.events,
        destination_type=dest,
    )

    AuditLog.log(
        action="webhook_created",
        resource_type="webhook",
        resource_id=str(wh.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "url": wh.url,
            "events": wh.events,
            "destination_type": dest,
        },
    )

    return 201, _serialize_webhook(wh)


@org_api.get(
    "/{org_id}/webhooks/{webhook_id}",
    response={200: WebhookOut, 404: ErrorOut},
)
def get_webhook(request, org_id: str, webhook_id: str):
    """Get a single webhook. Requires admin+."""
    _require_org_access(request)
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    try:
        wh = org.webhooks.get(pk=webhook_id)
    except (OrgWebhook.DoesNotExist, ValueError):
        return 404, {"detail": "Webhook not found."}

    return 200, _serialize_webhook(wh)


@org_api.patch(
    "/{org_id}/webhooks/{webhook_id}",
    response={200: WebhookOut, 400: ErrorOut, 404: ErrorOut},
)
def update_webhook(request, org_id: str, webhook_id: str, body: UpdateWebhookRequest):
    """Update an outbound webhook. Requires admin+."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    try:
        wh = org.webhooks.get(pk=webhook_id)
    except (OrgWebhook.DoesNotExist, ValueError):
        return 404, {"detail": "Webhook not found."}

    changes = {}
    if body.url is not None:
        changes["url"] = body.url
        wh.url = body.url
    if body.secret is not None:
        changes["secret"] = "***"
        wh.secret = body.secret
    if body.events is not None:
        invalid = set(body.events) - _VALID_WEBHOOK_EVENTS
        if invalid:
            return 400, {"detail": f"Invalid event types: {', '.join(sorted(invalid))}"}
        if not body.events:
            return 400, {"detail": "At least one event type is required."}
        changes["events"] = body.events
        wh.events = body.events
    if body.destination_type is not None:
        if body.destination_type not in _VALID_DESTINATION_TYPES:
            return 400, {"detail": f"Invalid destination_type: {body.destination_type}"}
        changes["destination_type"] = body.destination_type
        wh.destination_type = body.destination_type
    if body.is_active is not None:
        changes["is_active"] = body.is_active
        wh.is_active = body.is_active
        # Reset failure count when re-enabling
        if body.is_active:
            wh.failure_count = 0

    wh.save()

    AuditLog.log(
        action="webhook_updated",
        resource_type="webhook",
        resource_id=str(wh.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "changes": changes,
        },
    )

    return 200, _serialize_webhook(wh)


@org_api.delete(
    "/{org_id}/webhooks/{webhook_id}",
    response={200: ActionOut, 404: ErrorOut},
)
def delete_webhook(request, org_id: str, webhook_id: str):
    """Delete an outbound webhook. Requires admin+."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    try:
        wh = org.webhooks.get(pk=webhook_id)
    except (OrgWebhook.DoesNotExist, ValueError):
        return 404, {"detail": "Webhook not found."}

    wh_id = str(wh.pk)
    wh_url = wh.url
    wh.delete()

    AuditLog.log(
        action="webhook_deleted",
        resource_type="webhook",
        resource_id=wh_id,
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "url": wh_url,
        },
    )

    return 200, {"success": True, "message": "Webhook deleted."}


@org_api.post(
    "/{org_id}/webhooks/{webhook_id}/test",
    response={200: ActionOut, 404: ErrorOut},
)
def test_webhook(request, org_id: str, webhook_id: str):
    """Send a test event to a webhook to verify the endpoint. Requires admin+."""
    _require_org_access(request)
    from apps.workspace.models import OrgWebhook

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    try:
        wh = org.webhooks.get(pk=webhook_id)
    except (OrgWebhook.DoesNotExist, ValueError):
        return 404, {"detail": "Webhook not found."}

    from apps.workspace.tasks import send_test_webhook_event

    result = send_test_webhook_event(str(wh.pk))

    return 200, {
        "success": result.get("ok", False),
        "message": result.get("message", ""),
    }


@org_api.get(
    "/{org_id}/webhooks/{webhook_id}/deliveries",
    response={200: list[WebhookDeliveryLogOut], 404: ErrorOut},
)
def list_webhook_deliveries(request, org_id: str, webhook_id: str):
    """List recent deliveries for a webhook (last 100). Requires admin+."""
    _require_org_access(request)
    from apps.workspace.models import OrgWebhook, WebhookDeliveryLog

    org = _get_org_or_404(org_id)
    check_org_permission(request.auth, org, OrgPermission.MANAGE_WEBHOOKS)

    try:
        wh = org.webhooks.get(pk=webhook_id)
    except (OrgWebhook.DoesNotExist, ValueError):
        return 404, {"detail": "Webhook not found."}

    logs = WebhookDeliveryLog.objects.filter(webhook=wh).order_by("-created_at")[:100]
    return 200, [
        {
            "id": log.pk,
            "event_type": log.event_type,
            "status_code": log.status_code,
            "response_time_ms": log.response_time_ms,
            "success": log.success,
            "error_message": log.error_message,
            "created_at": log.created_at,
        }
        for log in logs
    ]


# ── Conditional Access Policies ──────────────────────────────────────────


def _serialize_access_policy(policy: ConditionalAccessPolicy) -> dict:
    return {
        "id": policy.pk,
        "organization_id": policy.organization_id,
        "name": policy.name,
        "conditions": policy.conditions,
        "action": policy.action,
        "is_active": policy.is_active,
        "priority": policy.priority,
        "created_at": policy.created_at,
        "updated_at": policy.updated_at,
    }


def _validate_conditions(conditions: list) -> str | None:
    """Validate condition objects. Returns error message or None."""
    import ipaddress
    import re as _re

    valid_types = {"ip_range", "time_of_day", "day_of_week", "user_agent_pattern"}
    for cond in conditions:
        ctype = (
            cond.get("type") if isinstance(cond, dict) else getattr(cond, "type", None)
        )
        if ctype not in valid_types:
            return f"Invalid condition type: {ctype}. Must be one of {sorted(valid_types)}."

        if ctype == "ip_range":
            cidr = (
                cond.get("cidr")
                if isinstance(cond, dict)
                else getattr(cond, "cidr", None)
            )
            if not cidr:
                return "ip_range condition requires 'cidr' field."
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                return f"Invalid CIDR range: {cidr}"

        elif ctype == "time_of_day":
            sh = (
                cond.get("start_hour")
                if isinstance(cond, dict)
                else getattr(cond, "start_hour", None)
            )
            eh = (
                cond.get("end_hour")
                if isinstance(cond, dict)
                else getattr(cond, "end_hour", None)
            )
            if sh is None or eh is None:
                return "time_of_day condition requires 'start_hour' and 'end_hour'."
            if not (0 <= sh <= 23) or not (0 <= eh <= 23):
                return "start_hour and end_hour must be between 0 and 23."

        elif ctype == "day_of_week":
            days = (
                cond.get("days")
                if isinstance(cond, dict)
                else getattr(cond, "days", None)
            )
            if not days or not isinstance(days, list):
                return "day_of_week condition requires 'days' list."
            if not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
                return "day_of_week days must be integers 0-6 (Mon=0, Sun=6)."

        elif ctype == "user_agent_pattern":
            pattern = (
                cond.get("pattern")
                if isinstance(cond, dict)
                else getattr(cond, "pattern", None)
            )
            if not pattern:
                return "user_agent_pattern condition requires 'pattern' field."
            try:
                _re.compile(pattern)
            except _re.error:
                return f"Invalid regex pattern: {pattern}"

    return None


@org_api.get(
    "/{org_id}/access-policies",
    response=AccessPolicyListOut,
)
def list_access_policies(request, org_id: str):
    """List conditional access policies for an organization. Admin+ only."""
    _require_org_access(request)
    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )
    policies = ConditionalAccessPolicy.objects.filter(organization=org)
    return {
        "policies": [_serialize_access_policy(p) for p in policies],
        "your_ip": _get_client_ip(request),
    }


@org_api.post(
    "/{org_id}/access-policies",
    response={201: AccessPolicyOut, 400: ErrorOut},
)
def create_access_policy(request, org_id: str, body: CreateAccessPolicyRequest):
    """Create a conditional access policy. Admin+ only."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    if body.action not in ("allow", "block", "require_mfa"):
        return 400, {"detail": "action must be 'allow', 'block', or 'require_mfa'."}

    conditions_data = [c.dict() for c in body.conditions]
    err = _validate_conditions(conditions_data)
    if err:
        return 400, {"detail": err}

    policy = ConditionalAccessPolicy.objects.create(
        organization=org,
        name=body.name.strip(),
        conditions=conditions_data,
        action=body.action,
        is_active=body.is_active,
        priority=body.priority,
    )

    AuditLog.log(
        action="access_policy_created",
        resource_type="access_policy",
        resource_id=str(policy.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "policy_name": policy.name,
            "action": policy.action,
        },
    )

    return 201, _serialize_access_policy(policy)


@org_api.patch(
    "/{org_id}/access-policies/{policy_id}",
    response={200: AccessPolicyOut, 400: ErrorOut, 404: ErrorOut},
)
def update_access_policy(
    request, org_id: str, policy_id: str, body: UpdateAccessPolicyRequest
):
    """Update a conditional access policy. Admin+ only."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        policy = ConditionalAccessPolicy.objects.get(pk=policy_id, organization=org)
    except (ConditionalAccessPolicy.DoesNotExist, ValueError):
        return 404, {"detail": "Access policy not found."}

    if body.name is not None:
        policy.name = body.name.strip()
    if body.action is not None:
        if body.action not in ("allow", "block", "require_mfa"):
            return 400, {"detail": "action must be 'allow', 'block', or 'require_mfa'."}
        policy.action = body.action
    if body.is_active is not None:
        policy.is_active = body.is_active
    if body.priority is not None:
        policy.priority = body.priority
    if body.conditions is not None:
        conditions_data = [c.dict() for c in body.conditions]
        err = _validate_conditions(conditions_data)
        if err:
            return 400, {"detail": err}
        policy.conditions = conditions_data

    policy.save()

    AuditLog.log(
        action="access_policy_updated",
        resource_type="access_policy",
        resource_id=str(policy.pk),
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "policy_name": policy.name,
        },
    )

    return 200, _serialize_access_policy(policy)


@org_api.delete(
    "/{org_id}/access-policies/{policy_id}",
    response={200: ActionOut, 404: ErrorOut},
)
def delete_access_policy(request, org_id: str, policy_id: str):
    """Delete a conditional access policy. Admin+ only."""
    _require_org_access(request)
    from apps.compliance.models import AuditLog

    org = _get_org_or_404(org_id)
    _check_org_admin_permission(
        request, request.auth, org, OrgPermission.MANAGE_SETTINGS
    )

    try:
        policy = ConditionalAccessPolicy.objects.get(pk=policy_id, organization=org)
    except (ConditionalAccessPolicy.DoesNotExist, ValueError):
        return 404, {"detail": "Access policy not found."}

    policy_name = policy.name
    policy_pk = str(policy.pk)
    policy.delete()

    AuditLog.log(
        action="access_policy_deleted",
        resource_type="access_policy",
        resource_id=policy_pk,
        actor_id=request.auth.pk,
        actor_email=request.auth.email,
        actor_ip=_get_client_ip(request),
        request_id=getattr(request, "request_id", ""),
        metadata={
            "organization_id": str(org.pk),
            "policy_name": policy_name,
        },
    )

    return 200, {"success": True, "message": f"Access policy '{policy_name}' deleted."}
