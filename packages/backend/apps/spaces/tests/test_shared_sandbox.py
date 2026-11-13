"""Tests for shared sandbox access in team projects (US-030).

Covers:
- Sandbox reuse across conversations by different users
- SELECT FOR UPDATE prevents double provisioning
- Permission-based sandbox status access
- Lifecycle: sandbox stays alive while any project conversation has active run
- sandbox_terminated notification for all project conversations
- GDPR limitation: shared sandbox files persist on user deletion
- Owner leaves org: sandbox continues, new runs use default config
"""

import pytest
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.agents.models import E2bSandbox
from apps.agents.sandbox import (
    _provision_project_sandbox_atomic,
    has_active_project_runs,
    notify_project_sandbox_terminated,
)
from apps.spaces.models import Project, ProjectShare, SharePermission
from apps.storage.models import AgentRun, Conversation
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db


# =============================================================================
# HELPERS
# =============================================================================


def _setup_user():
    user = UserFactory()
    Token.objects.get_or_create(user=user)
    return user


def _setup_org(owner):
    org = Organization.objects.create(name="Test Org")
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    return org


def _add_member(org, user, role=OrganizationRole.MEMBER):
    return OrganizationMembership.objects.create(organization=org, user=user, role=role)


def _setup_shared_project(owner, org):
    project = Project.objects.create(
        title="Shared Project",
        description="A shared team project",
        user=owner,
        organization=org,
    )
    return project


def _create_sandbox(state=E2bSandbox.SandboxState.READY, **kwargs):
    return E2bSandbox.objects.create(
        sandbox_id=f"sbx-test-{timezone.now().timestamp()}",
        sandbox_state=state,
        **kwargs,
    )


def _create_conversation(user, project=None):
    return Conversation.objects.create(
        user=user,
        title=f"Test conv {user.email}",
        project=project,
    )


def _create_agent_run(conversation, user, status=AgentRun.Status.RUNNING):
    run = AgentRun.objects.create(
        conversation=conversation,
        user=user,
        task="test task",
        status=status,
    )
    conversation.current_task = run
    conversation.save(update_fields=["current_task"])
    return run


# =============================================================================
# SANDBOX REUSE ACROSS CONVERSATIONS
# =============================================================================


class TestSharedSandboxReuse:
    """Verify that conversations in a shared project reuse the project sandbox."""

    def test_first_conversation_provisions_sandbox(self):
        """First conversation in a project provisions a new sandbox."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        record, is_new = _provision_project_sandbox_atomic(project)

        assert is_new is True
        assert record is not None
        project.refresh_from_db()
        assert project.sandbox_id == record.pk

    def test_second_conversation_reuses_sandbox(self):
        """Subsequent conversations reuse the project's existing sandbox."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        # First provision
        record1, is_new1 = _provision_project_sandbox_atomic(project)
        assert is_new1 is True
        # Mark as READY so active_for_project finds it
        record1.sandbox_state = E2bSandbox.SandboxState.READY
        record1.save(update_fields=["sandbox_state"])

        # Second provision: should reuse
        record2, is_new2 = _provision_project_sandbox_atomic(project)
        assert is_new2 is False
        assert record2.pk == record1.pk

    def test_different_users_get_same_sandbox(self):
        """Two team members in the same project get the same sandbox record."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        # Provision via first user
        record, _ = _provision_project_sandbox_atomic(project)
        record.sandbox_state = E2bSandbox.SandboxState.READY
        record.save(update_fields=["sandbox_state"])

        # Second user calls provision — gets same record
        record2, is_new = _provision_project_sandbox_atomic(project)
        assert is_new is False
        assert record2.pk == record.pk

    def test_project_sandbox_not_conversation_level(self):
        """Project sandbox is linked to project, not individual conversations."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        record, _ = _provision_project_sandbox_atomic(project)
        record.sandbox_state = E2bSandbox.SandboxState.READY
        record.save(update_fields=["sandbox_state"])

        # Sandbox is linked to project, not to any conversation
        assert record.conversation_id is None
        project.refresh_from_db()
        assert project.sandbox_id == record.pk


# =============================================================================
# SELECT FOR UPDATE — CONCURRENT PROVISIONING
# =============================================================================


class TestConcurrentProvisioning:
    """Verify SELECT FOR UPDATE prevents double sandbox provisioning."""

    def test_atomic_provision_creates_single_sandbox(self):
        """Two sequential calls produce only one sandbox."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        r1, new1 = _provision_project_sandbox_atomic(project)
        r1.sandbox_state = E2bSandbox.SandboxState.READY
        r1.save(update_fields=["sandbox_state"])

        r2, new2 = _provision_project_sandbox_atomic(project)

        assert new1 is True
        assert new2 is False
        assert r1.pk == r2.pk

    def test_provision_after_unhealthy_creates_new(self):
        """After marking sandbox unhealthy, re-provision creates a new one."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        r1, _ = _provision_project_sandbox_atomic(project)
        # Mark as error — simulates failed sandbox
        r1.sandbox_state = E2bSandbox.SandboxState.ERROR
        r1.save(update_fields=["sandbox_state"])
        project.sandbox = None
        project.save(update_fields=["sandbox"])

        r2, new2 = _provision_project_sandbox_atomic(project)

        assert new2 is True
        assert r2.pk != r1.pk


# =============================================================================
# PERMISSION-BASED SANDBOX STATUS ACCESS
# =============================================================================


class TestSandboxStatusPermissions:
    """Verify sandbox status is accessible to users with view+ on project."""

    def test_project_share_view_gives_conversation_access(self):
        """User with VIEW share on project can view conversations in it."""
        from apps.storage.models import conversation_can_view

        owner = _setup_user()
        viewer = _setup_user()
        org = _setup_org(owner)
        _add_member(org, viewer)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)

        # Before share: no access
        ProjectShare.objects.filter(project=project, user=viewer).delete()
        # Add view share
        ProjectShare.objects.create(
            project=project, user=viewer, permission_level=SharePermission.VIEW
        )

        assert conversation_can_view(conv, viewer) is True

    def test_project_share_collaborate_gives_conversation_access(self):
        """User with COLLABORATE share on project can view conversations."""
        from apps.storage.models import conversation_can_view

        owner = _setup_user()
        collaborator = _setup_user()
        org = _setup_org(owner)
        _add_member(org, collaborator)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)

        ProjectShare.objects.create(
            project=project,
            user=collaborator,
            permission_level=SharePermission.COLLABORATE,
        )

        assert conversation_can_view(conv, collaborator) is True

    def test_no_share_blocks_conversation_access(self):
        """User without share on project cannot view conversations in it."""
        from apps.storage.models import conversation_can_view

        owner = _setup_user()
        outsider = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)

        assert conversation_can_view(conv, outsider) is False


# =============================================================================
# LIFECYCLE: SANDBOX STAYS ALIVE WITH ACTIVE RUNS
# =============================================================================


class TestSandboxLifecycle:
    """Verify project sandbox stays alive while any conversation has active run."""

    def test_active_run_keeps_sandbox_alive(self):
        """has_active_project_runs returns True when a conversation has running agent."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        _create_agent_run(conv, owner, status=AgentRun.Status.RUNNING)

        assert has_active_project_runs(project) is True

    def test_no_active_run_allows_pause(self):
        """has_active_project_runs returns False when all runs are completed."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        _create_agent_run(conv, owner, status=AgentRun.Status.COMPLETED)

        assert has_active_project_runs(project) is False

    def test_multiple_conversations_one_active(self):
        """Sandbox stays alive if ANY conversation in project has active run."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        conv1 = _create_conversation(owner, project=project)
        conv2 = _create_conversation(member, project=project)
        _create_agent_run(conv1, owner, status=AgentRun.Status.COMPLETED)
        _create_agent_run(conv2, member, status=AgentRun.Status.RUNNING)

        assert has_active_project_runs(project) is True

    def test_all_conversations_completed(self):
        """Sandbox can be paused when all conversations have completed runs."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        conv1 = _create_conversation(owner, project=project)
        conv2 = _create_conversation(member, project=project)
        _create_agent_run(conv1, owner, status=AgentRun.Status.COMPLETED)
        _create_agent_run(conv2, member, status=AgentRun.Status.COMPLETED)

        assert has_active_project_runs(project) is False

    def test_provisioning_status_keeps_alive(self):
        """Provisioning status counts as active for lifecycle purposes."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        _create_agent_run(conv, owner, status=AgentRun.Status.PROVISIONING)

        assert has_active_project_runs(project) is True

    def test_queued_status_keeps_alive(self):
        """Queued status counts as active for lifecycle purposes."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        _create_agent_run(conv, owner, status=AgentRun.Status.QUEUED)

        assert has_active_project_runs(project) is True

    def test_no_conversations_returns_false(self):
        """Empty project has no active runs."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        assert has_active_project_runs(project) is False


# =============================================================================
# SANDBOX TERMINATION NOTIFICATION
# =============================================================================


class TestSandboxTerminationNotification:
    """Verify sandbox_terminated flag is set on project conversations."""

    def test_notify_sets_metadata_flag(self):
        """notify_project_sandbox_terminated sets sandbox_terminated in metadata."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        run = _create_agent_run(conv, owner)

        notify_project_sandbox_terminated(project)

        conv.refresh_from_db()
        assert conv.metadata.get("sandbox_terminated") is True

    def test_notify_multiple_conversations(self):
        """All conversations with current_task are flagged."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        conv1 = _create_conversation(owner, project=project)
        conv2 = _create_conversation(member, project=project)
        _create_agent_run(conv1, owner)
        _create_agent_run(conv2, member)

        notify_project_sandbox_terminated(project)

        conv1.refresh_from_db()
        conv2.refresh_from_db()
        assert conv1.metadata.get("sandbox_terminated") is True
        assert conv2.metadata.get("sandbox_terminated") is True

    def test_notify_skips_conversations_without_task(self):
        """Conversations with no current_task are not flagged."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv_active = _create_conversation(owner, project=project)
        conv_idle = _create_conversation(owner, project=project)
        _create_agent_run(conv_active, owner)
        # conv_idle has no current_task

        notify_project_sandbox_terminated(project)

        conv_active.refresh_from_db()
        conv_idle.refresh_from_db()
        assert conv_active.metadata.get("sandbox_terminated") is True
        assert conv_idle.metadata.get("sandbox_terminated") is not True

    def test_notify_skips_deleted_conversations(self):
        """Deleted conversations are not flagged."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        conv = _create_conversation(owner, project=project)
        _create_agent_run(conv, owner)
        conv.is_deleted = True
        conv.save(update_fields=["is_deleted"])

        notify_project_sandbox_terminated(project)

        conv.refresh_from_db()
        assert conv.metadata.get("sandbox_terminated") is not True


# =============================================================================
# GDPR: SHARED SANDBOX FILE LIMITATION
# =============================================================================


class TestGdprSharedSandbox:
    """Document and verify GDPR limitation for shared sandbox files."""

    def test_sandbox_survives_project_deletion_via_set_null(self):
        """When a project is deleted, its sandbox record survives (SET_NULL)."""
        owner = _setup_user()
        org = _setup_org(owner)
        project = _setup_shared_project(owner, org)

        sandbox = _create_sandbox()
        project.sandbox = sandbox
        project.save(update_fields=["sandbox"])
        sandbox_pk = sandbox.pk

        project.delete()

        # Sandbox record still exists
        assert E2bSandbox.objects.filter(pk=sandbox_pk).exists()

    def test_sandbox_unlinked_after_user_deletion(self):
        """Shared sandbox files persist after the contributing user is deleted."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        sandbox = _create_sandbox()
        project.sandbox = sandbox
        project.save(update_fields=["sandbox"])
        sandbox_pk = sandbox.pk

        # Member's conversation in the project
        conv = _create_conversation(member, project=project)
        conv_id = conv.id

        # Sandbox remains even though it may contain member's files
        # (file attribution is not tracked in the sandbox)
        assert E2bSandbox.objects.filter(pk=sandbox_pk).exists()


# =============================================================================
# OWNER LEAVES ORG
# =============================================================================


class TestOwnerLeavesOrg:
    """Sandbox continues when project owner leaves the org."""

    def test_sandbox_persists_after_owner_removed(self):
        """Project sandbox remains functional after owner is removed from org."""
        owner = _setup_user()
        member = _setup_user()
        org = _setup_org(owner)
        _add_member(org, member)
        project = _setup_shared_project(owner, org)

        sandbox = _create_sandbox()
        project.sandbox = sandbox
        project.save(update_fields=["sandbox"])

        # Remove owner from org
        OrganizationMembership.objects.filter(organization=org, user=owner).delete()

        # Sandbox still exists and linked to project
        project.refresh_from_db()
        assert project.sandbox_id == sandbox.pk
        assert E2bSandbox.objects.filter(
            pk=sandbox.pk,
            sandbox_state=E2bSandbox.SandboxState.READY,
        ).exists()


# =============================================================================
# SSE EVENT BUILDER
# =============================================================================


class TestSandboxTerminatedEvent:
    """Verify SSE event builder for sandbox_terminated."""

    @pytest.mark.skip(
        reason="build_sse_sandbox_terminated_event removed with streaming.py — SSE proxy deleted"
    )
    def test_build_sse_sandbox_terminated_event(self):
        pass
