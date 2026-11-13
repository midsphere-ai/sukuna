"""Tests for RBAC permission utilities."""

import pytest

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)
from apps.workspace.permissions import (
    PERMISSION_ROLE_MAP,
    OrgPermission,
    can_manage_member,
    check_org_permission,
    get_org_membership,
    get_user_role,
    require_org_role,
    role_at_least,
)
from config.errors.common import UnauthorizedAccessError


@pytest.fixture
def org():
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def owner(org):
    user = UserFactory()
    membership = OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.OWNER
    )
    return user, membership


@pytest.fixture
def admin_user(org):
    user = UserFactory()
    membership = OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.ADMIN
    )
    return user, membership


@pytest.fixture
def member_user(org):
    user = UserFactory()
    membership = OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.MEMBER
    )
    return user, membership


@pytest.fixture
def viewer_user(org):
    user = UserFactory()
    membership = OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.VIEWER
    )
    return user, membership


@pytest.mark.django_db
class TestGetOrgMembership:
    def test_returns_membership(self, org, member_user):
        user, expected = member_user
        result = get_org_membership(user, org)
        assert result == expected

    def test_returns_none_for_non_member(self, org):
        outsider = UserFactory()
        assert get_org_membership(outsider, org) is None


@pytest.mark.django_db
class TestGetUserRole:
    def test_returns_role(self, org, admin_user):
        user, _ = admin_user
        assert get_user_role(user, org) == OrganizationRole.ADMIN

    def test_returns_none_for_non_member(self, org):
        outsider = UserFactory()
        assert get_user_role(outsider, org) is None


@pytest.mark.django_db
class TestRoleAtLeast:
    def test_owner_at_least_viewer(self):
        assert role_at_least(OrganizationRole.OWNER, OrganizationRole.VIEWER) is True

    def test_viewer_at_least_owner(self):
        assert role_at_least(OrganizationRole.VIEWER, OrganizationRole.OWNER) is False

    def test_same_role(self):
        assert role_at_least(OrganizationRole.ADMIN, OrganizationRole.ADMIN) is True

    def test_unknown_role(self):
        assert role_at_least("unknown", OrganizationRole.VIEWER) is False


@pytest.mark.django_db
class TestRequireOrgRole:
    def test_owner_passes_all_requirements(self, org, owner):
        user, _ = owner
        for role in OrganizationRole:
            result = require_org_role(user, org, role)
            assert result is not None

    def test_viewer_passes_viewer_requirement(self, org, viewer_user):
        user, _ = viewer_user
        result = require_org_role(user, org, OrganizationRole.VIEWER)
        assert result.role == OrganizationRole.VIEWER

    def test_viewer_fails_member_requirement(self, org, viewer_user):
        user, _ = viewer_user
        with pytest.raises(UnauthorizedAccessError, match="Requires member role"):
            require_org_role(user, org, OrganizationRole.MEMBER)

    def test_member_fails_admin_requirement(self, org, member_user):
        user, _ = member_user
        with pytest.raises(UnauthorizedAccessError, match="Requires admin role"):
            require_org_role(user, org, OrganizationRole.ADMIN)

    def test_admin_fails_owner_requirement(self, org, admin_user):
        user, _ = admin_user
        with pytest.raises(UnauthorizedAccessError, match="Requires owner role"):
            require_org_role(user, org, OrganizationRole.OWNER)

    def test_non_member_raises(self, org):
        outsider = UserFactory()
        with pytest.raises(UnauthorizedAccessError, match="not a member"):
            require_org_role(outsider, org, OrganizationRole.VIEWER)

    def test_returns_membership(self, org, admin_user):
        user, expected = admin_user
        result = require_org_role(user, org, OrganizationRole.MEMBER)
        assert result == expected


@pytest.mark.django_db
class TestCheckOrgPermission:
    def test_viewer_can_view(self, org, viewer_user):
        user, _ = viewer_user
        result = check_org_permission(user, org, OrgPermission.VIEW_ORG)
        assert result is not None

    def test_viewer_cannot_create_project(self, org, viewer_user):
        user, _ = viewer_user
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(user, org, OrgPermission.CREATE_PROJECT)

    def test_member_can_create_project(self, org, member_user):
        user, _ = member_user
        result = check_org_permission(user, org, OrgPermission.CREATE_PROJECT)
        assert result is not None

    def test_member_cannot_manage_members(self, org, member_user):
        user, _ = member_user
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(user, org, OrgPermission.MANAGE_MEMBERS)

    def test_admin_can_manage_members(self, org, admin_user):
        user, _ = admin_user
        result = check_org_permission(user, org, OrgPermission.MANAGE_MEMBERS)
        assert result is not None

    def test_admin_cannot_delete_org(self, org, admin_user):
        user, _ = admin_user
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(user, org, OrgPermission.DELETE_ORG)

    def test_owner_can_delete_org(self, org, owner):
        user, _ = owner
        result = check_org_permission(user, org, OrgPermission.DELETE_ORG)
        assert result is not None

    def test_owner_can_manage_billing(self, org, owner):
        user, _ = owner
        result = check_org_permission(user, org, OrgPermission.MANAGE_BILLING)
        assert result is not None

    def test_non_member_denied(self, org):
        outsider = UserFactory()
        with pytest.raises(UnauthorizedAccessError):
            check_org_permission(outsider, org, OrgPermission.VIEW_ORG)

    def test_all_permissions_mapped(self):
        for perm in OrgPermission:
            assert perm in PERMISSION_ROLE_MAP, f"{perm} not in PERMISSION_ROLE_MAP"


@pytest.mark.django_db
class TestCanManageMember:
    def test_owner_can_manage_admin(self, org, owner, admin_user):
        _, owner_m = owner
        _, admin_m = admin_user
        assert can_manage_member(owner_m, admin_m) is True

    def test_owner_can_manage_member(self, org, owner, member_user):
        _, owner_m = owner
        _, member_m = member_user
        assert can_manage_member(owner_m, member_m) is True

    def test_owner_can_manage_viewer(self, org, owner, viewer_user):
        _, owner_m = owner
        _, viewer_m = viewer_user
        assert can_manage_member(owner_m, viewer_m) is True

    def test_owner_cannot_manage_other_owner(self, org):
        owner1 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        owner2 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.OWNER
        )
        assert can_manage_member(owner1, owner2) is False

    def test_admin_can_manage_member(self, org, admin_user, member_user):
        _, admin_m = admin_user
        _, member_m = member_user
        assert can_manage_member(admin_m, member_m) is True

    def test_admin_can_manage_viewer(self, org, admin_user, viewer_user):
        _, admin_m = admin_user
        _, viewer_m = viewer_user
        assert can_manage_member(admin_m, viewer_m) is True

    def test_admin_cannot_manage_other_admin(self, org):
        admin1 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.ADMIN
        )
        admin2 = OrganizationMembership.objects.create(
            organization=org, user=UserFactory(), role=OrganizationRole.ADMIN
        )
        assert can_manage_member(admin1, admin2) is False

    def test_admin_cannot_manage_owner(self, org, admin_user, owner):
        _, admin_m = admin_user
        _, owner_m = owner
        assert can_manage_member(admin_m, owner_m) is False

    def test_member_cannot_manage_anyone(self, org, member_user, viewer_user):
        _, member_m = member_user
        _, viewer_m = viewer_user
        assert can_manage_member(member_m, viewer_m) is False

    def test_viewer_cannot_manage_anyone(self, org, viewer_user, member_user):
        _, viewer_m = viewer_user
        _, member_m = member_user
        assert can_manage_member(viewer_m, member_m) is False
