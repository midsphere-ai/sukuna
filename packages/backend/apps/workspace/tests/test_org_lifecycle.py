"""Tests for Organization lifecycle management: deletion cascade, slug safety, frozen state.

Covers:
- Enhanced delete with confirm_name + cascade_mode (transfer / destroy)
- Deletion preview (dry-run)
- Active agent runs block deletion (409)
- Slug reservation on delete (90 days)
- Slug change + URL response
- Freeze / unfreeze
- AuditLog entries for lifecycle events
- Cascade integrity
"""

import json
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.spaces.models import Project
from apps.storage.models import AgentRun, Conversation
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    DeletedOrgSlug,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


# ── Helpers ──────────────────────────────────────────────────────────────────


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


def _create_org(name="Test Org"):
    """Create an org + owner. Returns (org, owner, owner_token)."""
    owner, token = _make_user()
    resp = _post(_client(token), f"{_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None):
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


def _create_project_with_conversation(org, user):
    """Create a project in the org with a conversation and agent run."""
    project = Project.objects.create(title="Test Project", user=user, organization=org)
    conversation = Conversation.objects.create(
        user=user,
        project=project,
        title="Test Conversation",
    )
    return project, conversation


# =============================================================================
# DELETION WITH CONFIRMATION
# =============================================================================


class TestDeleteWithConfirmation:
    """DELETE /organizations/{org_id} with confirm_name + cascade_mode."""

    def test_delete_with_destroy_cascade(self):
        org, owner, token = _create_org("DestroyMe")
        project = Project.objects.create(title="P", user=owner, organization=org)

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "DestroyMe", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 200
        assert not Organization.objects.filter(pk=org.pk).exists()
        assert not Project.objects.filter(pk=project.pk).exists()

    def test_delete_with_transfer_cascade(self):
        org, owner, token = _create_org("TransferMe")
        project = Project.objects.create(title="P", user=owner, organization=org)

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "TransferMe", "cascade_mode": "transfer"},
        )
        assert resp.status_code == 200
        assert not Organization.objects.filter(pk=org.pk).exists()
        # Project should still exist but no longer in org
        project.refresh_from_db()
        assert project.organization is None

    def test_wrong_confirm_name_rejected(self):
        org, _, token = _create_org("RealName")
        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "WrongName", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 400
        assert "confirm_name" in resp.json()["detail"]
        assert Organization.objects.filter(pk=org.pk).exists()

    def test_invalid_cascade_mode_rejected(self):
        org, _, token = _create_org("BadCascade")
        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "BadCascade", "cascade_mode": "invalid"},
        )
        assert resp.status_code == 400
        assert "cascade_mode" in resp.json()["detail"]

    def test_delete_creates_audit_log(self):
        org, _, token = _create_org("AuditDelete")
        org_pk = str(org.pk)
        _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "AuditDelete", "cascade_mode": "destroy"},
        )
        log = AuditLog.objects.filter(
            action="org_deleted",
            resource_id=org_pk,
        ).first()
        assert log is not None
        assert log.metadata["cascade_mode"] == "destroy"


# =============================================================================
# ACTIVE RUNS BLOCK DELETION
# =============================================================================


class TestActiveRunsBlockDeletion:
    """Deletion refused if agent runs are running/provisioning."""

    def test_running_agent_run_blocks_delete(self):
        org, owner, token = _create_org("ActiveRuns")
        project, conversation = _create_project_with_conversation(org, owner)
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="test",
            status=AgentRun.Status.RUNNING,
        )

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "ActiveRuns", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 409
        assert Organization.objects.filter(pk=org.pk).exists()

    def test_provisioning_agent_run_blocks_delete(self):
        org, owner, token = _create_org("ProvRuns")
        project, conversation = _create_project_with_conversation(org, owner)
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="test",
            status=AgentRun.Status.PROVISIONING,
        )

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "ProvRuns", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 409

    def test_completed_agent_run_does_not_block(self):
        org, owner, token = _create_org("CompletedRuns")
        project, conversation = _create_project_with_conversation(org, owner)
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="test",
            status=AgentRun.Status.COMPLETED,
        )

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "CompletedRuns", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 200


# =============================================================================
# DELETION PREVIEW
# =============================================================================


class TestDeletionPreview:
    """GET /organizations/{org_id}/deletion-preview"""

    def test_preview_returns_resource_counts(self):
        org, owner, token = _create_org("PreviewOrg")
        _add_member(org, OrganizationRole.MEMBER)
        project, conversation = _create_project_with_conversation(org, owner)
        AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="x",
            status=AgentRun.Status.RUNNING,
        )

        resp = _client(token).get(f"{_BASE}/{org.pk}/deletion-preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["projects"] == 1
        assert data["conversations"] == 1
        assert data["members"] == 2  # owner + member
        assert data["active_agent_runs"] == 1
        assert data["organization_name"] == "PreviewOrg"

    def test_preview_requires_owner_role(self):
        org, _, _ = _create_org("PreviewPerm")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)

        resp = _client(admin_token).get(f"{_BASE}/{org.pk}/deletion-preview")
        assert resp.status_code == 401

    def test_preview_empty_org(self):
        org, _, token = _create_org("EmptyOrg")
        resp = _client(token).get(f"{_BASE}/{org.pk}/deletion-preview")
        assert resp.status_code == 200
        data = resp.json()
        assert data["projects"] == 0
        assert data["conversations"] == 0
        assert data["active_agent_runs"] == 0


# =============================================================================
# SLUG RESERVATION
# =============================================================================


class TestSlugReservation:
    """Deleted org slugs are reserved for 90 days."""

    def test_deleted_org_slug_is_reserved(self):
        org, _, token = _create_org("SlugReserve")
        slug = org.slug

        _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "SlugReserve", "cascade_mode": "destroy"},
        )

        reserved = DeletedOrgSlug.objects.filter(slug=slug).first()
        assert reserved is not None
        assert reserved.is_reserved
        # Reserved for ~90 days
        assert reserved.reserved_until > timezone.now() + timedelta(days=89)

    def test_reserved_slug_cannot_be_used_for_new_org_slug_change(self):
        """Changing an existing org's slug to a reserved one is blocked."""
        org1, _, token1 = _create_org("OrgToDelete")
        slug1 = org1.slug

        _delete(
            _client(token1),
            f"{_BASE}/{org1.pk}",
            {"confirm_name": "OrgToDelete", "cascade_mode": "destroy"},
        )

        org2, _, token2 = _create_org("OrgToChange")
        resp = _patch(
            _client(token2),
            f"{_BASE}/{org2.pk}/slug",
            {"new_slug": slug1},
        )
        assert resp.status_code == 409
        assert "reserved" in resp.json()["detail"]


# =============================================================================
# SLUG CHANGE
# =============================================================================


class TestSlugChange:
    """PATCH /organizations/{org_id}/slug"""

    def test_slug_change_success(self):
        org, _, token = _create_org("OldSlug")
        old_slug = org.slug

        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/slug",
            {"new_slug": "new-slug"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["old_slug"] == old_slug
        assert data["new_slug"] == "new-slug"
        assert "new-slug" in data["new_scim_url"]
        assert old_slug in data["old_scim_url"]

        org.refresh_from_db()
        assert org.slug == "new-slug"

    def test_slug_change_same_slug_rejected(self):
        org, _, token = _create_org("SameSlug")
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/slug",
            {"new_slug": org.slug},
        )
        assert resp.status_code == 400

    def test_slug_change_empty_rejected(self):
        org, _, token = _create_org("EmptySlugTest")
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/slug",
            {"new_slug": "  "},
        )
        assert resp.status_code == 400

    def test_slug_change_duplicate_rejected(self):
        org1, _, _ = _create_org("First")
        org2, _, token2 = _create_org("Second")

        resp = _patch(
            _client(token2),
            f"{_BASE}/{org2.pk}/slug",
            {"new_slug": org1.slug},
        )
        assert resp.status_code == 409
        assert "already in use" in resp.json()["detail"]

    def test_slug_change_creates_audit_log(self):
        org, _, token = _create_org("AuditSlug")
        _patch(
            _client(token),
            f"{_BASE}/{org.pk}/slug",
            {"new_slug": "changed-slug"},
        )
        log = AuditLog.objects.filter(
            action="org_slug_changed",
            resource_id=str(org.pk),
        ).first()
        assert log is not None
        assert log.changes["slug"]["new"] == "changed-slug"

    def test_slug_change_requires_admin(self):
        org, _, _ = _create_org("AdminRequired")
        _, member_token = _add_member(org, OrganizationRole.MEMBER)

        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/slug",
            {"new_slug": "new-slug"},
        )
        assert resp.status_code == 401


# =============================================================================
# FREEZE / UNFREEZE
# =============================================================================


class TestFreezeOrganization:
    """POST /organizations/{org_id}/freeze and /unfreeze"""

    def test_freeze_org(self):
        org, _, token = _create_org("FreezeMe")
        resp = _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})
        assert resp.status_code == 200

        org.refresh_from_db()
        assert org.is_frozen
        assert org.frozen_at is not None

    def test_freeze_already_frozen_rejected(self):
        org, _, token = _create_org("AlreadyFrozen")
        _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})
        resp = _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})
        assert resp.status_code == 400
        assert "already frozen" in resp.json()["detail"]

    def test_unfreeze_org(self):
        org, _, token = _create_org("UnfreezeMe")
        _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})

        resp = _post(_client(token), f"{_BASE}/{org.pk}/unfreeze", {})
        assert resp.status_code == 200

        org.refresh_from_db()
        assert not org.is_frozen
        assert org.frozen_at is None

    def test_unfreeze_not_frozen_rejected(self):
        org, _, token = _create_org("NotFrozen")
        resp = _post(_client(token), f"{_BASE}/{org.pk}/unfreeze", {})
        assert resp.status_code == 400
        assert "not frozen" in resp.json()["detail"]

    def test_freeze_creates_audit_log(self):
        org, _, token = _create_org("AuditFreeze")
        _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})
        log = AuditLog.objects.filter(
            action="org_frozen",
            resource_id=str(org.pk),
        ).first()
        assert log is not None

    def test_unfreeze_creates_audit_log(self):
        org, _, token = _create_org("AuditUnfreeze")
        _post(_client(token), f"{_BASE}/{org.pk}/freeze", {})
        _post(_client(token), f"{_BASE}/{org.pk}/unfreeze", {})
        log = AuditLog.objects.filter(
            action="org_unfrozen",
            resource_id=str(org.pk),
        ).first()
        assert log is not None

    def test_freeze_requires_owner(self):
        org, _, _ = _create_org("FreezePermTest")
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)

        resp = _post(_client(admin_token), f"{_BASE}/{org.pk}/freeze", {})
        assert resp.status_code == 401


# =============================================================================
# CASCADE INTEGRITY
# =============================================================================


class TestCascadeIntegrity:
    """Verify that destroy mode cascades properly through projects → conversations → agent runs."""

    def test_destroy_cascades_all_resources(self):
        org, owner, token = _create_org("CascadeAll")
        project, conversation = _create_project_with_conversation(org, owner)
        run = AgentRun.objects.create(
            conversation=conversation,
            user=owner,
            task="t",
            status=AgentRun.Status.COMPLETED,
        )

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "CascadeAll", "cascade_mode": "destroy"},
        )
        assert resp.status_code == 200
        assert not Project.objects.filter(pk=project.pk).exists()
        assert not Conversation.objects.filter(pk=conversation.pk).exists()
        assert not AgentRun.objects.filter(pk=run.pk).exists()

    def test_transfer_preserves_conversations(self):
        org, owner, token = _create_org("TransferPreserve")
        project, conversation = _create_project_with_conversation(org, owner)

        resp = _delete(
            _client(token),
            f"{_BASE}/{org.pk}",
            {"confirm_name": "TransferPreserve", "cascade_mode": "transfer"},
        )
        assert resp.status_code == 200
        # Project and conversation still exist
        project.refresh_from_db()
        assert project.organization is None
        assert Conversation.objects.filter(pk=conversation.pk).exists()
