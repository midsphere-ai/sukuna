"""Tests for ProjectShare model + API (US-017).

Covers:
- Share CRUD via API
- Permission enforcement (owner, admin share)
- Org-wide shares vs user-specific shares
- Duplicate prevention
- Owner implicit access (no record needed)
- Shared projects appear in listing
- Cross-org sharing prevention
- Org-wide share: new member gains access dynamically
- User-specific > org-wide precedence
- AuditLog entries
- Edge cases
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditAction, AuditLog
from apps.spaces.models import Project, ProjectShare, SharePermission
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_P = "/api/v1/spaces"


# =============================================================================
# HELPERS
# =============================================================================


def _setup_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _auth_client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _setup_project(user, title="Test Project", organization=None):
    return Project.objects.create(
        title=title,
        description="Test description",
        user=user,
        organization=organization,
    )


def _setup_org(owner):
    org = Organization.objects.create(name="Test Org")
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    return org


def _add_member(org, user, role=OrganizationRole.MEMBER):
    return OrganizationMembership.objects.create(organization=org, user=user, role=role)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


# =============================================================================
# MODEL TESTS
# =============================================================================


class TestProjectShareModel:
    def test_create_user_share(self):
        owner, _ = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        share = ProjectShare.objects.create(
            project=project,
            user=target,
            permission_level=SharePermission.VIEW,
            shared_by=owner,
        )

        assert share.project == project
        assert share.user == target
        assert share.organization is None
        assert share.permission_level == SharePermission.VIEW
        assert share.shared_by == owner

    def test_create_org_share(self):
        owner, _ = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        share = ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.COLLABORATE,
            shared_by=owner,
        )

        assert share.organization == org
        assert share.user is None

    def test_unique_user_share(self):
        """Cannot create duplicate user-specific shares for the same project."""
        owner, _ = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project,
            user=target,
            permission_level=SharePermission.VIEW,
        )

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            ProjectShare.objects.create(
                project=project,
                user=target,
                permission_level=SharePermission.COLLABORATE,
            )

    def test_unique_org_share(self):
        """Cannot create duplicate org-wide shares for the same project."""
        owner, _ = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.VIEW,
        )

        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            ProjectShare.objects.create(
                project=project,
                organization=org,
                permission_level=SharePermission.COLLABORATE,
            )

    def test_cascade_on_project_delete(self):
        owner, _ = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        project.delete()
        assert ProjectShare.objects.count() == 0

    def test_cascade_on_user_delete(self):
        owner, _ = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        target.delete()
        assert ProjectShare.objects.count() == 0

    def test_shared_by_set_null(self):
        owner, _ = _setup_user()
        target, _ = _setup_user()
        sharer, _ = _setup_user()
        project = _setup_project(owner)

        share = ProjectShare.objects.create(
            project=project,
            user=target,
            permission_level=SharePermission.VIEW,
            shared_by=sharer,
        )

        sharer.delete()
        share.refresh_from_db()
        assert share.shared_by is None


# =============================================================================
# API - CREATE SHARE
# =============================================================================


class TestCreateShareAPI:
    def test_owner_can_share_with_user(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {"user_id": str(target.pk), "permission_level": "collaborate"}
            ),
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == str(target.pk)
        assert data["permission_level"] == "collaborate"
        assert data["shared_by_id"] == str(owner.pk)

    def test_owner_can_share_with_org(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {"organization_id": str(org.pk), "permission_level": "view"}
            ),
            content_type="application/json",
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_id"] == str(org.pk)
        assert data["permission_level"] == "view"

    def test_admin_share_user_can_share(self):
        """User with admin share permission can create new shares."""
        owner, _ = _setup_user()
        admin_user, admin_token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, admin_user)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        # Give admin_user admin share permission
        ProjectShare.objects.create(
            project=project,
            user=admin_user,
            permission_level=SharePermission.ADMIN,
            shared_by=owner,
        )

        client = _auth_client(admin_token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(target.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 200

    def test_non_admin_cannot_share(self):
        """User with view/collaborate share cannot create new shares."""
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, viewer)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project,
            user=viewer,
            permission_level=SharePermission.VIEW,
            shared_by=owner,
        )

        client = _auth_client(viewer_token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(target.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 401

    def test_cannot_share_with_owner(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(owner.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_must_provide_user_or_org(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_cannot_provide_both_user_and_org(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {
                    "user_id": str(target.pk),
                    "organization_id": str(org.pk),
                    "permission_level": "view",
                }
            ),
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_invalid_permission_level(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {"user_id": str(target.pk), "permission_level": "superadmin"}
            ),
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_duplicate_share_fails(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        # First share
        resp1 = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(target.pk), "permission_level": "view"}),
            content_type="application/json",
        )
        assert resp1.status_code == 200

        # Duplicate
        resp2 = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {"user_id": str(target.pk), "permission_level": "collaborate"}
            ),
            content_type="application/json",
        )
        # Should fail due to unique constraint
        assert resp2.status_code != 200

    def test_cross_org_sharing_prevented(self):
        """Cannot share an org project with a user from a different org."""
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        outsider, _ = _setup_user()  # Not a member of org

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(outsider.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 400
        assert "outside" in resp.json().get("error", "").lower()

    def test_cross_org_org_share_prevented(self):
        """Cannot share a project from Org A with Org B."""
        owner, token = _setup_user()
        org_a = _setup_org(owner)
        project = _setup_project(owner, organization=org_a)

        other_owner, _ = _setup_user()
        org_b = Organization.objects.create(name="Org B")
        OrganizationMembership.objects.create(
            organization=org_b, user=other_owner, role=OrganizationRole.OWNER
        )

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps(
                {
                    "organization_id": str(org_b.pk),
                    "permission_level": "view",
                }
            ),
            content_type="application/json",
        )

        assert resp.status_code == 400

    def test_share_personal_project_with_user(self):
        """Can share a personal (non-org) project directly with a user."""
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)  # No org

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(target.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 200

    def test_audit_log_on_create(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(target.pk), "permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 200
        log = AuditLog.objects.filter(action=AuditAction.PROJECT_SHARED).first()
        assert log is not None
        assert log.actor_email == owner.email
        assert log.metadata["project_id"] == str(project.pk)


# =============================================================================
# API - LIST SHARES
# =============================================================================


class TestListSharesAPI:
    def test_list_shares(self):
        owner, token = _setup_user()
        target1, _ = _setup_user()
        target2, _ = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=target1, permission_level=SharePermission.VIEW
        )
        ProjectShare.objects.create(
            project=project, user=target2, permission_level=SharePermission.COLLABORATE
        )

        client = _auth_client(token)
        resp = client.get(f"{_P}/projects/{project.id}/shares")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    def test_collaborator_can_list_shares(self):
        """Users with any share level can list shares."""
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        org = _setup_org(owner)
        _add_member(org, viewer)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )

        client = _auth_client(viewer_token)
        resp = client.get(f"{_P}/projects/{project.id}/shares")

        assert resp.status_code == 200

    def test_non_participant_cannot_list(self):
        owner, _ = _setup_user()
        stranger, stranger_token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(stranger_token)
        resp = client.get(f"{_P}/projects/{project.id}/shares")

        assert resp.status_code == 401


# =============================================================================
# API - UPDATE SHARE
# =============================================================================


class TestUpdateShareAPI:
    def test_owner_can_update_share(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)
        share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(token)
        resp = client.patch(
            f"{_P}/projects/{project.id}/shares/{share.pk}",
            data=json.dumps({"permission_level": "admin"}),
            content_type="application/json",
        )

        assert resp.status_code == 200
        assert resp.json()["permission_level"] == "admin"

    def test_non_admin_cannot_update(self):
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, viewer)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        viewer_share = ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )
        target_share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(viewer_token)
        resp = client.patch(
            f"{_P}/projects/{project.id}/shares/{target_share.pk}",
            data=json.dumps({"permission_level": "collaborate"}),
            content_type="application/json",
        )

        assert resp.status_code == 401

    def test_update_nonexistent_share(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.patch(
            f"{_P}/projects/{project.id}/shares/{uuid.uuid4()}",
            data=json.dumps({"permission_level": "view"}),
            content_type="application/json",
        )

        assert resp.status_code == 404

    def test_audit_log_on_update(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)
        share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(token)
        client.patch(
            f"{_P}/projects/{project.id}/shares/{share.pk}",
            data=json.dumps({"permission_level": "admin"}),
            content_type="application/json",
        )

        log = AuditLog.objects.filter(action=AuditAction.PROJECT_SHARE_UPDATED).first()
        assert log is not None
        assert log.changes["permission_level"]["old"] == "view"
        assert log.changes["permission_level"]["new"] == "admin"


# =============================================================================
# API - DELETE SHARE
# =============================================================================


class TestDeleteShareAPI:
    def test_owner_can_revoke_share(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)
        share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(token)
        resp = client.delete(f"{_P}/projects/{project.id}/shares/{share.pk}")

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not ProjectShare.objects.filter(pk=share.pk).exists()

    def test_admin_share_can_revoke(self):
        owner, _ = _setup_user()
        admin_user, admin_token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, admin_user)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project, user=admin_user, permission_level=SharePermission.ADMIN
        )
        target_share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(admin_token)
        resp = client.delete(f"{_P}/projects/{project.id}/shares/{target_share.pk}")

        assert resp.status_code == 200

    def test_non_admin_cannot_revoke(self):
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        target, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, viewer)
        _add_member(org, target)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )
        target_share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(viewer_token)
        resp = client.delete(f"{_P}/projects/{project.id}/shares/{target_share.pk}")

        assert resp.status_code == 401

    def test_audit_log_on_revoke(self):
        owner, token = _setup_user()
        target, _ = _setup_user()
        project = _setup_project(owner)
        share = ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(token)
        client.delete(f"{_P}/projects/{project.id}/shares/{share.pk}")

        log = AuditLog.objects.filter(action=AuditAction.PROJECT_SHARE_REVOKED).first()
        assert log is not None
        assert log.metadata["target_user_id"] == str(target.pk)

    def test_revoke_nonexistent(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.delete(f"{_P}/projects/{project.id}/shares/{uuid.uuid4()}")

        assert resp.status_code == 404


# =============================================================================
# SHARED PROJECTS IN LISTING
# =============================================================================


class TestSharedProjectsInListing:
    def test_shared_project_appears_in_listing(self):
        """Projects shared with a user appear in their project listing."""
        owner, _ = _setup_user()
        target, target_token = _setup_user()
        project = _setup_project(owner, title="Shared Project")

        ProjectShare.objects.create(
            project=project, user=target, permission_level=SharePermission.VIEW
        )

        client = _auth_client(target_token)
        resp = client.get(f"{_P}/projects")

        assert resp.status_code == 200
        data = resp.json()
        project_ids = [p["id"] for p in data["items"]]
        assert str(project.id) in project_ids

    def test_org_wide_share_appears_for_org_members(self):
        """Org-wide share makes the project appear for all org members."""
        owner, _ = _setup_user()
        member, member_token = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.VIEW,
        )

        # Set active org for member
        from apps.users.models import UserSettings

        settings, _ = UserSettings.objects.get_or_create(user=member)
        settings.last_active_org = org
        settings.save()

        client = _auth_client(member_token)
        resp = client.get(f"{_P}/projects")

        assert resp.status_code == 200
        data = resp.json()
        project_ids = [p["id"] for p in data["items"]]
        assert str(project.id) in project_ids

    def test_new_member_gains_access_via_org_share(self):
        """When a new member joins an org, they gain access to org-shared projects dynamically."""
        owner, _ = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.COLLABORATE,
        )

        # New member joins after the share was created
        new_member, new_token = _setup_user()
        _add_member(org, new_member)

        from apps.users.models import UserSettings

        settings, _ = UserSettings.objects.get_or_create(user=new_member)
        settings.last_active_org = org
        settings.save()

        client = _auth_client(new_token)
        resp = client.get(f"{_P}/projects")

        assert resp.status_code == 200
        data = resp.json()
        project_ids = [p["id"] for p in data["items"]]
        assert str(project.id) in project_ids


# =============================================================================
# OWNER IMPLICIT ACCESS
# =============================================================================


class TestOwnerImplicitAccess:
    def test_owner_has_access_without_share_record(self):
        """Project owner always has admin-level access without a ProjectShare."""
        owner, token = _setup_user()
        project = _setup_project(owner)

        assert ProjectShare.objects.filter(project=project, user=owner).count() == 0

        client = _auth_client(token)
        resp = client.get(f"{_P}/projects/{project.id}")

        assert resp.status_code == 200

    def test_owner_can_modify_without_share(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Updated"}),
            content_type="application/json",
        )

        assert resp.status_code == 200


# =============================================================================
# PRECEDENCE: USER-SPECIFIC > ORG-WIDE
# =============================================================================


class TestSharePrecedence:
    def test_user_specific_overrides_org_wide(self):
        """When user has both user-specific and org-wide share, user-specific wins."""
        from apps.spaces.service import get_effective_share

        owner, _ = _setup_user()
        member, _ = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_project(owner, organization=org)

        # Org-wide share: view
        ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.VIEW,
        )
        # User-specific share: admin
        ProjectShare.objects.create(
            project=project,
            user=member,
            permission_level=SharePermission.ADMIN,
        )

        share = get_effective_share(project, member)
        assert share is not None
        assert share.permission_level == SharePermission.ADMIN
        assert share.user == member  # user-specific, not org-wide


# =============================================================================
# SHARE-BASED PROJECT ACCESS
# =============================================================================


class TestShareBasedAccess:
    def test_shared_user_can_view_project(self):
        """User with view share can read project details."""
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )

        client = _auth_client(viewer_token)
        resp = client.get(f"{_P}/projects/{project.id}")

        assert resp.status_code == 200

    def test_view_share_cannot_modify(self):
        """User with view-only share cannot modify the project."""
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )

        client = _auth_client(viewer_token)
        resp = client.patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Hacked"}),
            content_type="application/json",
        )

        assert resp.status_code == 401

    def test_collaborate_share_can_modify(self):
        """User with collaborate share can modify the project."""
        owner, _ = _setup_user()
        collaborator, collab_token = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project,
            user=collaborator,
            permission_level=SharePermission.COLLABORATE,
        )

        client = _auth_client(collab_token)
        resp = client.patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Collaboration Edit"}),
            content_type="application/json",
        )

        assert resp.status_code == 200

    def test_admin_share_can_modify(self):
        """User with admin share can modify the project."""
        owner, _ = _setup_user()
        admin_user, admin_token = _setup_user()
        project = _setup_project(owner)

        ProjectShare.objects.create(
            project=project, user=admin_user, permission_level=SharePermission.ADMIN
        )

        client = _auth_client(admin_token)
        resp = client.patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Admin Edit"}),
            content_type="application/json",
        )

        assert resp.status_code == 200

    def test_unshared_user_cannot_access(self):
        """User with no share cannot access the project."""
        owner, _ = _setup_user()
        stranger, stranger_token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(stranger_token)
        resp = client.get(f"{_P}/projects/{project.id}")

        assert resp.status_code == 401

    def test_revoked_share_blocks_access(self):
        """After share is revoked, user immediately loses access."""
        owner, _ = _setup_user()
        viewer, viewer_token = _setup_user()
        project = _setup_project(owner)

        share = ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )

        # Verify access
        client = _auth_client(viewer_token)
        resp = client.get(f"{_P}/projects/{project.id}")
        assert resp.status_code == 200

        # Revoke and clear cache so next request checks permissions fresh
        share.delete()
        cache.clear()

        # Access should be blocked
        resp = client.get(f"{_P}/projects/{project.id}")
        assert resp.status_code == 401


# =============================================================================
# ENTERPRISE MODE GATE
# =============================================================================


class TestEnterpriseGate:
    def _disable_enterprise(self, user):
        from apps.workspace.models import EnterpriseConfig

        config, _ = EnterpriseConfig.objects.get_or_create(user=user)
        config.enabled = False
        config.save()

    def test_share_endpoints_require_enterprise(self):
        """Share API endpoints return 403 when enterprise mode is disabled."""
        owner, token = _setup_user()
        self._disable_enterprise(owner)
        project = _setup_project(owner)

        client = _auth_client(token)

        # POST
        resp = client.post(
            f"{_P}/projects/{project.id}/shares",
            data=json.dumps({"user_id": str(uuid.uuid4()), "permission_level": "view"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

        # GET
        resp = client.get(f"{_P}/projects/{project.id}/shares")
        assert resp.status_code == 403

        # PATCH
        resp = client.patch(
            f"{_P}/projects/{project.id}/shares/{uuid.uuid4()}",
            data=json.dumps({"permission_level": "view"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

        # DELETE
        resp = client.delete(f"{_P}/projects/{project.id}/shares/{uuid.uuid4()}")
        assert resp.status_code == 403
