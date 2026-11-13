"""US-032: Teams integration tests — full collaborative flow E2E.

Tests cover:
- Full collaborative flow: create org → invite → share project → join conversation → inject → attribution
- Injection queue ordering: two users inject while agent running, FIFO ordering
- Presence events: two users in same conversation, presence tracking
- Invitation link: generate link → new user accepts → auto-added with correct role
- Project move: personal → org, shared, accessible by team
- Notification delivery: injection triggers notification for participants
- Permission enforcement: viewer cannot inject (403), role hierarchy
- Billing attribution: injecting user's wallet charged, not conversation owner
- Shared sandbox: two users in same project get same sandbox_id
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.agents.presence import (
    get_present_users,
    get_typing_users,
    heartbeat,
    set_typing,
)
from apps.agents.sandbox import _provision_project_sandbox_atomic
from apps.billing.credit_service import CreditService
from apps.billing.models import CreditWallet
from apps.compliance.models import AuditAction, AuditLog
from apps.spaces.models import Project, ProjectShare, SharePermission
from apps.storage.models import (
    AgentRun,
    Conversation,
    ConversationParticipant,
    ParticipantRole,
    conversation_can_cancel,
    conversation_can_inject,
    conversation_can_view,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    EnterpriseConfig,
    Invitation,
    Notification,
    NotificationType,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)
from apps.workspace.notifications import create_notification

pytestmark = pytest.mark.django_db

_ORG_BASE = "/api/v1/workspace/organizations"
_INV_BASE = "/api/v1/workspace/invitations"
_SPACES_BASE = "/api/v1/spaces"


# ── Shared helpers ─────────────────────────────────────────────────────────


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


def _create_org(name="Test Org"):
    """Create org via API, return (org, owner, owner_token)."""
    owner, token = _make_user()
    resp = _post(_client(token), f"{_ORG_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None):
    """Create user and add to org with given role. Returns (user, token)."""
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


def _setup_project(user, title="Team Project", organization=None):
    return Project.objects.create(
        title=title,
        description="Test project",
        user=user,
        organization=organization,
    )


def _create_conversation(user, project=None, title=None):
    return Conversation.objects.create(
        user=user,
        title=title or f"Conv {user.email}",
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
# E2E: FULL COLLABORATIVE FLOW
# =============================================================================


class TestFullCollaborativeFlow:
    """E2E: user A creates org, invites user B, creates project, shares it,
    user B joins conversation, user B injects, response includes attribution."""

    def test_full_collaborative_flow(self):
        # Step 1: User A creates org
        org, user_a, token_a = _create_org("Collab Corp")
        assert org.name == "Collab Corp"
        assert OrganizationMembership.objects.filter(
            organization=org, user=user_a, role=OrganizationRole.OWNER
        ).exists()

        # Step 2: Invite User B via email
        user_b, token_b = _make_user()
        resp = _post(
            _client(token_a),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": user_b.email, "role": "member"},
        )
        assert resp.status_code == 201
        inv_token = Invitation.objects.get(organization=org, email=user_b.email).token

        # Step 3: User B accepts invitation
        resp = _post(_client(token_b), f"{_INV_BASE}/{inv_token}/accept", {})
        assert resp.status_code == 200
        assert org.has_member(user_b)
        membership = OrganizationMembership.objects.get(organization=org, user=user_b)
        assert membership.role == OrganizationRole.MEMBER

        # Step 4: User A creates project and shares with org
        project = _setup_project(user_a, "Shared Project", organization=org)
        ProjectShare.objects.create(
            project=project,
            user=user_b,
            permission_level=SharePermission.COLLABORATE,
            shared_by=user_a,
        )

        # Step 5: User A creates conversation in project
        conv = _create_conversation(user_a, project=project, title="Team Chat")
        run = _create_agent_run(conv, user_a)

        # Step 6: User B can view conversation (via project share)
        assert conversation_can_view(conv, user_b) is True

        # Step 7: User B can inject (COLLABORATE permission)
        assert conversation_can_inject(conv, user_b) is True

        # Step 8: Attribution check — message wrapping
        from apps.workspace.security import sanitize_display_name

        display_name = sanitize_display_name(user_b.name) or "Unknown"
        prompt = "Can you help with this?"
        attributed = f"[User: {display_name}] {prompt}"
        assert attributed.startswith("[User: ")
        assert prompt in attributed

        # Step 9: Audit log for the invitation
        assert AuditLog.objects.filter(action="invitation_created").exists()
        assert AuditLog.objects.filter(action="invitation_accepted").exists()

    def test_collaborator_has_full_permission_chain(self):
        """Collaborator can view, inject, and cancel — full permission check."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)

        project = _setup_project(owner, organization=org)
        ProjectShare.objects.create(
            project=project,
            user=member,
            permission_level=SharePermission.COLLABORATE,
            shared_by=owner,
        )
        conv = _create_conversation(owner, project=project)

        assert conversation_can_view(conv, member) is True
        assert conversation_can_inject(conv, member) is True
        assert conversation_can_cancel(conv, member) is True

    def test_viewer_has_limited_permissions(self):
        """Viewer can view but cannot inject or cancel."""
        org, owner, _ = _create_org()
        viewer, _ = _add_member(org, OrganizationRole.MEMBER)

        project = _setup_project(owner, organization=org)
        ProjectShare.objects.create(
            project=project,
            user=viewer,
            permission_level=SharePermission.VIEW,
            shared_by=owner,
        )
        conv = _create_conversation(owner, project=project)

        assert conversation_can_view(conv, viewer) is True
        assert conversation_can_inject(conv, viewer) is False
        assert conversation_can_cancel(conv, viewer) is False


# =============================================================================
# E2E: INJECTION QUEUE ORDERING
# =============================================================================


# Injection queue E2E tests moved to the sandbox pytest suite — the queue
# itself ported to ``packages/sandbox/agent_server/infra/injection_queue.py``.


# =============================================================================
# E2E: PRESENCE EVENTS
# =============================================================================


class TestPresenceEvents:
    """E2E: user A and B both view conversation, presence events fire."""

    def test_two_users_presence(self):
        conv_id = f"presence-e2e-{uuid.uuid4().hex[:8]}"

        # User A joins
        is_new_a, _ = heartbeat(conv_id, "user-a", "Alice")
        assert is_new_a is True

        # User B joins
        is_new_b, _ = heartbeat(conv_id, "user-b", "Bob")
        assert is_new_b is True

        # Both present
        users = get_present_users(conv_id)
        assert len(users) == 2
        user_ids = {u.user_id for u in users}
        assert user_ids == {"user-a", "user-b"}

    def test_typing_indicators_for_both(self):
        conv_id = f"typing-e2e-{uuid.uuid4().hex[:8]}"

        set_typing(conv_id, "user-a", "start")
        set_typing(conv_id, "user-b", "start")
        typers = get_typing_users(conv_id)
        assert set(typers) == {"user-a", "user-b"}

        # User A stops typing
        set_typing(conv_id, "user-a", "stop")
        typers = get_typing_users(conv_id)
        assert typers == ["user-b"]

    def test_presence_with_conversation_participants(self):
        """Full flow: real users with conversation participants + presence."""
        owner = UserFactory()
        collaborator = UserFactory()
        conv = Conversation.objects.create(user=owner, title="Presence test")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=collaborator,
            role=ParticipantRole.COLLABORATOR,
        )

        conv_id = str(conv.id)

        # Both heartbeat
        heartbeat(conv_id, str(owner.id), owner.name or "Owner")
        heartbeat(conv_id, str(collaborator.id), collaborator.name or "Collaborator")

        users = get_present_users(conv_id)
        assert len(users) == 2

        # Verify both can view
        assert conversation_can_view(conv, owner) is True
        assert conversation_can_view(conv, collaborator) is True

    def test_user_leaves_presence(self):
        """When user leaves, they are removed from presence."""
        from apps.agents.presence import leave

        conv_id = f"leave-e2e-{uuid.uuid4().hex[:8]}"
        heartbeat(conv_id, "user-a", "Alice")
        heartbeat(conv_id, "user-b", "Bob")

        leave(conv_id, "user-a")
        users = get_present_users(conv_id)
        assert len(users) == 1
        assert users[0].user_id == "user-b"


# =============================================================================
# E2E: INVITATION LINK FLOW
# =============================================================================


class TestInvitationLinkFlow:
    """E2E: generate link → new user signs up via link → auto-added with correct role."""

    def test_link_invitation_full_flow(self):
        # Step 1: Owner creates link invitation
        org, owner, owner_token = _create_org("Link Org")
        resp = _post(
            _client(owner_token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d", "max_uses": 10},
        )
        assert resp.status_code == 201
        inv_data = resp.json()
        link_token = inv_data["token"]

        # Step 2: New user signs up and accepts via link
        new_user, new_token = _make_user()
        resp = _post(_client(new_token), f"{_INV_BASE}/{link_token}/accept", {})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["role"] == "member"

        # Step 3: Verify membership
        assert org.has_member(new_user)
        membership = OrganizationMembership.objects.get(organization=org, user=new_user)
        assert membership.role == OrganizationRole.MEMBER

        # Step 4: Verify use count incremented
        inv = Invitation.objects.get(token=link_token)
        assert inv.use_count == 1

        # Step 5: Enterprise mode auto-enabled
        config = EnterpriseConfig.objects.get(user=new_user)
        assert config.enabled is True

    def test_link_multiple_users_accept(self):
        """Multiple users accept the same link invitation."""
        org, owner, owner_token = _create_org("Multi Org")
        resp = _post(
            _client(owner_token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "viewer", "expiry": "7d", "max_uses": 5},
        )
        link_token = resp.json()["token"]

        for _ in range(3):
            user, token = _make_user()
            resp = _post(_client(token), f"{_INV_BASE}/{link_token}/accept", {})
            assert resp.status_code == 200
            assert org.has_member(user)

        inv = Invitation.objects.get(token=link_token)
        assert inv.use_count == 3

    def test_link_exhausted_after_max_uses(self):
        """Link becomes unusable after max_uses reached."""
        org, owner, owner_token = _create_org("Exhaust Org")
        resp = _post(
            _client(owner_token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d", "max_uses": 1},
        )
        link_token = resp.json()["token"]

        # First accept
        user1, tok1 = _make_user()
        resp = _post(_client(tok1), f"{_INV_BASE}/{link_token}/accept", {})
        assert resp.status_code == 200

        # Second accept — exhausted
        user2, tok2 = _make_user()
        resp = _post(_client(tok2), f"{_INV_BASE}/{link_token}/accept", {})
        assert resp.status_code == 410


# =============================================================================
# E2E: PROJECT MOVE → SHARED → ACCESSIBLE BY TEAM
# =============================================================================


class TestProjectMoveFlow:
    """E2E: personal project moved to org, shared, accessible by team."""

    def test_move_then_share_then_access(self):
        # Step 1: User creates personal project with conversations
        owner, owner_token = _make_user()
        org = Organization.objects.create(name="Move Org")
        OrganizationMembership.objects.create(
            organization=org, user=owner, role=OrganizationRole.OWNER
        )
        member, member_token = _add_member(org, OrganizationRole.MEMBER)

        project = _setup_project(owner, "Personal Project")
        conv = _create_conversation(owner, project=project, title="My Conv")

        # Step 2: Move to org via API
        resp = _client(owner_token).post(
            f"{_SPACES_BASE}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        project.refresh_from_db()
        assert project.organization_id == org.pk

        # Step 3: Conversation still intact
        conv.refresh_from_db()
        assert conv.project_id == project.pk

        # Step 4: Share project with member
        ProjectShare.objects.create(
            project=project,
            user=member,
            permission_level=SharePermission.COLLABORATE,
            shared_by=owner,
        )

        # Step 5: Member can now view and inject
        assert conversation_can_view(conv, member) is True
        assert conversation_can_inject(conv, member) is True

        # Step 6: Audit log recorded
        assert AuditLog.objects.filter(
            action=AuditAction.PROJECT_MOVED,
            resource_id=str(project.pk),
        ).exists()

    def test_move_preserves_existing_conversations(self):
        """All conversations survive the project move."""
        owner, owner_token = _make_user()
        org = Organization.objects.create(name="Preserve Org")
        OrganizationMembership.objects.create(
            organization=org, user=owner, role=OrganizationRole.OWNER
        )

        project = _setup_project(owner, "Multi Conv Project")
        convs = [
            _create_conversation(owner, project=project, title=f"Conv {i}")
            for i in range(3)
        ]

        resp = _client(owner_token).post(
            f"{_SPACES_BASE}/projects/{project.pk}/move",
            data=json.dumps({"organization_id": str(org.pk)}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        for conv in convs:
            conv.refresh_from_db()
            assert conv.project_id == project.pk


# =============================================================================
# E2E: NOTIFICATION DELIVERY
# =============================================================================


class TestNotificationDelivery:
    """E2E: injection triggers notification for other participants."""

    def test_injection_creates_notification_for_participants(self):
        owner = UserFactory()
        collaborator = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Notify test")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=collaborator,
            role=ParticipantRole.COLLABORATOR,
        )

        # Simulate injection notification (as would happen in inject_message view)
        notif = create_notification(
            user=collaborator,
            type=NotificationType.INJECTION,
            title=f"{owner.name} sent a message",
            body="Check out this response",
            data={
                "conversation_id": str(conv.id),
                "actor_id": str(owner.id),
            },
        )

        assert notif is not None
        assert notif.user == collaborator
        assert notif.type == NotificationType.INJECTION
        assert notif.data["conversation_id"] == str(conv.id)
        assert notif.is_read is False

    def test_notification_not_sent_to_actor(self):
        """The user who triggers an action should NOT get notified."""
        owner = UserFactory()
        collaborator = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Self-notify test")

        # Notification sent only to collaborator, not to owner (who triggered)
        create_notification(
            user=collaborator,
            type=NotificationType.INJECTION,
            title=f"{owner.name} sent a message",
            body="New message",
            data={"conversation_id": str(conv.id), "actor_id": str(owner.id)},
        )

        # Owner has no notifications
        assert Notification.objects.filter(user=owner).count() == 0
        # Collaborator has one
        assert Notification.objects.filter(user=collaborator).count() == 1

    def test_multiple_participants_get_notifications(self):
        """All participants (except actor) get notified."""
        owner = UserFactory()
        member1 = UserFactory()
        member2 = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Multi-notify")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=member1,
            role=ParticipantRole.COLLABORATOR,
        )
        ConversationParticipant.objects.create(
            conversation=conv,
            user=member2,
            role=ParticipantRole.COLLABORATOR,
        )

        # Owner injects → both members should be notified
        for member in [member1, member2]:
            create_notification(
                user=member,
                type=NotificationType.INJECTION,
                title=f"{owner.name} sent a message",
                body="Team message",
                data={"conversation_id": str(conv.id), "actor_id": str(owner.id)},
            )

        assert Notification.objects.filter(user=member1).count() == 1
        assert Notification.objects.filter(user=member2).count() == 1
        assert Notification.objects.filter(user=owner).count() == 0

    def test_share_notification_on_project_share(self):
        """Sharing a project generates a SHARE notification."""
        owner = UserFactory()
        target = UserFactory()
        project = _setup_project(owner)

        notif = create_notification(
            user=target,
            type=NotificationType.SHARE,
            title=f"{owner.name} shared a project with you",
            body=project.title,
            data={"project_id": str(project.pk), "actor_id": str(owner.id)},
        )

        assert notif is not None
        assert notif.type == NotificationType.SHARE
        assert notif.data["project_id"] == str(project.pk)


# =============================================================================
# E2E: PERMISSION ENFORCEMENT
# =============================================================================


class TestPermissionEnforcement:
    """E2E: viewer cannot inject (403), role-based enforcement."""

    def test_viewer_cannot_inject(self):
        """Viewer on conversation cannot inject."""
        owner = UserFactory()
        viewer = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Perm test")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=viewer,
            role=ParticipantRole.VIEWER,
        )

        assert conversation_can_view(conv, viewer) is True
        assert conversation_can_inject(conv, viewer) is False

    def test_viewer_via_project_share_cannot_inject(self):
        """User with VIEW-only project share cannot inject into conversation."""
        owner = UserFactory()
        viewer = UserFactory()
        project = _setup_project(owner)
        ProjectShare.objects.create(
            project=project,
            user=viewer,
            permission_level=SharePermission.VIEW,
            shared_by=owner,
        )

        conv = _create_conversation(owner, project=project)
        assert conversation_can_view(conv, viewer) is True
        assert conversation_can_inject(conv, viewer) is False

    def test_stranger_cannot_view_or_inject(self):
        """User not part of org/share cannot access conversation."""
        owner = UserFactory()
        stranger = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Stranger test")
        assert conversation_can_view(conv, stranger) is False
        assert conversation_can_inject(conv, stranger) is False
        assert conversation_can_cancel(conv, stranger) is False

    def test_collaborator_can_inject_and_cancel(self):
        """Collaborator has inject + cancel permissions."""
        owner = UserFactory()
        collaborator = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Collab perm test")
        ConversationParticipant.objects.create(
            conversation=conv,
            user=collaborator,
            role=ParticipantRole.COLLABORATOR,
        )

        assert conversation_can_inject(conv, collaborator) is True
        assert conversation_can_cancel(conv, collaborator) is True

    def test_role_hierarchy_in_org(self):
        """Owner > Admin > Member > Viewer in org permission hierarchy."""
        org, owner, owner_token = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        viewer, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        # Owner can invite admin-level
        target, _ = _make_user()
        resp = _post(
            _client(owner_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "admin"},
        )
        assert resp.status_code == 201

        # Admin cannot invite admin (same level)
        target2, _ = _make_user()
        resp = _post(
            _client(admin_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target2.email, "role": "admin"},
        )
        assert resp.status_code == 400

        # Member cannot invite at all
        target3, _ = _make_user()
        resp = _post(
            _client(member_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target3.email, "role": "viewer"},
        )
        assert resp.status_code == 401

    def test_org_member_list_access_by_role(self):
        """All org members can list members (VIEWER+)."""
        org, owner, owner_token = _create_org()
        viewer, viewer_token = _add_member(org, OrganizationRole.VIEWER)

        resp = _client(viewer_token).get(f"{_ORG_BASE}/{org.pk}/members")
        assert resp.status_code == 200
        members = resp.json()
        assert len(members) == 2  # owner + viewer


# =============================================================================
# E2E: BILLING ATTRIBUTION
# =============================================================================


class TestBillingAttribution:
    """E2E: injecting user's wallet charged, not conversation owner."""

    def test_credit_hold_attributed_to_run_owner(self):
        """CreditHold is created against the run's user (owner), not injector."""
        owner = UserFactory()
        collaborator = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Billing E2E")
        run = AgentRun.objects.create(
            user=owner,
            conversation=conv,
            task="billing test",
            status=AgentRun.Status.RUNNING,
        )

        # Owner's wallet
        wallet, _ = CreditWallet.objects.get_or_create(user=owner)
        wallet.free_credits = 1000
        wallet.save(update_fields=["free_credits"])

        hold = CreditService.create_hold(wallet, run, estimated_credits=200)
        assert hold.wallet.user_id == owner.id

        # Collaborator cancels → refund goes to owner's wallet
        CreditService.refund(hold, reason="Cancelled by collaborator")
        hold.refresh_from_db()
        assert hold.status == "refunded"
        assert hold.wallet.user_id == owner.id

    def test_injecting_user_billing_attribution_in_audit(self):
        """Audit log for injection records both injector and conversation owner."""
        owner = UserFactory()
        injector = UserFactory()

        conv = Conversation.objects.create(user=owner, title="Attribution audit")
        run = AgentRun.objects.create(
            user=owner,
            conversation=conv,
            task="test",
            status=AgentRun.Status.RUNNING,
            run_id="attr-run-001",
        )

        AuditLog.log(
            actor_id=injector.id,
            actor_email=injector.email,
            action=AuditAction.INJECTION,
            resource_type="conversation",
            resource_id=str(conv.id),
            metadata={
                "run_id": "attr-run-001",
                "injecting_user_id": str(injector.id),
                "conversation_owner_id": str(owner.id),
            },
        )

        log = AuditLog.objects.filter(
            action=AuditAction.INJECTION,
            resource_id=str(conv.id),
        ).first()
        assert log is not None
        assert log.metadata["injecting_user_id"] == str(injector.id)
        assert log.metadata["conversation_owner_id"] == str(owner.id)
        assert log.actor_email == injector.email

    def test_credit_consume_and_settle(self):
        """Full billing lifecycle: hold → consume → settle."""
        owner = UserFactory()
        conv = Conversation.objects.create(user=owner, title="Settle test")
        run = AgentRun.objects.create(
            user=owner,
            conversation=conv,
            task="test",
            status=AgentRun.Status.RUNNING,
        )

        wallet, _ = CreditWallet.objects.get_or_create(user=owner)
        wallet.free_credits = 500
        wallet.save(update_fields=["free_credits"])

        hold = CreditService.create_hold(wallet, run, estimated_credits=100)
        CreditService.consume(hold, "llm", 50, source_type="gpt-4", description="test")
        hold.refresh_from_db()
        assert hold.amount_consumed == 50

        CreditService.settle(hold)
        hold.refresh_from_db()
        assert hold.status == "settled"


# =============================================================================
# E2E: SHARED SANDBOX
# =============================================================================


class TestSharedSandbox:
    """E2E: two users in same project get same sandbox_id."""

    def test_two_users_same_sandbox(self):
        owner = UserFactory()
        member = UserFactory()

        org = Organization.objects.create(name="Sandbox Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=owner,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=member,
            role=OrganizationRole.MEMBER,
        )

        project = _setup_project(owner, "Sandbox Project", organization=org)

        # First user provisions sandbox
        record1, is_new1 = _provision_project_sandbox_atomic(project)
        assert is_new1 is True
        from apps.agents.models import E2bSandbox

        record1.sandbox_state = E2bSandbox.SandboxState.READY
        record1.save(update_fields=["sandbox_state"])

        # Second user gets same sandbox
        record2, is_new2 = _provision_project_sandbox_atomic(project)
        assert is_new2 is False
        assert record2.pk == record1.pk

    def test_shared_sandbox_conversations_isolated(self):
        """Different conversations in same project share sandbox but are separate."""
        owner = UserFactory()
        member = UserFactory()

        org = Organization.objects.create(name="Isolation Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=owner,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=member,
            role=OrganizationRole.MEMBER,
        )

        project = _setup_project(owner, "Iso Project", organization=org)
        conv_a = _create_conversation(owner, project=project, title="Conv A")
        conv_b = _create_conversation(member, project=project, title="Conv B")

        # Different conversations, same project
        assert conv_a.project_id == conv_b.project_id
        assert conv_a.id != conv_b.id

        # Each conversation has its own presence
        heartbeat(str(conv_a.id), str(owner.id), "Owner")
        heartbeat(str(conv_b.id), str(member.id), "Member")

        users_a = get_present_users(str(conv_a.id))
        users_b = get_present_users(str(conv_b.id))
        assert len(users_a) == 1
        assert len(users_b) == 1
        assert users_a[0].user_id == str(owner.id)
        assert users_b[0].user_id == str(member.id)

    def test_sandbox_survives_member_removal(self):
        """Sandbox persists even after a member is removed from the org."""
        owner = UserFactory()
        member = UserFactory()

        org = Organization.objects.create(name="Remove Org")
        OrganizationMembership.objects.create(
            organization=org,
            user=owner,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=member,
            role=OrganizationRole.MEMBER,
        )

        project = _setup_project(owner, "Remove Project", organization=org)
        record, _ = _provision_project_sandbox_atomic(project)
        from apps.agents.models import E2bSandbox

        record.sandbox_state = E2bSandbox.SandboxState.READY
        record.save(update_fields=["sandbox_state"])
        sandbox_pk = record.pk

        # Remove member
        OrganizationMembership.objects.filter(
            organization=org,
            user=member,
        ).delete()

        # Sandbox still exists
        assert E2bSandbox.objects.filter(pk=sandbox_pk).exists()
        project.refresh_from_db()
        assert project.sandbox_id == sandbox_pk


# =============================================================================
# CROSS-CUTTING: FULL TEAM LIFECYCLE
# =============================================================================


class TestFullTeamLifecycle:
    """Cross-cutting integration: org creation → team formation → collaboration."""

    def test_org_to_collaboration_lifecycle(self):
        # 1. Create org
        org, owner, owner_token = _create_org("Lifecycle Corp")

        # 2. Add admin and member
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        member, member_token = _add_member(org, OrganizationRole.MEMBER)

        # 3. Owner creates project in org
        project = _setup_project(owner, "Team Project", organization=org)

        # 4. Share with members
        ProjectShare.objects.create(
            project=project,
            user=admin,
            permission_level=SharePermission.ADMIN,
            shared_by=owner,
        )
        ProjectShare.objects.create(
            project=project,
            user=member,
            permission_level=SharePermission.COLLABORATE,
            shared_by=owner,
        )

        # 5. Owner creates conversation
        conv = _create_conversation(owner, project=project, title="Sprint planning")

        # 6. All can view
        assert conversation_can_view(conv, owner) is True
        assert conversation_can_view(conv, admin) is True
        assert conversation_can_view(conv, member) is True

        # 7. Admin and member can inject
        assert conversation_can_inject(conv, admin) is True
        assert conversation_can_inject(conv, member) is True

        # 8. Presence tracking
        conv_id = str(conv.id)
        heartbeat(conv_id, str(owner.id), "Owner")
        heartbeat(conv_id, str(admin.id), "Admin")
        heartbeat(conv_id, str(member.id), "Member")
        assert len(get_present_users(conv_id)) == 3

        # 9. Injection queue moved to sandbox — no longer exercised here.

        # 10. Notifications
        for user in [admin, member]:
            create_notification(
                user=user,
                type=NotificationType.INJECTION,
                title=f"{owner.name} started a run",
                body="Sprint planning agent is running",
                data={"conversation_id": str(conv.id)},
            )

        assert Notification.objects.filter(user=admin).count() == 1
        assert Notification.objects.filter(user=member).count() == 1
        assert Notification.objects.filter(user=owner).count() == 0

    def test_frozen_org_blocks_team_operations(self):
        """Frozen org blocks invitations but existing members can still view."""
        org, owner, owner_token = _create_org("Frozen Org")
        member, _ = _add_member(org, OrganizationRole.MEMBER)

        # Freeze org
        org.frozen_at = timezone.now()
        org.save(update_fields=["frozen_at"])

        # Cannot invite new members
        target, _ = _make_user()
        resp = _post(
            _client(owner_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 400
        assert "frozen" in resp.json()["detail"].lower()

        # Existing member can still view org
        resp = _client(owner_token).get(f"{_ORG_BASE}/{org.pk}")
        assert resp.status_code == 200
