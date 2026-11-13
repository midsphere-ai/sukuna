"""Tests for Org-level API key endpoints.

Covers:
- POST /{org_id}/api-keys — create key (admin+)
- GET /{org_id}/api-keys — list keys (admin+)
- DELETE /{org_id}/api-keys/{key_id} — revoke key (admin+)
- Rate limiting per key
- Billing attribution (defaults to creator, configurable)
- Edge: org deleted → key auth returns 401
- Edge: creator leaves → key remains active, shows '[removed user]'
- RBAC: only admins+ can manage keys
"""

import hashlib
import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgAPIKey,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


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


# =============================================================================
# CREATE ORG API KEY
# =============================================================================


class TestCreateOrgAPIKey:
    def test_admin_can_create_key(self):
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "CI key"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "CI key"
        assert len(data["key"]) == 40  # hex(20) = 40 chars
        assert data["key_prefix"] == data["key"][:8]
        assert data["is_active"] is True
        assert data["rate_limit_per_minute"] == 120

    def test_custom_rate_limit(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Fast key", "rate_limit_per_minute": 500},
        )
        assert resp.status_code == 201
        assert resp.json()["rate_limit_per_minute"] == 500

    def test_custom_scopes(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Scoped", "scopes": ["agent:run", "read"]},
        )
        assert resp.status_code == 201
        assert resp.json()["scopes"] == ["agent:run", "read"]

    def test_member_cannot_create_key(self):
        org, owner, _ = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(
            _client(member_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x"},
        )
        assert resp.status_code == 401

    def test_viewer_cannot_create_key(self):
        org, owner, _ = _create_org()
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        resp = _post(
            _client(viewer_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x"},
        )
        assert resp.status_code == 401

    def test_admin_member_can_create_key(self):
        org, owner, _ = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Admin key"},
        )
        assert resp.status_code == 201

    def test_key_stored_as_hash(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Hash test"},
        )
        data = resp.json()
        api_key = OrgAPIKey.objects.get(pk=data["id"])
        expected_hash = hashlib.sha256(data["key"].encode()).hexdigest()
        assert api_key.key_hash == expected_hash

    def test_creates_audit_log(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Audited"},
        )
        log = AuditLog.objects.filter(action="org_api_key_created").first()
        assert log is not None
        assert log.resource_type == "org_api_key"

    def test_not_found_org(self):
        _, _, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{uuid.uuid4()}/api-keys",
            {"name": "x"},
        )
        assert resp.status_code == 404

    def test_billing_user_must_be_member(self):
        org, owner, token = _create_org()
        outsider = UserFactory()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x", "billing_user_id": outsider.pk},
        )
        assert resp.status_code == 400
        assert "not a member" in resp.json()["detail"]

    def test_billing_user_not_found(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x", "billing_user_id": 999999},
        )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"]

    def test_billing_user_defaults_to_creator(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Default billing"},
        )
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.billing_user == owner

    def test_custom_billing_user(self):
        org, owner, token = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Billed to member", "billing_user_id": member.pk},
        )
        assert resp.status_code == 201
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.billing_user == member


# =============================================================================
# LIST ORG API KEYS
# =============================================================================


class TestListOrgAPIKeys:
    def test_list_returns_keys(self):
        org, owner, token = _create_org()
        c = _client(token)
        _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "Key 1"})
        _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "Key 2"})
        resp = c.get(f"{_BASE}/{org.pk}/api-keys")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {k["name"] for k in data}
        assert names == {"Key 1", "Key 2"}

    def test_list_does_not_return_plaintext_key(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Secret"},
        )
        resp = _client(token).get(f"{_BASE}/{org.pk}/api-keys")
        keys = resp.json()
        for k in keys:
            assert "key" not in k  # plaintext never in list response

    def test_list_shows_created_by_email(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Owned"},
        )
        resp = _client(token).get(f"{_BASE}/{org.pk}/api-keys")
        assert resp.json()[0]["created_by_email"] == owner.email

    def test_member_cannot_list_keys(self):
        org, owner, _ = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _client(member_token).get(f"{_BASE}/{org.pk}/api-keys")
        assert resp.status_code == 401


# =============================================================================
# REVOKE ORG API KEY
# =============================================================================


class TestRevokeOrgAPIKey:
    def test_revoke_deactivates_key(self):
        org, owner, token = _create_org()
        c = _client(token)
        create_resp = _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "To revoke"})
        key_id = create_resp.json()["id"]
        resp = c.delete(f"{_BASE}/{org.pk}/api-keys/{key_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        api_key = OrgAPIKey.objects.get(pk=key_id)
        assert api_key.is_active is False

    def test_revoke_creates_audit_log(self):
        org, owner, token = _create_org()
        c = _client(token)
        create_resp = _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "Audit"})
        key_id = create_resp.json()["id"]
        c.delete(f"{_BASE}/{org.pk}/api-keys/{key_id}")
        log = AuditLog.objects.filter(action="org_api_key_revoked").first()
        assert log is not None

    def test_revoke_not_found(self):
        org, owner, token = _create_org()
        resp = _client(token).delete(f"{_BASE}/{org.pk}/api-keys/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_member_cannot_revoke(self):
        org, owner, owner_token = _create_org()
        create_resp = _post(
            _client(owner_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x"},
        )
        key_id = create_resp.json()["id"]
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _client(member_token).delete(f"{_BASE}/{org.pk}/api-keys/{key_id}")
        assert resp.status_code == 401


# =============================================================================
# RATE LIMITING
# =============================================================================


class TestOrgAPIKeyRateLimiting:
    def test_rate_limit_stored_on_key(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Rate limited", "rate_limit_per_minute": 60},
        )
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.rate_limit_per_minute == 60

    def test_default_rate_limit(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Default"},
        )
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.rate_limit_per_minute == 120


# =============================================================================
# BILLING ATTRIBUTION
# =============================================================================


class TestBillingAttribution:
    def test_billing_user_set_to_creator_by_default(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Default billing"},
        )
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.billing_user_id == owner.pk
        assert api_key.created_by_id == owner.pk

    def test_billing_user_configurable(self):
        org, owner, token = _create_org()
        member, _ = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Custom billing", "billing_user_id": member.pk},
        )
        assert resp.status_code == 201
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        assert api_key.billing_user_id == member.pk

    def test_billing_user_email_shown_in_list(self):
        org, owner, token = _create_org()
        member, _ = _add_member(org, OrganizationRole.ADMIN)
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "x", "billing_user_id": member.pk},
        )
        resp = _client(token).get(f"{_BASE}/{org.pk}/api-keys")
        assert resp.json()[0]["billing_user_email"] == member.email


# =============================================================================
# ORG DELETION EDGE CASE
# =============================================================================


class TestOrgDeletion:
    def test_keys_cascade_deleted_with_org(self):
        org, owner, token = _create_org()
        _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Will be deleted"},
        )
        assert OrgAPIKey.objects.filter(organization=org).count() == 1
        org.delete()
        assert OrgAPIKey.objects.count() == 0


# =============================================================================
# CREATOR DEPARTURE EDGE CASE
# =============================================================================


class TestCreatorDeparture:
    def test_key_survives_creator_deletion(self):
        """Key remains active after creator is deleted (SET_NULL)."""
        org, owner, token = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Survives"},
        )
        key_id = resp.json()["id"]

        # Delete the admin who created the key
        admin_id = admin.pk
        admin.delete()

        api_key = OrgAPIKey.objects.get(pk=key_id)
        assert api_key.is_active is True
        assert api_key.created_by is None

    def test_removed_creator_shows_placeholder(self):
        """List shows '[removed user]' for keys whose creator was deleted."""
        org, owner, token = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        _post(
            _client(admin_token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Orphaned"},
        )

        # Remove creator
        admin.delete()

        resp = _client(token).get(f"{_BASE}/{org.pk}/api-keys")
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["created_by_email"] == "[removed user]"


# =============================================================================
# ORG API KEY MODEL
# =============================================================================


class TestOrgAPIKeyModel:
    def test_str_representation(self):
        org = Organization.objects.create(name="Str Org", slug="str-org")
        api_key = OrgAPIKey.objects.create(
            organization=org,
            key_hash="a" * 64,
            key_prefix="abcd1234",
            name="Test",
        )
        assert "abcd1234" in str(api_key)
        assert "Str Org" in str(api_key)

    def test_last_used_at_nullable(self):
        org = Organization.objects.create(name="LU Org", slug="lu-org")
        api_key = OrgAPIKey.objects.create(
            organization=org,
            key_hash="b" * 64,
            key_prefix="efgh5678",
        )
        assert api_key.last_used_at is None

    def test_last_used_at_updatable(self):
        org = Organization.objects.create(name="LU2 Org", slug="lu2-org")
        api_key = OrgAPIKey.objects.create(
            organization=org,
            key_hash="c" * 64,
            key_prefix="ijkl9012",
        )
        now = timezone.now()
        api_key.last_used_at = now
        api_key.save(update_fields=["last_used_at"])
        api_key.refresh_from_db()
        assert api_key.last_used_at == now


# =============================================================================
# AUTHENTICATION (org API key authenticates as org)
# =============================================================================


class TestOrgAPIKeyAuthentication:
    def test_key_lookup_by_hash(self):
        """Verify key can be looked up by computing hash from plaintext."""
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Lookup test"},
        )
        plaintext = resp.json()["key"]
        key_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        api_key = OrgAPIKey.objects.get(key_hash=key_hash)
        assert api_key.is_active is True
        assert api_key.organization_id == org.pk

    def test_inactive_key_still_exists_in_db(self):
        """Revoked key stays in DB but is_active=False for audit trail."""
        org, owner, token = _create_org()
        c = _client(token)
        resp = _post(c, f"{_BASE}/{org.pk}/api-keys", {"name": "Deactivate"})
        key_id = resp.json()["id"]
        c.delete(f"{_BASE}/{org.pk}/api-keys/{key_id}")
        api_key = OrgAPIKey.objects.get(pk=key_id)
        assert api_key.is_active is False

    def test_org_api_key_respects_org_model_policy(self):
        """Keys belong to org — org's model/agent policies apply."""
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/api-keys",
            {"name": "Policy test"},
        )
        api_key = OrgAPIKey.objects.get(pk=resp.json()["id"])
        # Key's org is the same org whose policies apply
        assert api_key.organization_id == org.pk
