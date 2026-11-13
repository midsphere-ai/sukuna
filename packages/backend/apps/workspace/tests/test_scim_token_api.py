"""Tests for SCIM token management endpoints and SCIM discovery endpoints.

Covers US-013 acceptance criteria:
- Token generate/list/revoke via org_api
- Discovery endpoints (ServiceProviderConfig, Schemas, ResourceTypes)
- Permission enforcement (admin+ required)
- Edge cases: multiple active tokens, IP allowlist, usage tracking
"""

import hashlib
import json
import secrets

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SCIMToken,
)
from apps.workspace.scim_api import (
    _ip_in_cidrs,
    get_resource_types,
    get_schemas,
    get_service_provider_config,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


# ── Fixtures ─────────────────────────────────────────────────────────────


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


def _post(client, path, data=None):
    return client.post(
        path, data=json.dumps(data or {}), content_type="application/json"
    )


def _create_org(name="Token Test Org"):
    """Create an org + owner, return (org, owner_user, owner_token_key)."""
    owner, token_key = _make_user()
    resp = _post(_client(token_key), f"{_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token_key


def _add_member(org, role):
    user, token_key = _make_user()
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user, token_key


def _create_scim_token(org, **kwargs):
    """Create a SCIM token directly in the DB. Returns (plaintext, SCIMToken)."""
    plaintext = secrets.token_hex(20)
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    token = SCIMToken.objects.create(
        organization=org,
        token_hash=token_hash,
        prefix=plaintext[:8],
        **kwargs,
    )
    return plaintext, token


def _scim_request(rf, method, path, org, body=None):
    """Build a request with scim_org attached (simulates SCIMBearerAuth)."""
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path, data=json.dumps(body), content_type="application/json"
        )
    else:
        request = factory_method(path)
    request.scim_org = org
    request.request_id = "scim-test"
    request.META["REMOTE_ADDR"] = "10.0.0.1"
    request.scim_rate_limited = False
    return request


# =============================================================================
# TOKEN GENERATION
# =============================================================================


class TestCreateSCIMToken:
    """POST /{org_id}/scim-tokens — generate a new SCIM bearer token."""

    def test_create_token_returns_plaintext(self):
        org, owner, token_key = _create_org()
        resp = _post(
            _client(token_key), f"{_BASE}/{org.pk}/scim-tokens", {"name": "CI token"}
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "token" in body
        assert len(body["token"]) == 40  # 20 bytes hex = 40 chars
        assert body["prefix"] == body["token"][:8]
        assert body["name"] == "CI token"
        assert body["is_active"] is True

    def test_token_hash_stored_not_plaintext(self):
        org, owner, token_key = _create_org()
        resp = _post(_client(token_key), f"{_BASE}/{org.pk}/scim-tokens")
        plaintext = resp.json()["token"]
        token_id = resp.json()["id"]
        db_token = SCIMToken.objects.get(pk=token_id)
        expected_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        assert db_token.token_hash == expected_hash

    def test_create_multiple_tokens(self):
        """Multiple active tokens per org for zero-downtime rotation."""
        org, owner, token_key = _create_org()
        resp1 = _post(
            _client(token_key), f"{_BASE}/{org.pk}/scim-tokens", {"name": "old"}
        )
        resp2 = _post(
            _client(token_key), f"{_BASE}/{org.pk}/scim-tokens", {"name": "new"}
        )
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["token"] != resp2.json()["token"]
        assert org.scim_tokens.filter(is_active=True).count() == 2

    def test_create_token_with_allowed_cidrs(self):
        org, owner, token_key = _create_org()
        cidrs = ["10.0.0.0/8", "192.168.1.0/24"]
        resp = _post(
            _client(token_key),
            f"{_BASE}/{org.pk}/scim-tokens",
            {"allowed_cidrs": cidrs},
        )
        assert resp.status_code == 201
        assert resp.json()["allowed_cidrs"] == cidrs
        db_token = SCIMToken.objects.get(pk=resp.json()["id"])
        assert db_token.allowed_cidrs == cidrs

    def test_create_token_invalid_cidr(self):
        org, owner, token_key = _create_org()
        resp = _post(
            _client(token_key),
            f"{_BASE}/{org.pk}/scim-tokens",
            {"allowed_cidrs": ["not-a-cidr"]},
        )
        assert resp.status_code == 400
        assert "Invalid CIDR" in resp.json()["detail"]

    def test_create_token_audit_log(self):
        org, owner, token_key = _create_org()
        resp = _post(
            _client(token_key), f"{_BASE}/{org.pk}/scim-tokens", {"name": "audit test"}
        )
        assert resp.status_code == 201
        log = AuditLog.objects.filter(action="scim_token_created").first()
        assert log is not None
        assert log.resource_type == "scim_token"
        assert log.actor_email == owner.email
        assert log.metadata["token_prefix"] == resp.json()["prefix"]

    def test_create_token_empty_name_default(self):
        org, owner, token_key = _create_org()
        resp = _post(_client(token_key), f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 201
        assert resp.json()["name"] == ""


# =============================================================================
# TOKEN LISTING
# =============================================================================


class TestListSCIMTokens:
    """GET /{org_id}/scim-tokens — list tokens with prefix + metadata."""

    def test_list_tokens(self):
        org, owner, token_key = _create_org()
        _create_scim_token(org, name="tok1")
        _create_scim_token(org, name="tok2")
        resp = _client(token_key).get(f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        # Verify no plaintext token or hash is exposed
        for item in data:
            assert "token" not in item
            assert "token_hash" not in item
            assert "prefix" in item
            assert "last_used_at" in item
            assert "last_used_ip" in item
            assert "allowed_cidrs" in item

    def test_list_tokens_empty(self):
        org, owner, token_key = _create_org()
        resp = _client(token_key).get(f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tokens_other_org_not_visible(self):
        org1, owner1, tk1 = _create_org("Org One")
        org2, owner2, tk2 = _create_org("Org Two")
        _create_scim_token(org1, name="org1-token")
        _create_scim_token(org2, name="org2-token")
        resp = _client(tk1).get(f"{_BASE}/{org1.pk}/scim-tokens")
        assert len(resp.json()) == 1
        assert resp.json()[0]["name"] == "org1-token"


# =============================================================================
# TOKEN REVOCATION
# =============================================================================


class TestRevokeSCIMToken:
    """DELETE /{org_id}/scim-tokens/{token_id} — revoke a token."""

    def test_revoke_token(self):
        org, owner, token_key = _create_org()
        _, scim_tok = _create_scim_token(org)
        resp = _client(token_key).delete(f"{_BASE}/{org.pk}/scim-tokens/{scim_tok.pk}")
        assert resp.status_code == 200
        scim_tok.refresh_from_db()
        assert scim_tok.is_active is False

    def test_revoke_token_audit_log(self):
        org, owner, token_key = _create_org()
        _, scim_tok = _create_scim_token(org)
        _client(token_key).delete(f"{_BASE}/{org.pk}/scim-tokens/{scim_tok.pk}")
        log = AuditLog.objects.filter(action="scim_token_revoked").first()
        assert log is not None
        assert log.metadata["token_prefix"] == scim_tok.prefix

    def test_revoke_nonexistent_token(self):
        org, owner, token_key = _create_org()
        import uuid

        fake_id = str(uuid.uuid4())
        resp = _client(token_key).delete(f"{_BASE}/{org.pk}/scim-tokens/{fake_id}")
        assert resp.status_code == 404

    def test_revoke_token_from_other_org(self):
        org1, owner1, tk1 = _create_org("Org A")
        org2, _, _ = _create_org("Org B")
        _, scim_tok = _create_scim_token(org2)
        # org1 admin tries to revoke org2's token
        resp = _client(tk1).delete(f"{_BASE}/{org1.pk}/scim-tokens/{scim_tok.pk}")
        assert resp.status_code == 404  # not found in org1's scope


# =============================================================================
# PERMISSION ENFORCEMENT
# =============================================================================


class TestSCIMTokenPermissions:
    """Only admin+ roles can manage SCIM tokens."""

    def test_viewer_cannot_create(self):
        org, _, _ = _create_org()
        _, viewer_key = _add_member(org, OrganizationRole.VIEWER)
        resp = _post(_client(viewer_key), f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 401

    def test_member_cannot_create(self):
        org, _, _ = _create_org()
        _, member_key = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(_client(member_key), f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 401

    def test_admin_can_create(self):
        org, _, _ = _create_org()
        _, admin_key = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(
            _client(admin_key), f"{_BASE}/{org.pk}/scim-tokens", {"name": "admin tok"}
        )
        assert resp.status_code == 201

    def test_viewer_cannot_list(self):
        org, _, _ = _create_org()
        _, viewer_key = _add_member(org, OrganizationRole.VIEWER)
        resp = _client(viewer_key).get(f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 401

    def test_viewer_cannot_revoke(self):
        org, _, owner_key = _create_org()
        _, scim_tok = _create_scim_token(org)
        _, viewer_key = _add_member(org, OrganizationRole.VIEWER)
        resp = _client(viewer_key).delete(f"{_BASE}/{org.pk}/scim-tokens/{scim_tok.pk}")
        assert resp.status_code == 401

    def test_non_member_cannot_create(self):
        org, _, _ = _create_org()
        _, outsider_key = _make_user()
        resp = _post(_client(outsider_key), f"{_BASE}/{org.pk}/scim-tokens")
        assert resp.status_code == 401


# =============================================================================
# IP ALLOWLIST
# =============================================================================


class TestIPAllowlist:
    """SCIM token IP allowlist enforcement."""

    def test_ip_in_cidr(self):
        assert _ip_in_cidrs("10.0.1.5", ["10.0.0.0/8"]) is True

    def test_ip_not_in_cidr(self):
        assert _ip_in_cidrs("192.168.1.1", ["10.0.0.0/8"]) is False

    def test_empty_allowlist_allows_all(self):
        assert _ip_in_cidrs("1.2.3.4", []) is True

    def test_none_ip_with_allowlist_denied(self):
        assert _ip_in_cidrs(None, ["10.0.0.0/8"]) is False

    def test_multiple_cidrs(self):
        assert _ip_in_cidrs("192.168.1.5", ["10.0.0.0/8", "192.168.0.0/16"]) is True
        assert _ip_in_cidrs("172.16.0.1", ["10.0.0.0/8", "192.168.0.0/16"]) is False

    def test_invalid_cidr_skipped(self):
        # Invalid CIDR in list is skipped, valid one still matches
        assert _ip_in_cidrs("10.0.0.1", ["bad-cidr", "10.0.0.0/8"]) is True

    def test_invalid_ip_denied(self):
        assert _ip_in_cidrs("not-an-ip", ["10.0.0.0/8"]) is False

    def test_ipv6_in_cidr(self):
        assert _ip_in_cidrs("::1", ["::1/128"]) is True
        assert _ip_in_cidrs("::1", ["::2/128"]) is False


# =============================================================================
# USAGE TRACKING
# =============================================================================


class TestTokenUsageTracking:
    """last_used_at and last_used_ip are updated on SCIM API use."""

    def test_new_token_has_no_usage(self):
        org = Organization.objects.create(name="Usage Org")
        _, token = _create_scim_token(org)
        assert token.last_used_at is None
        assert token.last_used_ip is None

    def test_model_fields_exist(self):
        org = Organization.objects.create(name="Fields Org")
        _, token = _create_scim_token(org)
        # Verify the fields are accessible and settable
        from django.utils import timezone

        token.last_used_ip = "10.0.0.1"
        token.last_used_at = timezone.now()
        token.save()
        token.refresh_from_db()
        assert token.last_used_ip == "10.0.0.1"
        assert token.last_used_at is not None


# =============================================================================
# SCIM DISCOVERY ENDPOINTS
# =============================================================================


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def org():
    return Organization.objects.create(name="Discovery Org")


class TestServiceProviderConfig:
    """GET /{org_slug}/ServiceProviderConfig"""

    def test_returns_valid_scim_json(self, rf, org):
        _, scim_tok = _create_scim_token(org)
        request = _scim_request(
            rf, "get", f"/scim/v2/{org.slug}/ServiceProviderConfig", org
        )
        status, body = get_service_provider_config(request, org.slug)
        assert status == 200
        assert (
            "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
            in body["schemas"]
        )
        assert body["patch"]["supported"] is True
        assert body["bulk"]["supported"] is False
        assert body["filter"]["supported"] is True
        assert len(body["authenticationSchemes"]) == 1
        assert body["authenticationSchemes"][0]["type"] == "oauthbearertoken"

    def test_wrong_org_returns_403(self, rf, org):
        other_org = Organization.objects.create(name="Other")
        request = _scim_request(
            rf, "get", f"/scim/v2/{other_org.slug}/ServiceProviderConfig", org
        )
        status, body = get_service_provider_config(request, other_org.slug)
        assert status == 403


class TestSchemas:
    """GET /{org_slug}/Schemas"""

    def test_returns_user_schema(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Schemas", org)
        status, body = get_schemas(request, org.slug)
        assert status == 200
        assert body["totalResults"] == 1
        user_schema = body["Resources"][0]
        assert user_schema["id"] == "urn:ietf:params:scim:schemas:core:2.0:User"
        assert user_schema["name"] == "User"
        attr_names = [a["name"] for a in user_schema["attributes"]]
        assert "userName" in attr_names
        assert "name" in attr_names
        assert "active" in attr_names

    def test_schema_has_correct_meta(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Schemas", org)
        status, body = get_schemas(request, org.slug)
        user_schema = body["Resources"][0]
        assert org.slug in user_schema["meta"]["location"]


class TestResourceTypes:
    """GET /{org_slug}/ResourceTypes"""

    def test_returns_user_resource_type(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/ResourceTypes", org)
        status, body = get_resource_types(request, org.slug)
        assert status == 200
        assert body["totalResults"] == 1
        rt = body["Resources"][0]
        assert rt["id"] == "User"
        assert rt["name"] == "User"
        assert rt["schema"] == "urn:ietf:params:scim:schemas:core:2.0:User"
        assert org.slug in rt["endpoint"]

    def test_resource_type_meta_location(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/ResourceTypes", org)
        status, body = get_resource_types(request, org.slug)
        rt = body["Resources"][0]
        assert "ResourceTypes/User" in rt["meta"]["location"]


# =============================================================================
# TOKEN ROTATION WORKFLOW
# =============================================================================


class TestTokenRotation:
    """End-to-end token rotation: create new → both active → revoke old."""

    def test_rotation_workflow(self):
        org, owner, token_key = _create_org("Rotation Org")
        c = _client(token_key)

        # Create initial token
        resp1 = _post(c, f"{_BASE}/{org.pk}/scim-tokens", {"name": "v1"})
        assert resp1.status_code == 201
        tok1_id = resp1.json()["id"]

        # Create second token (rotation)
        resp2 = _post(c, f"{_BASE}/{org.pk}/scim-tokens", {"name": "v2"})
        assert resp2.status_code == 201

        # Both active
        assert org.scim_tokens.filter(is_active=True).count() == 2

        # Revoke old
        resp3 = c.delete(f"{_BASE}/{org.pk}/scim-tokens/{tok1_id}")
        assert resp3.status_code == 200

        # Only new one active
        active = org.scim_tokens.filter(is_active=True)
        assert active.count() == 1
        assert active.first().name == "v2"
