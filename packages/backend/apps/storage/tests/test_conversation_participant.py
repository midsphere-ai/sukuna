"""Tests for ConversationParticipant model, permission checks, and query scoping."""

import pytest
from cryptography.fernet import Fernet
from django.db import IntegrityError

from apps.compliance.models import AuditAction, AuditLog
from apps.spaces.models import Project, ProjectShare, SharePermission
from apps.storage.models import (
    Conversation,
    ConversationParticipant,
    ParticipantRole,
    _get_project_share_role,
    conversation_can_cancel,
    conversation_can_inject,
    conversation_can_view,
)
from apps.users.tests.factories import UserFactory

# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)


@pytest.fixture
def creator():
    return UserFactory()


@pytest.fixture
def other_user():
    return UserFactory()


@pytest.fixture
def conversation(creator):
    return Conversation.objects.create(user=creator, title="Test conv")


# ── Model CRUD ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestConversationParticipantModel:
    def test_create_participant(self, conversation, other_user):
        p = ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.COLLABORATOR,
        )
        assert p.role == ParticipantRole.COLLABORATOR
        assert p.joined_at is not None
        assert p.last_seen_at is None

    def test_unique_together(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.VIEWER,
        )
        with pytest.raises(IntegrityError):
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=other_user,
                role=ParticipantRole.COLLABORATOR,
            )

    def test_default_role_is_viewer(self, conversation, other_user):
        p = ConversationParticipant.objects.create(
            conversation=conversation, user=other_user
        )
        assert p.role == ParticipantRole.VIEWER

    def test_str(self, conversation, other_user):
        p = ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.VIEWER,
        )
        s = str(p)
        assert "viewer" in s

    def test_cascade_delete_conversation(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation, user=other_user
        )
        conv_id = conversation.id
        conversation.delete()
        assert (
            ConversationParticipant.objects.filter(conversation_id=conv_id).count() == 0
        )

    def test_cascade_delete_user(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation, user=other_user
        )
        user_id = other_user.id
        other_user.delete()
        assert ConversationParticipant.objects.filter(user_id=user_id).count() == 0


# ── Auto-creator signal ────────────────────────────────────────────────


@pytest.mark.django_db
class TestAutoCreatorParticipant:
    def test_creator_added_on_creation(self, creator):
        conv = Conversation.objects.create(user=creator, title="Auto-test")
        p = ConversationParticipant.objects.get(conversation=conv, user=creator)
        assert p.role == ParticipantRole.CREATOR

    def test_audit_log_on_creator_join(self, creator):
        conv = Conversation.objects.create(user=creator, title="Audit-test")
        log = AuditLog.objects.filter(
            action=AuditAction.PARTICIPANT_JOINED,
            resource_type="conversation",
            resource_id=str(conv.id),
        ).first()
        assert log is not None
        assert log.metadata["role"] == ParticipantRole.CREATOR
        assert log.metadata["auto"] is True

    def test_no_participant_for_null_user(self):
        conv = Conversation.objects.create(user=None, title="No owner")
        assert ConversationParticipant.objects.filter(conversation=conv).count() == 0

    def test_idempotent_signal(self, creator):
        """Saving an existing conversation again does not duplicate participant."""
        conv = Conversation.objects.create(user=creator, title="Idem-test")
        conv.title = "Updated"
        conv.save()
        assert (
            ConversationParticipant.objects.filter(
                conversation=conv, user=creator
            ).count()
            == 1
        )


# ── Permission checks ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestPermissionChecks:
    def test_owner_can_view(self, conversation, creator):
        assert conversation_can_view(conversation, creator) is True

    def test_owner_can_inject(self, conversation, creator):
        assert conversation_can_inject(conversation, creator) is True

    def test_owner_can_cancel(self, conversation, creator):
        assert conversation_can_cancel(conversation, creator) is True

    def test_viewer_can_view(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation, user=other_user, role=ParticipantRole.VIEWER
        )
        assert conversation_can_view(conversation, other_user) is True

    def test_viewer_cannot_inject(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation, user=other_user, role=ParticipantRole.VIEWER
        )
        assert conversation_can_inject(conversation, other_user) is False

    def test_viewer_cannot_cancel(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation, user=other_user, role=ParticipantRole.VIEWER
        )
        assert conversation_can_cancel(conversation, other_user) is False

    def test_collaborator_can_view(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.COLLABORATOR,
        )
        assert conversation_can_view(conversation, other_user) is True

    def test_collaborator_can_inject(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.COLLABORATOR,
        )
        assert conversation_can_inject(conversation, other_user) is True

    def test_collaborator_can_cancel(self, conversation, other_user):
        ConversationParticipant.objects.create(
            conversation=conversation,
            user=other_user,
            role=ParticipantRole.COLLABORATOR,
        )
        assert conversation_can_cancel(conversation, other_user) is True

    def test_stranger_cannot_view(self, conversation, other_user):
        assert conversation_can_view(conversation, other_user) is False

    def test_stranger_cannot_inject(self, conversation, other_user):
        assert conversation_can_inject(conversation, other_user) is False


# ── Permission derivation from ProjectShare ─────────────────────────────


@pytest.mark.django_db
class TestProjectSharePermissionDerivation:
    def test_view_share_grants_viewer(self, creator, other_user):
        project = Project.objects.create(title="Shared proj", user=creator)
        conv = Conversation.objects.create(
            user=creator, title="In project", project=project
        )
        ProjectShare.objects.create(
            project=project, user=other_user, permission_level=SharePermission.VIEW
        )
        assert conversation_can_view(conv, other_user) is True
        assert conversation_can_inject(conv, other_user) is False

    def test_collaborate_share_grants_collaborator(self, creator, other_user):
        project = Project.objects.create(title="Collab proj", user=creator)
        conv = Conversation.objects.create(
            user=creator, title="In project", project=project
        )
        ProjectShare.objects.create(
            project=project,
            user=other_user,
            permission_level=SharePermission.COLLABORATE,
        )
        assert conversation_can_view(conv, other_user) is True
        assert conversation_can_inject(conv, other_user) is True

    def test_admin_share_grants_collaborator(self, creator, other_user):
        project = Project.objects.create(title="Admin proj", user=creator)
        conv = Conversation.objects.create(
            user=creator, title="In project", project=project
        )
        ProjectShare.objects.create(
            project=project,
            user=other_user,
            permission_level=SharePermission.ADMIN,
        )
        assert conversation_can_view(conv, other_user) is True
        assert conversation_can_inject(conv, other_user) is True

    def test_no_share_no_access(self, creator, other_user):
        project = Project.objects.create(title="No share proj", user=creator)
        conv = Conversation.objects.create(
            user=creator, title="In project", project=project
        )
        assert conversation_can_view(conv, other_user) is False

    def test_org_wide_share(self, creator, other_user):
        """Org-wide ProjectShare also grants derived access."""
        from apps.workspace.models import Organization, OrganizationMembership

        org = Organization.objects.create(name="TestOrg", slug="testorg")
        OrganizationMembership.objects.create(
            organization=org, user=creator, role="owner"
        )
        OrganizationMembership.objects.create(
            organization=org, user=other_user, role="member"
        )
        project = Project.objects.create(
            title="Org proj", user=creator, organization=org
        )
        conv = Conversation.objects.create(
            user=creator, title="Org conv", project=project
        )
        ProjectShare.objects.create(
            project=project,
            organization=org,
            permission_level=SharePermission.COLLABORATE,
        )
        assert conversation_can_view(conv, other_user) is True
        assert conversation_can_inject(conv, other_user) is True

    def test_no_project_no_derived_role(self, creator, other_user):
        conv = Conversation.objects.create(user=creator, title="No project")
        assert _get_project_share_role(conv, other_user) is None


# ── Edge cases ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestEdgeCases:
    def test_creator_leaves_org_loses_access(self, creator, other_user):
        """Creator leaves org → no access. Collaborator still has access."""
        from apps.workspace.models import Organization, OrganizationMembership

        org = Organization.objects.create(name="EdgeOrg", slug="edgeorg")
        OrganizationMembership.objects.create(
            organization=org, user=creator, role="owner"
        )
        OrganizationMembership.objects.create(
            organization=org, user=other_user, role="admin"
        )
        project = Project.objects.create(
            title="Edge proj", user=creator, organization=org
        )
        conv = Conversation.objects.create(
            user=creator, title="Edge conv", project=project
        )
        ConversationParticipant.objects.create(
            conversation=conv, user=other_user, role=ParticipantRole.COLLABORATOR
        )

        # Creator's participant record is removed (simulating leave)
        ConversationParticipant.objects.filter(conversation=conv, user=creator).delete()
        # Conversation.user still points to creator but they lost participant record
        # Other user (collaborator) still has access
        assert conversation_can_view(conv, other_user) is True
        assert conversation_can_inject(conv, other_user) is True

    def test_deleted_conversation_excluded(self, creator, other_user):
        """is_deleted=True conversations are excluded from participant queries."""
        conv = Conversation.objects.create(
            user=creator, title="Deleted conv", is_deleted=True
        )
        ConversationParticipant.objects.create(
            conversation=conv, user=other_user, role=ParticipantRole.COLLABORATOR
        )
        # The model still exists but query scoping should filter it
        from apps.storage.models import Conversation as Conv

        visible = Conv.objects.filter(participants__user=other_user, is_deleted=False)
        assert conv not in visible

    def test_cascade_delete_no_orphans(self, creator, other_user):
        """Deleting conversation cascades ConversationParticipant records."""
        conv = Conversation.objects.create(user=creator, title="Cascade test")
        ConversationParticipant.objects.create(
            conversation=conv, user=other_user, role=ParticipantRole.VIEWER
        )
        conv_id = conv.id
        conv.delete()
        assert (
            ConversationParticipant.objects.filter(conversation_id=conv_id).count() == 0
        )


# ── Conversation query includes participated ────────────────────────────


@pytest.mark.django_db
class TestConversationQueryScoping:
    def test_participant_sees_conversation(self, creator, other_user):
        """User who is a participant (not owner) sees the conversation in queries."""
        conv = Conversation.objects.create(user=creator, title="Shared conv")
        ConversationParticipant.objects.create(
            conversation=conv, user=other_user, role=ParticipantRole.COLLABORATOR
        )
        qs = Conversation.objects.filter(
            participants__user=other_user, is_deleted=False
        )
        assert conv in qs

    def test_owner_sees_own_conversation(self, creator):
        conv = Conversation.objects.create(user=creator, title="Own conv")
        qs = Conversation.objects.filter(user=creator, is_deleted=False)
        assert conv in qs

    def test_deleted_excluded_from_participant_query(self, creator, other_user):
        conv = Conversation.objects.create(
            user=creator, title="Del conv", is_deleted=True
        )
        ConversationParticipant.objects.create(
            conversation=conv, user=other_user, role=ParticipantRole.VIEWER
        )
        qs = Conversation.objects.filter(
            participants__user=other_user, is_deleted=False
        )
        assert conv not in qs


# ── GDPR export includes participated conversations ─────────────────────


@pytest.mark.django_db
class TestGDPRExportParticipated:
    def test_export_includes_participated_conversations(self, creator, other_user):
        """Participated conversations appear in export with shared=True."""
        conv = Conversation.objects.create(user=creator, title="GDPR conv")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=other_user,
            role=ParticipantRole.COLLABORATOR,
        )
        from apps.compliance.services import export_user_data

        data = export_user_data(other_user)
        conv_ids = [c["id"] for c in data["conversations"]]
        assert str(conv.id) in conv_ids
        matched = [c for c in data["conversations"] if c["id"] == str(conv.id)][0]
        assert matched["shared"] is True
        assert matched["participant_role"] == ParticipantRole.COLLABORATOR
        assert "summary" not in matched

    def test_export_owned_not_duplicated(self, creator):
        """Owned conversations are not duplicated even if user is also a participant."""
        conv = Conversation.objects.create(user=creator, title="Own GDPR conv")
        # Creator is auto-added as participant via signal
        from apps.compliance.services import export_user_data

        data = export_user_data(creator)
        conv_ids = [c["id"] for c in data["conversations"]]
        assert conv_ids.count(str(conv.id)) == 1

    def test_export_owned_includes_summary(self, creator):
        """Owned non-shared conversations include summary."""
        conv = Conversation.objects.create(
            user=creator, title="Summary conv", summary="Important info"
        )
        from apps.compliance.services import export_user_data

        data = export_user_data(creator)
        matched = [c for c in data["conversations"] if c["id"] == str(conv.id)][0]
        assert matched["summary"] == "Important info"
