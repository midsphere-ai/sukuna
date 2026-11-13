"""Tests for Organization CRUD and membership management API endpoints with RBAC enforcement.

Covers:
- Organization CRUD (create, list, get, update, delete)
- Member management (list, invite, change role, remove, leave)
- RBAC enforcement at every endpoint (viewer/member/admin/owner)
- Edge cases: last owner protection, self-management, non-member access
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _delete(client, path, data=None):
    kwargs = {"content_type": "application/json"}
    if data is not None:
        kwargs["data"] = json.dumps(data)
    return client.delete(path, **kwargs)


def _create_org(name="Test Org", description=""):
    """Create an org + owner membership, return (org, owner, owner_token)."""
    owner, token = _make_user()
    resp = _post(
        _client(token), f"{_BASE}/", {"name": name, "description": description}
    )
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None):
    """Create a user and add them to org with the given role. Returns (user, token)."""
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


# =============================================================================
# AUTHENTICATION
# =============================================================================


class TestOrgAuthentication:
    """All org endpoints require authentication."""

    ENDPOINTS = [
        ("get", f"{_BASE}/"),
        ("post", f"{_BASE}/"),
        ("get", f"{_BASE}/00000000-0000-0000-0000-000000000000"),
        ("patch", f"{_BASE}/00000000-0000-0000-0000-000000000000"),
        ("delete", f"{_BASE}/00000000-0000-0000-0000-000000000000"),
        ("get", f"{_BASE}/00000000-0000-0000-0000-000000000000/members"),
        ("post", f"{_BASE}/00000000-0000-0000-0000-000000000000/members"),
    ]

    def test_no_token_returns_401(self):
        for method, path in self.ENDPOINTS:
            cache.clear()
            fn = getattr(Client(), method)
            resp = fn(path, content_type="application/json")
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )


# =============================================================================
# ORGANIZATION CRUD
# =============================================================================


class TestCreateOrganization:
    """POST /organizations/"""

    def test_create_org_success(self):
        _, token = _make_user()
        resp = _post(
            _client(token), f"{_BASE}/", {"name": "Acme", "description": "Testing"}
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Acme"
        assert data["slug"] == "acme"
        assert data["description"] == "Testing"
        assert data["member_count"] == 1
        assert data["your_role"] == "owner"

    def test_create_org_creator_is_owner(self):
        org, owner, _ = _create_org("OwnerTest")
        m = OrganizationMembership.objects.get(organization=org, user=owner)
        assert m.role == OrganizationRole.OWNER

    def test_create_org_empty_name_rejected(self):
        _, token = _make_user()
        resp = _post(_client(token), f"{_BASE}/", {"name": "  "})
        assert resp.status_code == 400

    def test_create_org_strips_whitespace(self):
        _, token = _make_user()
        resp = _post(_client(token), f"{_BASE}/", {"name": "  Padded Name  "})
        assert resp.status_code == 201
        assert resp.json()["name"] == "Padded Name"


class TestListOrganizations:
    """GET /organizations/"""

    def test_list_returns_user_orgs(self):
        org, _, owner_token = _create_org("Org A")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _client(member_token).get(f"{_BASE}/")
        assert resp.status_code == 200
        names = [o["name"] for o in resp.json()]
        assert "Org A" in names

    def test_list_excludes_non_member_orgs(self):
        _create_org("Secret Org")
        outsider, outsider_token = _make_user()

        resp = _client(outsider_token).get(f"{_BASE}/")
        assert resp.status_code == 200
        assert len(resp.json()) == 0


class TestGetOrganization:
    """GET /organizations/{org_id}"""

    def test_viewer_can_get_org(self):
        org, _, _ = _create_org("ViewTest")
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        resp = _client(viewer_token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "ViewTest"
        assert resp.json()["your_role"] == "viewer"

    def test_non_member_gets_401(self):
        org, _, _ = _create_org("Private")
        _, outsider_token = _make_user()

        resp = _client(outsider_token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 401

    def test_nonexistent_org_returns_404(self):
        _, token = _make_user()
        resp = _client(token).get(f"{_BASE}/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestUpdateOrganization:
    """PATCH /organizations/{org_id}"""

    def test_admin_can_update_org(self):
        org, _, _ = _create_org("OldName")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)

        resp = _patch(_client(admin_token), f"{_BASE}/{org.pk}", {"name": "NewName"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "NewName"

    def test_owner_can_update_org(self):
        org, _, owner_token = _create_org("OwnerUpdate")
        resp = _patch(
            _client(owner_token), f"{_BASE}/{org.pk}", {"description": "Updated"}
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "Updated"

    def test_member_cannot_update_org(self):
        org, _, _ = _create_org("NoMemberEdit")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _patch(_client(member_token), f"{_BASE}/{org.pk}", {"name": "Hacked"})
        assert resp.status_code == 401

    def test_viewer_cannot_update_org(self):
        org, _, _ = _create_org("NoViewerEdit")
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        resp = _patch(_client(viewer_token), f"{_BASE}/{org.pk}", {"name": "Hacked"})
        assert resp.status_code == 401

    def test_update_empty_name_rejected(self):
        org, _, owner_token = _create_org("ValidName")
        resp = _patch(_client(owner_token), f"{_BASE}/{org.pk}", {"name": ""})
        assert resp.status_code == 400


class TestDeleteOrganization:
    """DELETE /organizations/{org_id}"""

    def test_owner_can_delete_org(self):
        org, _, owner_token = _create_org("ToDelete")
        resp = _delete(
            _client(owner_token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "ToDelete", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 200
        assert not Organization.objects.filter(pk=org.pk).exists()

    def test_admin_cannot_delete_org(self):
        org, _, _ = _create_org("AdminCantDelete")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)

        resp = _delete(
            _client(admin_token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "AdminCantDelete", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 401
        assert Organization.objects.filter(pk=org.pk).exists()

    def test_member_cannot_delete_org(self):
        org, _, _ = _create_org("MemberCantDelete")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _delete(
            _client(member_token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "MemberCantDelete", "cascade_mode": "destroy"},
        )


# =============================================================================
# MEMBER MANAGEMENT
# =============================================================================


class TestListMembers:
    """GET /organizations/{org_id}/members"""

    def test_viewer_can_list_members(self):
        org, owner, _ = _create_org("MemberList")
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        resp = _client(viewer_token).get(f"{_BASE}/{org.pk}/members")
        assert resp.status_code == 200
        emails = [m["email"] for m in resp.json()]
        assert owner.email in emails

    def test_non_member_cannot_list_members(self):
        org, _, _ = _create_org("NoAccess")
        _, outsider_token = _make_user()

        resp = _client(outsider_token).get(f"{_BASE}/{org.pk}/members")
        assert resp.status_code == 401


class TestInviteMember:
    """POST /organizations/{org_id}/members"""

    def test_admin_can_invite_member(self):
        org, _, _ = _create_org("InviteTest")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        target, _ = _make_user()

        resp = _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "member"
        assert org.has_member(target)

    def test_owner_can_invite_admin(self):
        org, _, owner_token = _create_org("OwnerInvite")
        target, _ = _make_user()

        resp = _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "admin"},
        )
        assert resp.status_code == 201
        assert resp.json()["role"] == "admin"

    def test_admin_cannot_invite_admin(self):
        org, _, _ = _create_org("AdminCantInviteAdmin")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        target, _ = _make_user()

        resp = _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "admin"},
        )
        assert resp.status_code == 400

    def test_member_cannot_invite(self):
        org, _, _ = _create_org("MemberCantInvite")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        target, _ = _make_user()

        resp = _post(
            _client(member_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "viewer"},
        )
        assert resp.status_code == 401

    def test_invite_nonexistent_user_returns_404(self):
        org, _, owner_token = _create_org("InviteGhost")
        resp = _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members",
            {"email": "nobody@example.com", "role": "member"},
        )
        assert resp.status_code == 404

    def test_invite_existing_member_returns_409(self):
        org, _, owner_token = _create_org("InviteDupe")
        existing_member, _ = _add_member(org, OrganizationRole.MEMBER)

        resp = _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members",
            {"email": existing_member.email, "role": "member"},
        )
        assert resp.status_code == 409

    def test_invite_invalid_role_returns_400(self):
        org, _, owner_token = _create_org("InviteBadRole")
        target, _ = _make_user()

        resp = _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "owner"},
        )
        assert resp.status_code == 400

    def test_invite_sets_invited_by(self):
        org, owner, owner_token = _create_org("InvitedBy")
        target, _ = _make_user()

        _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members",
            {"email": target.email, "role": "member"},
        )
        m = OrganizationMembership.objects.get(organization=org, user=target)
        assert m.invited_by == owner


class TestChangeMemberRole:
    """PATCH /organizations/{org_id}/members/{membership_id}"""

    def test_owner_can_promote_member_to_admin(self):
        org, _, owner_token = _create_org("Promote")
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _patch(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members/{membership.pk}",
            {"role": "admin"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    def test_admin_can_demote_member_to_viewer(self):
        org, _, _ = _create_org("Demote")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/members/{membership.pk}",
            {"role": "viewer"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "viewer"

    def test_admin_cannot_change_owner_role(self):
        org, owner, _ = _create_org("OwnerProtected")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        owner_membership = OrganizationMembership.objects.get(
            organization=org, user=owner
        )

        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/members/{owner_membership.pk}",
            {"role": "admin"},
        )
        assert resp.status_code == 401

    def test_admin_cannot_change_other_admin(self):
        org, _, _ = _create_org("AdminVsAdmin")
        _, admin1_token = _add_member(org, OrganizationRole.ADMIN)
        admin2, _ = _add_member(org, OrganizationRole.ADMIN)
        admin2_membership = OrganizationMembership.objects.get(
            organization=org, user=admin2
        )

        resp = _patch(
            _client(admin1_token),
            f"{_BASE}/{org.pk}/members/{admin2_membership.pk}",
            {"role": "member"},
        )
        assert resp.status_code == 401

    def test_member_cannot_change_roles(self):
        org, _, _ = _create_org("MemberCantManage")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        viewer, _ = _add_member(org, OrganizationRole.VIEWER)
        viewer_membership = OrganizationMembership.objects.get(
            organization=org, user=viewer
        )

        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/members/{viewer_membership.pk}",
            {"role": "member"},
        )
        assert resp.status_code == 401

    def test_non_owner_cannot_promote_to_owner(self):
        org, _, _ = _create_org("NoOwnerPromotion")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/members/{membership.pk}",
            {"role": "owner"},
        )
        assert resp.status_code == 400

    def test_owner_can_promote_to_owner(self):
        org, _, owner_token = _create_org("OwnerTransfer")
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _patch(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members/{membership.pk}",
            {"role": "owner"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "owner"

    def test_cannot_demote_last_owner(self):
        org, owner, owner_token = _create_org("LastOwner")
        owner_membership = OrganizationMembership.objects.get(
            organization=org, user=owner
        )

        resp = _patch(
            _client(owner_token),
            f"{_BASE}/{org.pk}/members/{owner_membership.pk}",
            {"role": "admin"},
        )
        # can_manage_member returns False for owner managing another owner,
        # but owner_membership is self, so the role change should fail at model level
        assert resp.status_code in (400, 401)


class TestRemoveMember:
    """DELETE /organizations/{org_id}/members/{membership_id}"""

    def test_owner_can_remove_member(self):
        org, _, owner_token = _create_org("RemoveTest")
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _client(owner_token).delete(f"{_BASE}/{org.pk}/members/{membership.pk}")
        assert resp.status_code == 200
        assert not org.has_member(member)

    def test_admin_can_remove_member(self):
        org, _, _ = _create_org("AdminRemove")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        membership = OrganizationMembership.objects.get(organization=org, user=member)

        resp = _client(admin_token).delete(f"{_BASE}/{org.pk}/members/{membership.pk}")
        assert resp.status_code == 200

    def test_admin_cannot_remove_owner(self):
        org, owner, _ = _create_org("CantRemoveOwner")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        owner_membership = OrganizationMembership.objects.get(
            organization=org, user=owner
        )

        resp = _client(admin_token).delete(
            f"{_BASE}/{org.pk}/members/{owner_membership.pk}"
        )
        assert resp.status_code == 401

    def test_member_cannot_remove_anyone(self):
        org, _, _ = _create_org("MemberCantRemove")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        viewer, _ = _add_member(org, OrganizationRole.VIEWER)
        viewer_membership = OrganizationMembership.objects.get(
            organization=org, user=viewer
        )

        resp = _client(member_token).delete(
            f"{_BASE}/{org.pk}/members/{viewer_membership.pk}"
        )
        assert resp.status_code == 401

    def test_nonexistent_membership_returns_404(self):
        org, _, owner_token = _create_org("GhostMembership")
        resp = _client(owner_token).delete(
            f"{_BASE}/{org.pk}/members/00000000-0000-0000-0000-000000000000"
        )
        assert resp.status_code == 404


class TestLeaveOrganization:
    """POST /organizations/{org_id}/leave"""

    def test_member_can_leave(self):
        org, _, _ = _create_org("LeaveTest")
        member, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _post(_client(member_token), f"{_BASE}/{org.pk}/leave", {})
        assert resp.status_code == 200
        assert not org.has_member(member)

    def test_last_owner_cannot_leave(self):
        org, _, owner_token = _create_org("LastOwnerLeave")
        resp = _post(_client(owner_token), f"{_BASE}/{org.pk}/leave", {})
        assert resp.status_code == 400

    def test_non_member_cannot_leave(self):
        org, _, _ = _create_org("NotAMember")
        _, outsider_token = _make_user()

        resp = _post(_client(outsider_token), f"{_BASE}/{org.pk}/leave", {})
        assert resp.status_code == 401

    def test_co_owner_can_leave(self):
        org, _, _ = _create_org("CoOwnerLeave")
        co_owner, co_owner_token = _add_member(org, OrganizationRole.OWNER)

        resp = _post(_client(co_owner_token), f"{_BASE}/{org.pk}/leave", {})
        assert resp.status_code == 200
        assert not org.has_member(co_owner)


# =============================================================================
# PROJECT ORG RBAC
# =============================================================================


class TestProjectOrgRBAC:
    """Project endpoints respect org-level RBAC for org-owned projects."""

    _PROJECTS = "/api/v1/spaces/projects"

    def _auth(self, token):
        return _client(token)

    def test_org_member_can_create_project_in_org(self):
        org, _, _ = _create_org("ProjectOrg")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _post(
            self._auth(member_token),
            self._PROJECTS,
            {
                "title": "Org Project",
                "description": "Test",
                "organization_id": str(org.pk),
            },
        )
        assert resp.status_code == 200
        from apps.spaces.models import Project

        project = Project.objects.get(pk=resp.json()["project_id"])
        assert project.organization_id == org.pk

    def test_viewer_cannot_create_project_in_org(self):
        org, _, _ = _create_org("ViewerCantCreate")
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        resp = _post(
            self._auth(viewer_token),
            self._PROJECTS,
            {
                "title": "Blocked",
                "description": "Test",
                "organization_id": str(org.pk),
            },
        )
        assert resp.status_code == 401

    def test_non_member_cannot_create_project_in_org(self):
        org, _, _ = _create_org("NoAccess")
        _, outsider_token = _make_user()

        resp = _post(
            self._auth(outsider_token),
            self._PROJECTS,
            {
                "title": "Blocked",
                "description": "Test",
                "organization_id": str(org.pk),
            },
        )
        assert resp.status_code == 401

    def test_org_member_can_list_org_projects(self):
        org, owner, owner_token = _create_org("ListOrgProjects")
        member, member_token = _add_member(org, OrganizationRole.MEMBER)

        # Owner creates a project in the org
        _post(
            self._auth(owner_token),
            self._PROJECTS,
            {
                "title": "Shared Project",
                "description": "Visible to members",
                "organization_id": str(org.pk),
            },
        )

        # Member switches to org context first (project listing is org-scoped)
        _post(
            self._auth(member_token),
            "/api/v1/workspace/switch-org",
            {"organization_id": str(org.pk)},
        )

        # Member can see it in their project list
        resp = self._auth(member_token).get(self._PROJECTS)
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["items"]]
        assert "Shared Project" in titles

    def test_non_member_cannot_see_org_projects(self):
        org, _, owner_token = _create_org("HiddenProjects")
        _, outsider_token = _make_user()

        _post(
            self._auth(owner_token),
            self._PROJECTS,
            {
                "title": "Secret",
                "description": "Hidden",
                "organization_id": str(org.pk),
            },
        )

        resp = self._auth(outsider_token).get(self._PROJECTS)
        assert resp.status_code == 200
        titles = [p["title"] for p in resp.json()["items"]]
        assert "Secret" not in titles
