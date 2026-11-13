"""RBAC permission utilities for organization-level authorization.

Usage:
    from apps.workspace.permissions import require_org_role, check_org_permission, OrgPermission

    # In a service or view:
    membership = get_org_membership(user, org)
    check_org_permission(membership, OrgPermission.MANAGE_MEMBERS)

    # Or check minimum role directly:
    require_org_role(user, org, OrganizationRole.ADMIN)
"""

from enum import Enum

from config.errors.common import UnauthorizedAccessError

from .models import (
    ROLE_HIERARCHY,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)


class OrgPermission(str, Enum):
    """Named permissions mapped to minimum required roles."""

    # Viewer-level
    VIEW_ORG = "view_org"
    VIEW_MEMBERS = "view_members"
    VIEW_PROJECTS = "view_projects"
    VIEW_AUDIT_LOG = "view_audit_log"

    # Member-level
    CREATE_PROJECT = "create_project"
    EDIT_OWN_PROJECT = "edit_own_project"
    DELETE_OWN_PROJECT = "delete_own_project"
    CREATE_CONVERSATION = "create_conversation"

    # Admin-level
    MANAGE_WEBHOOKS = "manage_webhooks"
    MANAGE_MEMBERS = "manage_members"
    INVITE_MEMBERS = "invite_members"
    REMOVE_MEMBERS = "remove_members"
    EDIT_ANY_PROJECT = "edit_any_project"
    DELETE_ANY_PROJECT = "delete_any_project"
    MANAGE_SETTINGS = "manage_settings"
    VIEW_ANALYTICS = "view_analytics"

    # Owner-level
    DELETE_ORG = "delete_org"
    TRANSFER_OWNERSHIP = "transfer_ownership"
    MANAGE_BILLING = "manage_billing"


# Map each permission to the minimum role required
PERMISSION_ROLE_MAP: dict[OrgPermission, str] = {
    # Viewer
    OrgPermission.VIEW_ORG: OrganizationRole.VIEWER,
    OrgPermission.VIEW_MEMBERS: OrganizationRole.VIEWER,
    OrgPermission.VIEW_PROJECTS: OrganizationRole.VIEWER,
    OrgPermission.VIEW_AUDIT_LOG: OrganizationRole.VIEWER,
    # Member
    OrgPermission.CREATE_PROJECT: OrganizationRole.MEMBER,
    OrgPermission.EDIT_OWN_PROJECT: OrganizationRole.MEMBER,
    OrgPermission.DELETE_OWN_PROJECT: OrganizationRole.MEMBER,
    OrgPermission.CREATE_CONVERSATION: OrganizationRole.MEMBER,
    # Admin
    OrgPermission.MANAGE_WEBHOOKS: OrganizationRole.ADMIN,
    OrgPermission.MANAGE_MEMBERS: OrganizationRole.ADMIN,
    OrgPermission.INVITE_MEMBERS: OrganizationRole.ADMIN,
    OrgPermission.REMOVE_MEMBERS: OrganizationRole.ADMIN,
    OrgPermission.EDIT_ANY_PROJECT: OrganizationRole.ADMIN,
    OrgPermission.DELETE_ANY_PROJECT: OrganizationRole.ADMIN,
    OrgPermission.MANAGE_SETTINGS: OrganizationRole.ADMIN,
    OrgPermission.VIEW_ANALYTICS: OrganizationRole.ADMIN,
    # Owner
    OrgPermission.DELETE_ORG: OrganizationRole.OWNER,
    OrgPermission.TRANSFER_OWNERSHIP: OrganizationRole.OWNER,
    OrgPermission.MANAGE_BILLING: OrganizationRole.OWNER,
}


def get_org_membership(
    user, organization: Organization
) -> OrganizationMembership | None:
    """Look up a user's membership in an organization.

    Returns None if the user is not a member.
    """
    return (
        organization.memberships.filter(user=user)
        .select_related("organization")
        .first()
    )


def get_user_role(user, organization: Organization) -> str | None:
    """Return the user's role in the organization, or None if not a member."""
    membership = get_org_membership(user, organization)
    return membership.role if membership else None


def role_at_least(role: str, min_role: str) -> bool:
    """Check if a role meets or exceeds a minimum role level."""
    return ROLE_HIERARCHY.get(role, -1) >= ROLE_HIERARCHY.get(min_role, 0)


def require_org_role(
    user,
    organization: Organization,
    min_role: str,
) -> OrganizationMembership:
    """Require that a user has at least the given role in the organization.

    Returns the membership if authorized.

    Raises:
        UnauthorizedAccessError: If the user is not a member or lacks the required role.
    """
    membership = get_org_membership(user, organization)
    if membership is None:
        raise UnauthorizedAccessError("User is not a member of this organization.")
    if not membership.has_role_or_higher(min_role):
        raise UnauthorizedAccessError(
            f"Requires {min_role} role or higher. Current role: {membership.role}."
        )
    return membership


def check_org_permission(
    user,
    organization: Organization,
    permission: OrgPermission,
) -> OrganizationMembership:
    """Check that a user has a specific named permission in the organization.

    Returns the membership if authorized.

    Raises:
        UnauthorizedAccessError: If the user lacks the required permission.
    """
    min_role = PERMISSION_ROLE_MAP.get(permission)
    if min_role is None:
        raise ValueError(f"Unknown permission: {permission}")
    return require_org_role(user, organization, min_role)


def can_manage_member(
    actor_membership: OrganizationMembership,
    target_membership: OrganizationMembership,
) -> bool:
    """Check if the actor can manage (change role, remove) the target member.

    Rules:
    - Owners can manage anyone except other owners (use transfer_ownership for that).
    - Admins can manage members and viewers, but not other admins or owners.
    - Members and viewers cannot manage anyone.
    """
    if actor_membership.role_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        return False
    # Cannot manage someone at or above your level (except owner managing non-owners)
    if actor_membership.role == OrganizationRole.OWNER:
        return target_membership.role != OrganizationRole.OWNER
    return actor_membership.role_level > target_membership.role_level
