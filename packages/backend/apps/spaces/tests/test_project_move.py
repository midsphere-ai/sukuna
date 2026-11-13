"""Tests for project move to/from organization (US-029).

Covers:
- Move project to organization
- Move project back to personal
- Permission checks (owner only, admin+ in target org)
- ProjectShare auto-creation/deletion on move
- Conversations remain intact after move
- Sandbox transfers with project
- Bulk move with batching
- AuditLog entries for each move
- Edge cases: BYOM warnings, MCP config warnings
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


# =============================================================================
# MOVE TO ORGANIZATION
# =============================================================================


class TestMoveToOrganization:
    """Test moving a personal project to an organization."""

    def test_move_project_to_org(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["moved"] is True
        assert body["organization_id"] == str(org.pk)

        project.refresh_from_db()
        assert project.organization_id == org.pk

    def test_move_creates_admin_share_for_owner(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        client = _auth_client(token)
        client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )

        share = ProjectShare.objects.filter(project=project, user=owner).first()
        assert share is not None
        assert share.permission_level == SharePermission.ADMIN

    def test_conversations_remain_after_move(self):
        from apps.storage.models import Conversation

        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        # Create conversations in the project
        conv1 = Conversation.objects.create(project=project, user=owner, title="Conv 1")
        conv2 = Conversation.objects.create(project=project, user=owner, title="Conv 2")

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Conversations still belong to the project
        assert Conversation.objects.filter(project=project).count() == 2
        conv1.refresh_from_db()
        conv2.refresh_from_db()
        assert conv1.project_id == project.pk
        assert conv2.project_id == project.pk

    def test_sandbox_transfers_with_project(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)
        original_sandbox = project.sandbox  # may be None, but FK stays

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        project.refresh_from_db()
        assert project.sandbox == original_sandbox  # Unchanged

    def test_audit_log_created_on_move(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        client = _auth_client(token)
        client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )

        log = AuditLog.objects.filter(
            action=AuditAction.PROJECT_MOVED,
            resource_id=str(project.pk),
        ).first()
        assert log is not None
        assert log.metadata["destination_org_id"] == str(org.pk)
        assert log.metadata["source_org_id"] is None


# =============================================================================
# MOVE BACK TO PERSONAL
# =============================================================================


class TestMoveBackToPersonal:
    """Test moving an org project back to personal space."""

    def test_move_back_to_personal(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": None}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        project.refresh_from_db()
        assert project.organization_id is None

    def test_move_back_removes_owner_share(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        # Create owner share (simulating prior move)
        ProjectShare.objects.create(
            project=project,
            user=owner,
            permission_level=SharePermission.ADMIN,
            shared_by=owner,
        )

        client = _auth_client(token)
        client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": None}),
            content_type="application/json",
        )

        assert not ProjectShare.objects.filter(project=project, user=owner).exists()

    def test_audit_log_on_move_back(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": None}),
            content_type="application/json",
        )

        log = AuditLog.objects.filter(
            action=AuditAction.PROJECT_MOVED,
            resource_id=str(project.pk),
        ).first()
        assert log is not None
        assert log.metadata["source_org_id"] == str(org.pk)
        assert log.metadata["destination_org_id"] is None


# =============================================================================
# PERMISSION CHECKS
# =============================================================================


class TestMovePermissions:
    """Test permission enforcement for project moves."""

    def test_non_owner_cannot_move(self):
        owner, _ = _setup_user()
        other, other_token = _setup_user()
        org = _setup_org(owner)
        _add_member(org, other, role=OrganizationRole.ADMIN)
        project = _setup_project(owner)

        # Share project with other user so they can see it
        ProjectShare.objects.create(
            project=project,
            user=other,
            permission_level=SharePermission.ADMIN,
            shared_by=owner,
        )

        client = _auth_client(other_token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_member_role_cannot_move_to_org(self):
        """User must be admin+ in target org."""
        owner, token = _setup_user()
        org_owner, _ = _setup_user()
        org = _setup_org(org_owner)
        _add_member(org, owner, role=OrganizationRole.MEMBER)

        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_admin_in_org_can_move(self):
        owner, token = _setup_user()
        org_owner, _ = _setup_user()
        org = _setup_org(org_owner)
        _add_member(org, owner, role=OrganizationRole.ADMIN)

        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_move_nonexistent_project_404(self):
        owner, token = _setup_user()
        org = _setup_org(owner)

        client = _auth_client(token)
        fake_id = str(uuid.uuid4())
        resp = client.post(
            f"{_P}/projects/{fake_id}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_move_to_nonexistent_org(self):
        owner, token = _setup_user()
        project = _setup_project(owner)

        client = _auth_client(token)
        fake_org_id = str(uuid.uuid4())
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": fake_org_id}),
            content_type="application/json",
        )
        assert resp.status_code == 400


# =============================================================================
# BULK MOVE
# =============================================================================


class TestBulkMove:
    """Test bulk move of projects."""

    def test_bulk_move_to_org(self):
        owner, token = _setup_user()
        org = _setup_org(owner)

        projects = [_setup_project(owner, title=f"P{i}") for i in range(3)]
        project_ids = [str(p.pk) for p in projects]

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/bulk-move",
            data=json.dumps(
                {
                    "project_ids": project_ids,
                    "organization_id": str(org.pk),
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert body["succeeded"] == 3
        assert body["failed"] == 0

        for p in projects:
            p.refresh_from_db()
            assert p.organization_id == org.pk

    def test_bulk_move_partial_failure(self):
        """Non-owned projects fail individually without blocking others."""
        owner, token = _setup_user()
        other, _ = _setup_user()
        org = _setup_org(owner)

        p1 = _setup_project(owner, title="Mine")
        p2 = _setup_project(other, title="Not mine")

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/bulk-move",
            data=json.dumps(
                {
                    "project_ids": [str(p1.pk), str(p2.pk)],
                    "organization_id": str(org.pk),
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["succeeded"] == 1
        assert body["failed"] == 1

    def test_bulk_move_audit_logs(self):
        owner, token = _setup_user()
        org = _setup_org(owner)

        projects = [_setup_project(owner, title=f"P{i}") for i in range(2)]
        project_ids = [str(p.pk) for p in projects]

        client = _auth_client(token)
        client.post(
            f"{_P}/projects/bulk-move",
            data=json.dumps(
                {
                    "project_ids": project_ids,
                    "organization_id": str(org.pk),
                }
            ),
            content_type="application/json",
        )

        logs = AuditLog.objects.filter(action=AuditAction.PROJECT_MOVED)
        assert logs.count() == 2
        for log in logs:
            assert log.metadata["bulk"] is True

    def test_bulk_move_empty_ids_rejected(self):
        owner, token = _setup_user()
        org = _setup_org(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/bulk-move",
            data=json.dumps(
                {
                    "project_ids": [],
                    "organization_id": str(org.pk),
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 400


# =============================================================================
# EDGE CASES: BYOM + MCP warnings
# =============================================================================


class TestMoveWarnings:
    """Test warning generation for BYOM and MCP configs."""

    def test_byom_warning_on_move(self):
        from apps.agents.models import UserProviderConfig

        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        # Create a BYOM config for the owner
        UserProviderConfig.objects.create(
            user=owner,
            tool_slot=UserProviderConfig.ToolSlot.LEAD_AGENT,
            provider_name="openai",
            model_name="gpt-4o",
            api_key_encrypted=b"gAAAAABencrypted",
        )

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert any("BYOM" in w for w in body["warnings"])

    def test_mcp_config_warning_on_move(self):
        from apps.agents.models import UserCustomMCPConfig

        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        UserCustomMCPConfig.objects.create(
            user=owner,
            server_name="My MCP Tool",
            server_type=UserCustomMCPConfig.ServerType.SSE,
            url="http://localhost:8000",
        )

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert any("MCP" in w for w in body["warnings"])

    def test_no_warnings_when_no_byom_mcp(self):
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["warnings"] == []

    def test_move_back_no_warnings(self):
        """Moving back to personal should not generate BYOM/MCP warnings."""
        owner, token = _setup_user()
        org = _setup_org(owner)
        project = _setup_project(owner, organization=org)

        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": None}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["warnings"] == []
