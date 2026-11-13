"""Tests for invitation creation, acceptance, revocation, resend, and edge cases.

Covers:
- Email invitation create (admin+, role hierarchy enforcement)
- Invitation list (admin+)
- Accept invitation (by token, authenticated)
- Info endpoint (public, no auth)
- Revoke invitation (admin+)
- Resend invitation (admin+)
- Edge cases: expired invite, revoked invite, already-member, frozen org, duplicate invite
- AuditLog entries for invitation lifecycle
"""

import json
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Invitation,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_ORG_BASE = "/api/v1/workspace/organizations"
_INV_BASE = "/api/v1/workspace/invitations"


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


def _create_org(name="Test Org"):
    """Create an org + owner membership, return (org, owner, owner_token)."""
    owner, token = _make_user()
    resp = _post(_client(token), f"{_ORG_BASE}/", {"name": name})
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


# ── Create Invitation Tests ─────────────────────────────────────────────────


class TestCreateInvitation:
    def test_owner_creates_invitation(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] == target.email
        assert data["role"] == "member"
        assert data["organization_id"] == str(org.pk)
        assert data["is_active"] is True
        assert Invitation.objects.filter(organization=org, email=target.email).exists()

    def test_admin_creates_invitation(self):
        org, _, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        target, _ = _make_user()
        resp = _post(
            _client(admin_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 201

    def test_member_cannot_create_invitation(self):
        org, _, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        target, _ = _make_user()
        resp = _post(
            _client(member_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "viewer"},
        )
        assert resp.status_code == 401

    def test_admin_cannot_invite_at_own_level(self):
        org, _, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        target, _ = _make_user()
        resp = _post(
            _client(admin_token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "admin"},
        )
        assert resp.status_code == 400
        assert "equal to or higher" in resp.json()["detail"]

    def test_owner_can_invite_admin(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "admin"},
        )
        assert resp.status_code == 201

    def test_invalid_role_rejected(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "owner"},
        )
        assert resp.status_code == 400

    def test_already_member_returns_409(self):
        org, owner, token = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": member.email, "role": "member"},
        )
        assert resp.status_code == 409
        assert "already a member" in resp.json()["detail"]

    def test_duplicate_active_invite_returns_409(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        resp1 = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp1.status_code == 201
        resp2 = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp2.status_code == 409
        assert "active invitation already exists" in resp2.json()["detail"]

    def test_invite_nonexistent_user_still_works(self):
        """Invite an email that doesn't have an account yet."""
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": "newuser@example.com", "role": "member"},
        )
        assert resp.status_code == 201
        assert resp.json()["email"] == "newuser@example.com"

    def test_frozen_org_cannot_invite(self):
        org, owner, token = _create_org()
        org.frozen_at = timezone.now()
        org.save(update_fields=["frozen_at"])
        target, _ = _make_user()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert resp.status_code == 400
        assert "frozen" in resp.json()["detail"].lower()

    def test_creates_audit_log(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert AuditLog.objects.filter(action="invitation_created").exists()

    def test_sends_email(self):
        org, owner, token = _create_org()
        target, _ = _make_user()
        _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitations",
            {"email": target.email, "role": "member"},
        )
        assert len(mail.outbox) == 1
        assert "invited" in mail.outbox[0].subject.lower()
        assert target.email in mail.outbox[0].to


# ── List Invitations Tests ──────────────────────────────────────────────────


class TestListInvitations:
    def test_admin_can_list(self):
        org, _, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        # Create an invitation
        Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=admin,
            expires_at=timezone.now() + timedelta(days=7),
        )
        resp = _client(admin_token).get(f"{_ORG_BASE}/{org.pk}/invitations")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_member_cannot_list(self):
        org, _, _ = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _client(member_token).get(f"{_ORG_BASE}/{org.pk}/invitations")
        assert resp.status_code == 401

    def test_only_active_invitations_listed(self):
        org, owner, token = _create_org()
        Invitation.objects.create(
            organization=org,
            email="active@example.com",
            role="member",
            invited_by=owner,
            is_active=True,
        )
        Invitation.objects.create(
            organization=org,
            email="revoked@example.com",
            role="member",
            invited_by=owner,
            is_active=False,
        )
        resp = _client(token).get(f"{_ORG_BASE}/{org.pk}/invitations")
        assert resp.status_code == 200
        emails = [inv["email"] for inv in resp.json()]
        assert "active@example.com" in emails
        assert "revoked@example.com" not in emails


# ── Invitation Info Tests ────────────────────────────────────────────────────


class TestInvitationInfo:
    def test_get_info_no_auth(self):
        """Info endpoint doesn't require auth."""
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
        )
        # Use unauthenticated client
        resp = Client().get(f"{_INV_BASE}/{inv.token}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_name"] == org.name
        assert data["role"] == "member"

    def test_expired_invite_returns_410(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        resp = Client().get(f"{_INV_BASE}/{inv.token}")
        assert resp.status_code == 410
        assert "expired" in resp.json()["detail"].lower()

    def test_revoked_invite_returns_410(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            is_active=False,
        )
        resp = Client().get(f"{_INV_BASE}/{inv.token}")
        assert resp.status_code == 410
        assert "revoked" in resp.json()["detail"].lower()

    def test_nonexistent_token_returns_404(self):
        resp = Client().get(f"{_INV_BASE}/{uuid.uuid4()}")
        assert resp.status_code == 404


# ── Accept Invitation Tests ─────────────────────────────────────────────────


class TestAcceptInvitation:
    def test_accept_as_existing_user(self):
        org, owner, owner_token = _create_org()
        target, target_token = _make_user()
        inv = Invitation.objects.create(
            organization=org,
            email=target.email,
            role="member",
            invited_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
            max_uses=1,
        )
        resp = _post(
            _client(target_token),
            f"{_INV_BASE}/{inv.token}/accept",
            {},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["organization_name"] == org.name
        assert data["role"] == "member"
        assert org.has_member(target)

    def test_accept_increments_use_count(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            max_uses=5,
        )
        target, target_token = _make_user()
        _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        inv.refresh_from_db()
        assert inv.use_count == 1

    def test_accept_expired_invite_rejected(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        target, target_token = _make_user()
        resp = _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 410

    def test_accept_revoked_invite_rejected(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            is_active=False,
        )
        target, target_token = _make_user()
        resp = _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 410

    def test_accept_max_uses_exhausted(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            max_uses=1,
            use_count=1,
        )
        target, target_token = _make_user()
        resp = _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 410
        assert "usage limit" in resp.json()["detail"].lower()

    def test_already_member_returns_success(self):
        """Edge: user already a member clicks invite link -> return success."""
        org, owner, owner_token = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        inv = Invitation.objects.create(
            organization=org,
            email=member.email,
            role="member",
            invited_by=owner,
        )
        resp = _post(_client(member_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["message"] == "Already a member."

    def test_accept_creates_audit_log(self):
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            max_uses=1,
        )
        target, target_token = _make_user()
        _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert AuditLog.objects.filter(action="invitation_accepted").exists()

    def test_accept_by_different_email_user(self):
        """Edge: invite for email X, user with email Y accepts via token — should work."""
        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="original@example.com",
            role="member",
            invited_by=owner,
            max_uses=1,
        )
        # Different user accepts (token-based, not email-based)
        different_user, diff_token = _make_user()
        resp = _post(_client(diff_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 200
        assert org.has_member(different_user)

    def test_accept_enables_enterprise_mode(self):
        """Accepting invitation auto-enables enterprise mode."""
        from apps.workspace.models import EnterpriseConfig

        org, owner, _ = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            max_uses=1,
        )
        target, target_token = _make_user()
        _post(_client(target_token), f"{_INV_BASE}/{inv.token}/accept", {})
        config = EnterpriseConfig.objects.get(user=target)
        assert config.enabled is True


# ── Revoke Invitation Tests ─────────────────────────────────────────────────


class TestRevokeInvitation:
    def test_admin_revokes_invitation(self):
        org, _, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=admin,
        )
        resp = _client(admin_token).delete(
            f"{_INV_BASE}/{inv.pk}/revoke",
            content_type="application/json",
        )
        assert resp.status_code == 200
        inv.refresh_from_db()
        assert inv.is_active is False

    def test_member_cannot_revoke(self):
        org, _, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
        )
        resp = _client(member_token).delete(
            f"{_INV_BASE}/{inv.pk}/revoke",
            content_type="application/json",
        )
        assert resp.status_code == 401

    def test_revoke_already_revoked(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            is_active=False,
        )
        resp = _client(token).delete(
            f"{_INV_BASE}/{inv.pk}/revoke",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_revoke_creates_audit_log(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
        )
        _client(token).delete(
            f"{_INV_BASE}/{inv.pk}/revoke",
            content_type="application/json",
        )
        assert AuditLog.objects.filter(action="invitation_revoked").exists()


# ── Resend Invitation Tests ─────────────────────────────────────────────────


class TestResendInvitation:
    def test_resend_sends_email(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
        )
        mail.outbox.clear()
        resp = _post(
            _client(token),
            f"{_INV_BASE}/{inv.pk}/resend",
            {},
        )
        assert resp.status_code == 200
        assert len(mail.outbox) == 1
        assert "test@example.com" in mail.outbox[0].to

    def test_cannot_resend_revoked(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            is_active=False,
        )
        resp = _post(_client(token), f"{_INV_BASE}/{inv.pk}/resend", {})
        assert resp.status_code == 400

    def test_cannot_resend_expired(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        resp = _post(_client(token), f"{_INV_BASE}/{inv.pk}/resend", {})
        assert resp.status_code == 400

    def test_member_cannot_resend(self):
        org, owner, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        inv = Invitation.objects.create(
            organization=org,
            email="test@example.com",
            role="member",
            invited_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
        )
        resp = _post(_client(member_token), f"{_INV_BASE}/{inv.pk}/resend", {})
        assert resp.status_code == 401


# ── Link Invitation Tests ─────────────────────────────────────────────────


class TestCreateLinkInvitation:
    def test_owner_creates_link_invitation(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["email"] is None
        assert data["role"] == "member"
        assert data["max_uses"] is None
        assert data["use_count"] == 0
        assert data["is_active"] is True
        assert data["expires_at"] is not None

    def test_link_with_max_uses(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "viewer", "expiry": "30d", "max_uses": 10},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["max_uses"] == 10

    def test_link_never_expires(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "never"},
        )
        assert resp.status_code == 201
        assert resp.json()["expires_at"] is None

    def test_invalid_expiry_rejected(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "99d"},
        )
        assert resp.status_code == 400
        assert "Invalid expiry" in resp.json()["detail"]

    def test_invalid_max_uses_rejected(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d", "max_uses": 0},
        )
        assert resp.status_code == 400
        assert "max_uses" in resp.json()["detail"]

    def test_member_cannot_create_link(self):
        org, _, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(
            _client(member_token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "viewer", "expiry": "7d"},
        )
        assert resp.status_code == 401

    def test_admin_cannot_create_link_at_own_level(self):
        org, _, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(
            _client(admin_token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "admin", "expiry": "7d"},
        )
        assert resp.status_code == 400
        assert "equal to or higher" in resp.json()["detail"]

    def test_frozen_org_cannot_create_link(self):
        org, owner, token = _create_org()
        org.frozen_at = timezone.now()
        org.save()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d"},
        )
        assert resp.status_code == 400
        assert "frozen" in resp.json()["detail"].lower()

    def test_link_invite_shows_in_list(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d"},
        )
        resp = _client(token).get(f"{_ORG_BASE}/{org.pk}/invitations")
        assert resp.status_code == 200
        links = [inv for inv in resp.json() if inv["email"] is None]
        assert len(links) == 1

    def test_link_invite_accept_by_different_user(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d", "max_uses": 5},
        )
        inv_token = resp.json()["token"]

        user1, user1_token = _make_user()
        accept1 = _post(_client(user1_token), f"{_INV_BASE}/{inv_token}/accept", {})
        assert accept1.status_code == 200
        assert accept1.json()["success"] is True

        user2, user2_token = _make_user()
        accept2 = _post(_client(user2_token), f"{_INV_BASE}/{inv_token}/accept", {})
        assert accept2.status_code == 200
        assert accept2.json()["success"] is True

        inv = Invitation.objects.get(token=inv_token)
        assert inv.use_count == 2

    def test_link_invite_max_uses_enforced(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d", "max_uses": 1},
        )
        inv_token = resp.json()["token"]

        user1, user1_token = _make_user()
        accept1 = _post(_client(user1_token), f"{_INV_BASE}/{inv_token}/accept", {})
        assert accept1.status_code == 200

        user2, user2_token = _make_user()
        accept2 = _post(_client(user2_token), f"{_INV_BASE}/{inv_token}/accept", {})
        assert accept2.status_code == 410
        assert "usage limit" in accept2.json()["detail"]

    def test_link_invite_expiry_enforced(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "1d"},
        )
        inv_token = resp.json()["token"]

        # Manually expire the invitation
        inv = Invitation.objects.get(token=inv_token)
        inv.expires_at = timezone.now() - timedelta(hours=1)
        inv.save()

        user, user_token = _make_user()
        accept = _post(_client(user_token), f"{_INV_BASE}/{inv_token}/accept", {})
        assert accept.status_code == 410
        assert "expired" in accept.json()["detail"]

    def test_link_invite_creates_audit_log(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_ORG_BASE}/{org.pk}/invitation-links",
            {"role": "member", "expiry": "7d"},
        )
        assert resp.status_code == 201
        assert AuditLog.objects.filter(action="invitation_link_created").exists()


# ── Rate Limiting Tests ────────────────────────────────────────────────────


class TestAcceptRateLimit:
    def test_rate_limit_after_10_accepts(self):
        org, owner, token = _create_org()
        inv = Invitation.objects.create(
            organization=org,
            role="member",
            invited_by=owner,
            max_uses=None,
        )

        # Pre-fill the invite-accept rate limit cache to simulate 10 prior accepts
        client_ip = "127.0.0.1"
        rate_key = f"invite_accept:{client_ip}"
        cache.set(rate_key, 10, timeout=60)

        user, user_token = _make_user()
        resp = _post(_client(user_token), f"{_INV_BASE}/{inv.token}/accept", {})
        assert resp.status_code == 429
        assert "Too many" in resp.json()["detail"]
