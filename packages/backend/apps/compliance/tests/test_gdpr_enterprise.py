"""Tests for GDPR x enterprise — org-aware deletion, export scoping, anonymization."""

import json

import pytest

from apps.billing.models import (
    CreditHold,
    CreditWallet,
    SubscriptionPlan,
    UserSubscription,
)
from apps.compliance.models import ConsentRecord, ConsentType
from apps.compliance.services import (
    OrgOwnerDeletionError,
    delete_user_account,
    export_user_data,
)
from apps.spaces.models import Project
from apps.storage.models import AgentRun, Conversation
from apps.users.models import User
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_org(owner, name="Test Org"):
    """Create an org with an owner membership."""
    org = Organization.objects.create(name=name)
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    return org


def _add_member(org, user, role=OrganizationRole.MEMBER):
    """Add a user as a member of an org."""
    return OrganizationMembership.objects.create(organization=org, user=user, role=role)


def _make_shared_conversation(user, title="Shared Chat"):
    """Create a conversation marked as shared."""
    return Conversation.objects.create(
        user=user, title=title, summary="Some summary", metadata={"shared": True}
    )


def _make_private_conversation(user, title="Private Chat"):
    """Create a regular private conversation."""
    return Conversation.objects.create(user=user, title=title, summary="Private stuff")


def _make_active_run_with_credits(user, conv, status="running"):
    """Create an active agent run with a credit hold."""
    run = AgentRun.objects.create(
        conversation=conv, user=user, task="running task", status=status
    )
    # Create billing infrastructure
    plan, _ = SubscriptionPlan.objects.get_or_create(
        tier="premium",
        defaults={
            "name": "Pro",
            "price": 20,
            "features": {"weekly_tasks": 100},
            "monthly_credits": 1000,
        },
    )
    sub, _ = UserSubscription.objects.get_or_create(
        user=user, defaults={"plan": plan, "status": "active"}
    )
    wallet = CreditWallet.objects.get(user=user)
    hold = CreditHold.objects.create(
        wallet=wallet,
        run=run,
        amount_reserved=100,
        amount_consumed=50,
        status="active",
    )
    return run, hold, wallet


# ── Deletion: Org Owner Blocked ─────────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAsOrgOwner:
    def test_deletion_blocked_when_user_owns_org(self):
        """Org owners must transfer ownership before deletion."""
        user = UserFactory()
        org = _make_org(user, "My Company")

        with pytest.raises(OrgOwnerDeletionError) as exc_info:
            delete_user_account(user)

        assert len(exc_info.value.owned_orgs) == 1
        assert exc_info.value.owned_orgs[0]["name"] == "My Company"
        # User should still exist
        assert User.objects.filter(id=user.id).exists()

    def test_deletion_blocked_lists_all_owned_orgs(self):
        """Error should list all orgs where user is owner."""
        user = UserFactory()
        _make_org(user, "Org Alpha")
        _make_org(user, "Org Beta")

        with pytest.raises(OrgOwnerDeletionError) as exc_info:
            delete_user_account(user)

        names = {o["name"] for o in exc_info.value.owned_orgs}
        assert names == {"Org Alpha", "Org Beta"}

    def test_deletion_blocked_does_not_modify_data(self):
        """Failed deletion should not remove any memberships or conversations."""
        user = UserFactory()
        org = _make_org(user, "My Org")
        conv = _make_private_conversation(user)

        with pytest.raises(OrgOwnerDeletionError):
            delete_user_account(user)

        assert OrganizationMembership.objects.filter(user=user).count() == 1
        assert Conversation.objects.filter(id=conv.id).exists()


# ── Deletion: Org Member (Non-Owner) ────────────────────────────────────────


@pytest.mark.django_db
class TestDeleteAsOrgMember:
    def test_deletion_succeeds_for_non_owner(self):
        """Non-owner members can delete their account."""
        owner = UserFactory()
        member = UserFactory()
        org = _make_org(owner, "Team Org")
        _add_member(org, member)

        result = delete_user_account(member)

        assert result["deleted"] is True
        assert not User.objects.filter(id=member.id).exists()

    def test_org_memberships_removed_before_deletion(self):
        """All org memberships should be removed during deletion."""
        owner = UserFactory()
        member = UserFactory()
        org1 = _make_org(owner, "Org 1")
        org2 = _make_org(owner, "Org 2")
        _add_member(org1, member)
        _add_member(org2, member, role=OrganizationRole.ADMIN)

        result = delete_user_account(member)

        assert result["org_memberships_removed"] == 2
        assert not OrganizationMembership.objects.filter(user_id=member.id).exists()

    def test_org_survives_member_deletion(self):
        """The org itself should not be deleted when a member leaves."""
        owner = UserFactory()
        member = UserFactory()
        org = _make_org(owner, "Survivor Org")
        _add_member(org, member)

        delete_user_account(member)

        assert Organization.objects.filter(id=org.id).exists()
        assert org.memberships.count() == 1  # Only the owner remains


# ── Deletion: Shared Conversation Anonymization ─────────────────────────────


@pytest.mark.django_db
class TestDeleteSharedConversationAnonymization:
    def test_shared_conversations_anonymized_not_deleted(self):
        """Shared conversations should be anonymized, not deleted."""
        user = UserFactory()
        shared_conv = _make_shared_conversation(user, "My Shared Chat")
        conv_id = shared_conv.id

        result = delete_user_account(user)

        assert result["shared_conversations_anonymized"] == 1
        # Conversation should still exist
        conv = Conversation.objects.get(id=conv_id)
        assert conv.title == "[Deleted User]"
        assert conv.summary == ""
        assert conv.user is None

    def test_private_conversations_still_deleted(self):
        """Private (non-shared) conversations should still be CASCADE deleted."""
        user = UserFactory()
        private_conv = _make_private_conversation(user)
        conv_id = private_conv.id

        result = delete_user_account(user)

        assert result["conversations_deleted"] >= 0
        assert not Conversation.objects.filter(id=conv_id).exists()

    def test_mixed_shared_and_private_conversations(self):
        """Shared conversations survive; private ones are deleted."""
        user = UserFactory()
        shared = _make_shared_conversation(user, "Shared")
        private = _make_private_conversation(user, "Private")

        result = delete_user_account(user)

        assert result["shared_conversations_anonymized"] == 1
        assert Conversation.objects.filter(id=shared.id).exists()
        assert not Conversation.objects.filter(id=private.id).exists()

    def test_shared_conversation_metadata_preserved(self):
        """The shared flag should remain in metadata after anonymization."""
        user = UserFactory()
        conv = _make_shared_conversation(user)
        conv_id = conv.id

        delete_user_account(user)

        conv = Conversation.objects.get(id=conv_id)
        assert conv.metadata.get("shared") is True


# ── Deletion: Active Runs + Credit Refund ───────────────────────────────────


@pytest.mark.django_db
class TestDeleteActiveRunsCreditRefund:
    def test_active_runs_cancelled_and_credits_refunded(self):
        """Active runs should be cancelled and their credit holds refunded."""
        user = UserFactory()
        conv = _make_private_conversation(user)
        run, hold, wallet = _make_active_run_with_credits(user, conv)

        result = delete_user_account(user)

        assert result["agent_runs_cancelled"] == 1
        assert result["credits_refunded"] == 50  # amount_consumed

    def test_multiple_active_runs_all_cancelled(self):
        """All active runs across conversations should be cancelled."""
        user = UserFactory()
        conv1 = _make_private_conversation(user, "Chat 1")
        conv2 = _make_private_conversation(user, "Chat 2")
        AgentRun.objects.create(
            conversation=conv1, user=user, task="task1", status="running"
        )
        AgentRun.objects.create(
            conversation=conv2, user=user, task="task2", status="provisioning"
        )

        result = delete_user_account(user)

        assert result["agent_runs_cancelled"] == 2

    def test_completed_runs_not_cancelled(self):
        """Completed runs should not be re-cancelled."""
        user = UserFactory()
        conv = _make_private_conversation(user)
        AgentRun.objects.create(
            conversation=conv, user=user, task="done", status="completed"
        )

        result = delete_user_account(user)

        assert result["agent_runs_cancelled"] == 0

    def test_active_runs_in_shared_projects_cancelled(self):
        """Active runs in org-scoped projects should also be cancelled."""
        owner = UserFactory()
        member = UserFactory()
        org = _make_org(owner)
        _add_member(org, member)

        project = Project.objects.create(
            title="Org Project", user=member, organization=org
        )
        conv = Conversation.objects.create(
            user=member, title="Org Chat", project=project
        )
        run = AgentRun.objects.create(
            conversation=conv, user=member, task="org task", status="running"
        )

        result = delete_user_account(member)

        assert result["agent_runs_cancelled"] == 1


# ── Export: Org Membership Scoping ──────────────────────────────────────────


@pytest.mark.django_db
class TestExportOrgScoping:
    def test_export_includes_org_memberships(self):
        """Export should include all orgs the user belongs to."""
        user = UserFactory()
        owner = UserFactory()
        org = _make_org(owner, "Export Org")
        _add_member(org, user, role=OrganizationRole.ADMIN)

        data = export_user_data(user)

        assert "organization_memberships" in data
        assert len(data["organization_memberships"]) == 1
        m = data["organization_memberships"][0]
        assert m["org_name"] == "Export Org"
        assert m["role"] == "admin"
        assert "joined_at" in m

    def test_export_includes_multiple_orgs(self):
        """Export should list all orgs the user is a member of."""
        user = UserFactory()
        owner = UserFactory()
        org1 = _make_org(owner, "Org A")
        org2 = _make_org(owner, "Org B")
        _add_member(org1, user)
        _add_member(org2, user, role=OrganizationRole.VIEWER)

        data = export_user_data(user)

        assert len(data["organization_memberships"]) == 2
        names = {m["org_name"] for m in data["organization_memberships"]}
        assert names == {"Org A", "Org B"}

    def test_export_org_memberships_empty_for_no_orgs(self):
        """Users not in any org should have an empty list."""
        user = UserFactory()

        data = export_user_data(user)

        assert data["organization_memberships"] == []

    def test_export_does_not_include_other_members_data(self):
        """Export should not include data about other org members."""
        user = UserFactory()
        other = UserFactory()
        owner = UserFactory()
        org = _make_org(owner, "Shared Org")
        _add_member(org, user)
        _add_member(org, other)

        data = export_user_data(user)

        # Only the user's own membership should appear
        assert len(data["organization_memberships"]) == 1
        assert data["organization_memberships"][0]["org_name"] == "Shared Org"


# ── Export: Shared Conversation Scoping ─────────────────────────────────────


@pytest.mark.django_db
class TestExportSharedConversationScoping:
    def test_shared_conversations_marked_in_export(self):
        """Shared conversations should be flagged and exclude summary."""
        user = UserFactory()
        _make_shared_conversation(user, "My Shared")

        data = export_user_data(user)

        shared_convos = [c for c in data["conversations"] if c.get("shared")]
        assert len(shared_convos) == 1
        assert shared_convos[0]["title"] == "My Shared"
        assert "summary" not in shared_convos[0]

    def test_private_conversations_include_summary(self):
        """Private conversations should include full summary."""
        user = UserFactory()
        _make_private_conversation(user, "My Private")

        data = export_user_data(user)

        private_convos = [c for c in data["conversations"] if not c.get("shared")]
        assert len(private_convos) == 1
        assert "summary" in private_convos[0]
        assert private_convos[0]["summary"] == "Private stuff"

    def test_export_includes_owned_projects(self):
        """Export should include projects the user owns."""
        user = UserFactory()
        Project.objects.create(title="My Project", user=user)

        data = export_user_data(user)

        assert len(data["projects"]) == 1
        assert data["projects"][0]["title"] == "My Project"

    def test_export_includes_consent_records(self):
        """Export should include the user's consent records."""
        user = UserFactory()
        ConsentRecord.objects.create(
            user=user,
            user_email=user.email,
            consent_type=ConsentType.ANALYTICS,
            version="1.0",
            action="granted",
        )

        data = export_user_data(user)

        assert len(data["consent_records"]) == 1
        assert data["consent_records"][0]["consent_type"] == "analytics"


# ── API: 409 on Org Owner Deletion ──────────────────────────────────────────


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def _authed_request(rf, method, path, user, body=None, **kwargs):
    """Build a request and attach the auth user (simulates NinjaAuthAdapter)."""
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
    request.request_id = "test-req-id"
    return request


@pytest.mark.django_db
class TestGdprDeleteAPI:
    def test_delete_returns_409_for_org_owner(self, rf):
        """API should return 409 with org list when user owns orgs."""
        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        user = UserFactory()
        _make_org(user, "Blocked Org")

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            user,
            body={"confirm": True, "reason": "leaving"},
        )
        body = DeleteAccountRequest(confirm=True, reason="leaving")
        status, response = gdpr_delete(request, body)

        assert status == 409
        assert "Transfer org ownership" in response["detail"]
        assert len(response["owned_orgs"]) == 1
        assert response["owned_orgs"][0]["name"] == "Blocked Org"
        # User should still exist
        assert User.objects.filter(id=user.id).exists()

    def test_delete_succeeds_for_non_owner_member(self, rf):
        """API should return 200 for members who don't own orgs."""
        from apps.compliance.api import DeleteAccountRequest, gdpr_delete

        owner = UserFactory()
        member = UserFactory()
        org = _make_org(owner)
        _add_member(org, member)

        request = _authed_request(
            rf,
            "delete",
            "/api/v1/compliance/users/me",
            member,
            body={"confirm": True},
        )
        body = DeleteAccountRequest(confirm=True)
        status, response = gdpr_delete(request, body)

        assert status == 200
        assert response["success"] is True
