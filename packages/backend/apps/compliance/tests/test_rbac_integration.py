"""RBAC integration tests — cross-endpoint permission matrix.

Verifies that every org-scoped and compliance API endpoint enforces the
correct minimum role.  Each test covers a specific (endpoint, role) pair.

Role hierarchy: VIEWER (0) < MEMBER (1) < ADMIN (2) < OWNER (3)
"""

import json

import pytest
from django.test import RequestFactory

from apps.compliance.models import RetentionPolicy
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)
from config.errors.common import UnauthorizedAccessError

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    return RequestFactory()


def _authed_request(rf, method, path, user, body=None, **kwargs):
    """Build a request with the auth user attached (simulates NinjaAuthAdapter)."""
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path,
            data=json.dumps(body),
            content_type="application/json",
            **kwargs,
        )
    else:
        request = factory_method(path, **kwargs)
    request.auth = user
    request.request_id = "rbac-test"
    return request


@pytest.fixture
def org():
    return Organization.objects.create(name="RBAC Test Org")


def _make_member(org, role):
    """Create a user and add them to org with the given role."""
    user = UserFactory()
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


@pytest.fixture
def viewer(org):
    return _make_member(org, OrganizationRole.VIEWER)


@pytest.fixture
def member(org):
    return _make_member(org, OrganizationRole.MEMBER)


@pytest.fixture
def admin(org):
    return _make_member(org, OrganizationRole.ADMIN)


@pytest.fixture
def owner(org):
    return _make_member(org, OrganizationRole.OWNER)


@pytest.fixture
def non_member():
    return UserFactory()


# ============================================================================
# GET /organizations/{id} — requires VIEWER+
# ============================================================================


class TestGetOrganization:
    def test_viewer_can_access(self, rf, org, viewer):
        from apps.workspace.org_api import get_organization

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}", viewer
        )
        result = get_organization(request, org_id=str(org.pk))
        assert result["name"] == org.name

    def test_member_can_access(self, rf, org, member):
        from apps.workspace.org_api import get_organization

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}", member
        )
        result = get_organization(request, org_id=str(org.pk))
        assert result["name"] == org.name

    def test_admin_can_access(self, rf, org, admin):
        from apps.workspace.org_api import get_organization

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}", admin
        )
        result = get_organization(request, org_id=str(org.pk))
        assert result["name"] == org.name

    def test_owner_can_access(self, rf, org, owner):
        from apps.workspace.org_api import get_organization

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}", owner
        )
        result = get_organization(request, org_id=str(org.pk))
        assert result["name"] == org.name

    def test_non_member_rejected(self, rf, org, non_member):
        from apps.workspace.org_api import get_organization

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}", non_member
        )
        with pytest.raises(UnauthorizedAccessError):
            get_organization(request, org_id=str(org.pk))


# ============================================================================
# PATCH /organizations/{id} — requires ADMIN+ (MANAGE_SETTINGS)
# ============================================================================


class TestUpdateOrganization:
    def test_viewer_rejected(self, rf, org, viewer):
        from apps.workspace.org_api import update_organization
        from apps.workspace.org_schemas import UpdateOrganizationRequest

        body = UpdateOrganizationRequest(name="New Name")
        request = _authed_request(
            rf, "patch", f"/api/v1/workspace/organizations/{org.pk}", viewer
        )
        with pytest.raises(UnauthorizedAccessError):
            update_organization(request, org_id=str(org.pk), body=body)

    def test_member_rejected(self, rf, org, member):
        from apps.workspace.org_api import update_organization
        from apps.workspace.org_schemas import UpdateOrganizationRequest

        body = UpdateOrganizationRequest(name="New Name")
        request = _authed_request(
            rf, "patch", f"/api/v1/workspace/organizations/{org.pk}", member
        )
        with pytest.raises(UnauthorizedAccessError):
            update_organization(request, org_id=str(org.pk), body=body)

    def test_admin_can_update(self, rf, org, admin):
        from apps.workspace.org_api import update_organization
        from apps.workspace.org_schemas import UpdateOrganizationRequest

        body = UpdateOrganizationRequest(name="Updated Name")
        request = _authed_request(
            rf, "patch", f"/api/v1/workspace/organizations/{org.pk}", admin
        )
        result = update_organization(request, org_id=str(org.pk), body=body)
        assert result["name"] == "Updated Name"

    def test_owner_can_update(self, rf, org, owner):
        from apps.workspace.org_api import update_organization
        from apps.workspace.org_schemas import UpdateOrganizationRequest

        body = UpdateOrganizationRequest(description="Owner updated")
        request = _authed_request(
            rf, "patch", f"/api/v1/workspace/organizations/{org.pk}", owner
        )
        result = update_organization(request, org_id=str(org.pk), body=body)
        assert result["description"] == "Owner updated"


# ============================================================================
# DELETE /organizations/{id} — requires OWNER
# ============================================================================


class TestDeleteOrganization:
    def test_viewer_rejected(self, rf, org, viewer):
        from apps.workspace.org_api import delete_organization
        from apps.workspace.org_schemas import DeleteOrganizationRequest

        request = _authed_request(
            rf, "delete", f"/api/v1/workspace/organizations/{org.pk}", viewer
        )
        body = DeleteOrganizationRequest(confirm_name=org.name, cascade_mode="destroy")
        with pytest.raises(UnauthorizedAccessError):
            delete_organization(request, org_id=str(org.pk), body=body)

    def test_member_rejected(self, rf, org, member):
        from apps.workspace.org_api import delete_organization
        from apps.workspace.org_schemas import DeleteOrganizationRequest

        request = _authed_request(
            rf, "delete", f"/api/v1/workspace/organizations/{org.pk}", member
        )
        body = DeleteOrganizationRequest(confirm_name=org.name, cascade_mode="destroy")
        with pytest.raises(UnauthorizedAccessError):
            delete_organization(request, org_id=str(org.pk), body=body)

    def test_admin_rejected(self, rf, org, admin):
        from apps.workspace.org_api import delete_organization
        from apps.workspace.org_schemas import DeleteOrganizationRequest

        request = _authed_request(
            rf, "delete", f"/api/v1/workspace/organizations/{org.pk}", admin
        )
        body = DeleteOrganizationRequest(confirm_name=org.name, cascade_mode="destroy")
        with pytest.raises(UnauthorizedAccessError):
            delete_organization(request, org_id=str(org.pk), body=body)

    def test_owner_can_delete(self, rf, owner):
        from apps.workspace.org_api import delete_organization
        from apps.workspace.org_schemas import DeleteOrganizationRequest

        org = Organization.objects.create(name="Delete Me Org")
        OrganizationMembership.objects.create(
            organization=org, user=owner, role=OrganizationRole.OWNER
        )
        request = _authed_request(
            rf, "delete", f"/api/v1/workspace/organizations/{org.pk}", owner
        )
        body = DeleteOrganizationRequest(
            confirm_name="Delete Me Org", cascade_mode="destroy"
        )
        result = delete_organization(request, org_id=str(org.pk), body=body)
        status, payload = result
        assert status == 200
        assert payload["success"] is True
        assert not Organization.objects.filter(pk=org.pk).exists()


# ============================================================================
# GET /organizations/{id}/members — requires VIEWER+
# ============================================================================


class TestListMembers:
    def test_viewer_can_list(self, rf, org, viewer):
        from apps.workspace.org_api import list_members

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}/members", viewer
        )
        result = list_members(request, org_id=str(org.pk))
        assert isinstance(result, list)

    def test_non_member_rejected(self, rf, org, non_member):
        from apps.workspace.org_api import list_members

        request = _authed_request(
            rf, "get", f"/api/v1/workspace/organizations/{org.pk}/members", non_member
        )
        with pytest.raises(UnauthorizedAccessError):
            list_members(request, org_id=str(org.pk))


# ============================================================================
# POST /organizations/{id}/members — requires ADMIN+ (INVITE_MEMBERS)
# ============================================================================


class TestInviteMember:
    def test_viewer_rejected(self, rf, org, viewer):
        from apps.workspace.org_api import invite_member
        from apps.workspace.org_schemas import InviteMemberRequest

        target = UserFactory()
        body = InviteMemberRequest(email=target.email, role=OrganizationRole.VIEWER)
        request = _authed_request(
            rf, "post", f"/api/v1/workspace/organizations/{org.pk}/members", viewer
        )
        with pytest.raises(UnauthorizedAccessError):
            invite_member(request, org_id=str(org.pk), body=body)

    def test_member_rejected(self, rf, org, member):
        from apps.workspace.org_api import invite_member
        from apps.workspace.org_schemas import InviteMemberRequest

        target = UserFactory()
        body = InviteMemberRequest(email=target.email, role=OrganizationRole.VIEWER)
        request = _authed_request(
            rf, "post", f"/api/v1/workspace/organizations/{org.pk}/members", member
        )
        with pytest.raises(UnauthorizedAccessError):
            invite_member(request, org_id=str(org.pk), body=body)

    def test_admin_can_invite_viewer(self, rf, org, admin):
        from apps.workspace.org_api import invite_member
        from apps.workspace.org_schemas import InviteMemberRequest

        target = UserFactory()
        body = InviteMemberRequest(email=target.email, role=OrganizationRole.VIEWER)
        request = _authed_request(
            rf, "post", f"/api/v1/workspace/organizations/{org.pk}/members", admin
        )
        status, result = invite_member(request, org_id=str(org.pk), body=body)
        assert status == 201
        assert result["role"] == OrganizationRole.VIEWER

    def test_admin_cannot_invite_admin(self, rf, org, admin):
        from apps.workspace.org_api import invite_member
        from apps.workspace.org_schemas import InviteMemberRequest

        target = UserFactory()
        body = InviteMemberRequest(email=target.email, role=OrganizationRole.ADMIN)
        request = _authed_request(
            rf, "post", f"/api/v1/workspace/organizations/{org.pk}/members", admin
        )
        status, result = invite_member(request, org_id=str(org.pk), body=body)
        assert status == 400
        assert "role equal to or higher" in result["detail"]

    def test_owner_can_invite_admin(self, rf, org, owner):
        from apps.workspace.org_api import invite_member
        from apps.workspace.org_schemas import InviteMemberRequest

        target = UserFactory()
        body = InviteMemberRequest(email=target.email, role=OrganizationRole.ADMIN)
        request = _authed_request(
            rf, "post", f"/api/v1/workspace/organizations/{org.pk}/members", owner
        )
        status, result = invite_member(request, org_id=str(org.pk), body=body)
        assert status == 201
        assert result["role"] == OrganizationRole.ADMIN


# ============================================================================
# PATCH /organizations/{id}/members/{mid} — requires ADMIN+ with outranking
# ============================================================================


class TestChangeMemberRole:
    def test_viewer_rejected(self, rf, org, viewer, member):
        from apps.workspace.org_api import change_member_role
        from apps.workspace.org_schemas import ChangeMemberRoleRequest

        target_membership = OrganizationMembership.objects.get(
            user=member, organization=org
        )
        body = ChangeMemberRoleRequest(role=OrganizationRole.VIEWER)
        request = _authed_request(rf, "patch", "/", viewer)
        with pytest.raises(UnauthorizedAccessError):
            change_member_role(
                request,
                org_id=str(org.pk),
                membership_id=str(target_membership.pk),
                body=body,
            )

    def test_admin_can_change_member_role(self, rf, org, admin, member):
        from apps.workspace.org_api import change_member_role
        from apps.workspace.org_schemas import ChangeMemberRoleRequest

        target_membership = OrganizationMembership.objects.get(
            user=member, organization=org
        )
        body = ChangeMemberRoleRequest(role=OrganizationRole.VIEWER)
        request = _authed_request(rf, "patch", "/", admin)
        status, result = change_member_role(
            request,
            org_id=str(org.pk),
            membership_id=str(target_membership.pk),
            body=body,
        )
        assert status == 200
        assert result["role"] == OrganizationRole.VIEWER

    def test_admin_cannot_change_admin_role(self, rf, org, admin):
        from apps.workspace.org_api import change_member_role
        from apps.workspace.org_schemas import ChangeMemberRoleRequest

        other_admin = _make_member(org, OrganizationRole.ADMIN)
        target_membership = OrganizationMembership.objects.get(
            user=other_admin, organization=org
        )
        body = ChangeMemberRoleRequest(role=OrganizationRole.VIEWER)
        request = _authed_request(rf, "patch", "/", admin)
        with pytest.raises(UnauthorizedAccessError, match="cannot change"):
            change_member_role(
                request,
                org_id=str(org.pk),
                membership_id=str(target_membership.pk),
                body=body,
            )


# ============================================================================
# DELETE /organizations/{id}/members/{mid} — requires ADMIN+ with outranking
# ============================================================================


class TestRemoveMember:
    def test_viewer_rejected(self, rf, org, viewer, member):
        from apps.workspace.org_api import remove_member

        target_membership = OrganizationMembership.objects.get(
            user=member, organization=org
        )
        request = _authed_request(rf, "delete", "/", viewer)
        with pytest.raises(UnauthorizedAccessError):
            remove_member(
                request, org_id=str(org.pk), membership_id=str(target_membership.pk)
            )

    def test_admin_can_remove_member(self, rf, org, admin, member):
        from apps.workspace.org_api import remove_member

        target_membership = OrganizationMembership.objects.get(
            user=member, organization=org
        )
        request = _authed_request(rf, "delete", "/", admin)
        result = remove_member(
            request, org_id=str(org.pk), membership_id=str(target_membership.pk)
        )
        # remove_member returns (status, body) for error paths, or just ActionOut on success
        if isinstance(result, tuple):
            status, body = result
            assert status == 200
        else:
            assert result["success"] is True

    def test_admin_cannot_remove_admin(self, rf, org, admin):
        from apps.workspace.org_api import remove_member

        other_admin = _make_member(org, OrganizationRole.ADMIN)
        target_membership = OrganizationMembership.objects.get(
            user=other_admin, organization=org
        )
        request = _authed_request(rf, "delete", "/", admin)
        with pytest.raises(UnauthorizedAccessError, match="cannot remove"):
            remove_member(
                request, org_id=str(org.pk), membership_id=str(target_membership.pk)
            )


# ============================================================================
# GET /organizations/{id}/security-policy — requires VIEWER+
# ============================================================================


class TestGetSecurityPolicy:
    def test_viewer_can_read(self, rf, org, viewer):
        from apps.workspace.org_api import get_security_policy

        request = _authed_request(rf, "get", "/", viewer)
        result = get_security_policy(request, org_id=str(org.pk))
        assert "mfa_required" in result

    def test_non_member_rejected(self, rf, org, non_member):
        from apps.workspace.org_api import get_security_policy

        request = _authed_request(rf, "get", "/", non_member)
        with pytest.raises(UnauthorizedAccessError):
            get_security_policy(request, org_id=str(org.pk))


# ============================================================================
# PATCH /organizations/{id}/security-policy — requires ADMIN+ (MANAGE_SETTINGS)
# ============================================================================


class TestUpdateSecurityPolicy:
    def test_viewer_rejected(self, rf, org, viewer):
        from apps.workspace.org_api import update_security_policy
        from apps.workspace.org_schemas import UpdateSecurityPolicyRequest

        body = UpdateSecurityPolicyRequest(mfa_required=True)
        request = _authed_request(rf, "patch", "/", viewer)
        with pytest.raises(UnauthorizedAccessError):
            update_security_policy(request, org_id=str(org.pk), body=body)

    def test_member_rejected(self, rf, org, member):
        from apps.workspace.org_api import update_security_policy
        from apps.workspace.org_schemas import UpdateSecurityPolicyRequest

        body = UpdateSecurityPolicyRequest(mfa_required=True)
        request = _authed_request(rf, "patch", "/", member)
        with pytest.raises(UnauthorizedAccessError):
            update_security_policy(request, org_id=str(org.pk), body=body)

    def test_admin_can_update(self, rf, org, admin):
        from apps.workspace.org_api import update_security_policy
        from apps.workspace.org_schemas import UpdateSecurityPolicyRequest

        body = UpdateSecurityPolicyRequest(mfa_required=True)
        request = _authed_request(rf, "patch", "/", admin)
        status, result = update_security_policy(request, org_id=str(org.pk), body=body)
        assert status == 200
        assert result["mfa_required"] is True

    def test_owner_can_update(self, rf, org, owner):
        from apps.workspace.org_api import update_security_policy
        from apps.workspace.org_schemas import UpdateSecurityPolicyRequest

        body = UpdateSecurityPolicyRequest(max_concurrent_sessions=10)
        request = _authed_request(rf, "patch", "/", owner)
        status, result = update_security_policy(request, org_id=str(org.pk), body=body)
        assert status == 200
        assert result["max_concurrent_sessions"] == 10

    def test_invalid_timeout_rejected(self, rf, org, admin):
        from apps.workspace.org_api import update_security_policy
        from apps.workspace.org_schemas import UpdateSecurityPolicyRequest

        body = UpdateSecurityPolicyRequest(session_timeout_minutes=1)  # below min 5
        request = _authed_request(rf, "patch", "/", admin)
        status, result = update_security_policy(request, org_id=str(org.pk), body=body)
        assert status == 400


# ============================================================================
# Compliance: retention policies — SUPERUSER only
# ============================================================================


class TestRetentionPolicyRBAC:
    def test_superuser_can_list(self, rf):
        superuser = UserFactory(is_superuser=True)
        RetentionPolicy.objects.create(
            resource_type="rbac_test", retention_days=30, action="delete"
        )
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", superuser
        )

        from apps.compliance.api import list_retention_policies

        status, data = list_retention_policies(request)
        assert status == 200

    def test_regular_user_rejected(self, rf):
        user = UserFactory()
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", user
        )

        from apps.compliance.api import list_retention_policies

        status, _ = list_retention_policies(request)
        assert status == 403

    def test_org_admin_not_superuser_rejected(self, rf, org, admin):
        request = _authed_request(
            rf, "get", "/api/v1/compliance/retention-policies", admin
        )

        from apps.compliance.api import list_retention_policies

        status, _ = list_retention_policies(request)
        assert status == 403

    def test_superuser_can_update(self, rf):
        superuser = UserFactory(is_superuser=True)
        policy = RetentionPolicy.objects.create(
            resource_type="rbac_upd", retention_days=30, action="delete"
        )
        request = _authed_request(rf, "patch", "/", superuser)

        from apps.compliance.api import RetentionPolicyUpdate, update_retention_policy

        body = RetentionPolicyUpdate(retention_days=90)
        status, data = update_retention_policy(request, policy.pk, body)
        assert status == 200
        assert data["retention_days"] == 90


# ============================================================================
# Compliance: consent endpoints — any authenticated user
# ============================================================================


class TestConsentRBAC:
    def test_any_user_can_read_consent(self, rf):
        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/consent", user)

        from apps.compliance.api import consent_current

        result = consent_current(request)
        assert isinstance(result, dict)

    def test_any_user_can_read_history(self, rf):
        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/consent/history", user)

        from apps.compliance.api import consent_history

        result = consent_history(request)
        assert isinstance(result, list)


# ============================================================================
# Compliance: security-policy endpoint — any authenticated user
# ============================================================================


class TestSecurityPolicyEndpointRBAC:
    def test_any_user_can_read_effective_policy(self, rf):
        from unittest.mock import patch

        user = UserFactory()
        request = _authed_request(rf, "get", "/api/v1/compliance/security-policy", user)

        from apps.compliance.api import effective_security_policy

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            result = effective_security_policy(request)
        assert "mfa_required" in result
        assert "session_timeout_minutes" in result


# ============================================================================
# Permission utility functions
# ============================================================================


class TestPermissionUtilities:
    def test_role_at_least_hierarchy(self):
        from apps.workspace.permissions import role_at_least

        assert role_at_least(OrganizationRole.OWNER, OrganizationRole.VIEWER)
        assert role_at_least(OrganizationRole.ADMIN, OrganizationRole.MEMBER)
        assert role_at_least(OrganizationRole.MEMBER, OrganizationRole.MEMBER)
        assert not role_at_least(OrganizationRole.VIEWER, OrganizationRole.MEMBER)
        assert not role_at_least(OrganizationRole.MEMBER, OrganizationRole.ADMIN)

    def test_can_manage_member_rules(self, org, owner, admin, member, viewer):
        from apps.workspace.permissions import can_manage_member

        owner_m = OrganizationMembership.objects.get(user=owner, organization=org)
        admin_m = OrganizationMembership.objects.get(user=admin, organization=org)
        member_m = OrganizationMembership.objects.get(user=member, organization=org)
        viewer_m = OrganizationMembership.objects.get(user=viewer, organization=org)

        # Owner can manage admin, member, viewer
        assert can_manage_member(owner_m, admin_m) is True
        assert can_manage_member(owner_m, member_m) is True
        assert can_manage_member(owner_m, viewer_m) is True

        # Admin can manage member, viewer but not admin
        assert can_manage_member(admin_m, member_m) is True
        assert can_manage_member(admin_m, viewer_m) is True
        assert can_manage_member(admin_m, admin_m) is False

        # Member cannot manage anyone
        assert can_manage_member(member_m, viewer_m) is False

        # Viewer cannot manage anyone
        assert can_manage_member(viewer_m, member_m) is False

    def test_check_org_permission_all_levels(self, org, viewer, member, admin, owner):
        from apps.workspace.permissions import OrgPermission, check_org_permission

        # Viewer-level permission
        check_org_permission(viewer, org, OrgPermission.VIEW_ORG)
        check_org_permission(member, org, OrgPermission.VIEW_ORG)
        check_org_permission(admin, org, OrgPermission.VIEW_ORG)
        check_org_permission(owner, org, OrgPermission.VIEW_ORG)

        # Member-level permission
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(viewer, org, OrgPermission.CREATE_PROJECT)
        check_org_permission(member, org, OrgPermission.CREATE_PROJECT)
        check_org_permission(admin, org, OrgPermission.CREATE_PROJECT)

        # Admin-level permission
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(viewer, org, OrgPermission.MANAGE_SETTINGS)
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(member, org, OrgPermission.MANAGE_SETTINGS)
        check_org_permission(admin, org, OrgPermission.MANAGE_SETTINGS)
        check_org_permission(owner, org, OrgPermission.MANAGE_SETTINGS)

        # Owner-level permission
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(admin, org, OrgPermission.DELETE_ORG)
        check_org_permission(owner, org, OrgPermission.DELETE_ORG)
