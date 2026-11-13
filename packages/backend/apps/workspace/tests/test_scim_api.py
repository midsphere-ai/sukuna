"""SCIM 2.0 provisioning tests — model, bearer token auth, CRUD endpoints,
pagination, audit logging, and error handling.

Covers US-012 acceptance criteria.
"""

import hashlib
import json
import secrets
import uuid

import pytest
from django.test import RequestFactory

from apps.compliance.models import AuditLog
from apps.users.models import User
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SCIMToken,
)
from apps.workspace.scim_api import (
    create_scim_user,
    delete_scim_user,
    get_scim_user,
    list_scim_users,
    patch_scim_user,
    replace_scim_user,
)

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def org():
    return Organization.objects.create(name="SCIM Test Org")


@pytest.fixture
def other_org():
    return Organization.objects.create(name="Other Org")


def _create_scim_token(org):
    """Create a SCIM token and return (plaintext, SCIMToken instance)."""
    plaintext = secrets.token_hex(20)
    token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
    token = SCIMToken.objects.create(
        organization=org,
        token_hash=token_hash,
        prefix=plaintext[:8],
    )
    return plaintext, token


def _scim_request(rf, method, path, org, body=None):
    """Build a request with scim_org attached (simulates SCIMBearerAuth)."""
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path,
            data=json.dumps(body),
            content_type="application/json",
        )
    else:
        request = factory_method(path)
    request.scim_org = org
    request.request_id = "scim-test"
    request.META["REMOTE_ADDR"] = "10.0.0.1"
    return request


# ===========================================================================
# MODEL TESTS
# ===========================================================================


class TestSCIMTokenModel:
    """SCIMToken model creation and field behavior."""

    def test_create_token(self, org):
        plaintext, token = _create_scim_token(org)
        assert token.pk is not None
        assert token.organization == org
        assert token.prefix == plaintext[:8]
        assert token.is_active is True
        assert token.last_used_at is None
        assert token.created_at is not None

    def test_token_hash_unique(self, org):
        _, token1 = _create_scim_token(org)
        with pytest.raises(Exception):
            SCIMToken.objects.create(
                organization=org,
                token_hash=token1.token_hash,
                prefix="dup12345",
            )

    def test_token_str(self, org):
        _, token = _create_scim_token(org)
        assert "SCIM token" in str(token)
        assert org.name in str(token)

    def test_token_org_cascade(self, org):
        _, token = _create_scim_token(org)
        token_pk = token.pk
        org.delete()
        assert not SCIMToken.objects.filter(pk=token_pk).exists()


# ===========================================================================
# BEARER TOKEN AUTH TESTS
# ===========================================================================


class TestSCIMBearerAuth:
    """SCIM bearer token authentication."""

    def test_valid_token_authenticates(self, org):
        from apps.workspace.scim_api import SCIMBearerAuth

        plaintext, _ = _create_scim_token(org)
        auth = SCIMBearerAuth()
        rf = RequestFactory()
        request = rf.get("/scim/v2/test/Users")
        result = auth.authenticate(request, plaintext)
        assert result is not None
        assert request.scim_org == org

    def test_invalid_token_returns_none(self, org):
        from apps.workspace.scim_api import SCIMBearerAuth

        auth = SCIMBearerAuth()
        rf = RequestFactory()
        request = rf.get("/scim/v2/test/Users")
        result = auth.authenticate(request, "invalid-token-value")
        assert result is None

    def test_inactive_token_returns_none(self, org):
        from apps.workspace.scim_api import SCIMBearerAuth

        plaintext, token = _create_scim_token(org)
        token.is_active = False
        token.save()

        auth = SCIMBearerAuth()
        rf = RequestFactory()
        request = rf.get("/scim/v2/test/Users")
        result = auth.authenticate(request, plaintext)
        assert result is None

    def test_token_last_used_updated(self, org):
        from apps.workspace.scim_api import SCIMBearerAuth

        plaintext, token = _create_scim_token(org)
        assert token.last_used_at is None

        auth = SCIMBearerAuth()
        rf = RequestFactory()
        request = rf.get("/scim/v2/test/Users")
        auth.authenticate(request, plaintext)

        token.refresh_from_db()
        assert token.last_used_at is not None


# ===========================================================================
# PROVISION (POST) TESTS
# ===========================================================================


class TestSCIMProvisionUser:
    """SCIM POST /Users — provision new and existing users."""

    def test_provision_new_user(self, rf, org):
        email = f"newuser-{uuid.uuid4().hex[:8]}@example.com"
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(
            userName=email,
            name={"givenName": "New User"},
        )
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 201
        assert data["userName"] == email
        assert data["name"]["givenName"] == "New User"
        assert data["active"] is True

        # User exists in DB
        user = User.objects.get_by_email(email)
        assert user.name == "New User"
        assert org.has_member(user)

    def test_provision_existing_user(self, rf, org):
        user = UserFactory()
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=user.email)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 201
        assert data["id"] == str(user.pk)
        assert org.has_member(user)

    def test_provision_duplicate_member_409(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=user.email)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 409
        assert "already a member" in data["detail"]

    def test_provision_empty_username_400(self, rf, org):
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName="  ")
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 400

    def test_provision_with_inactive_status(self, rf, org):
        email = f"inactive-{uuid.uuid4().hex[:8]}@example.com"
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=email, active=False)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 201
        assert data["active"] is False

        user = User.objects.get_by_email(email)
        assert user.is_active is False

    def test_provision_audit_log(self, rf, org):
        email = f"audit-{uuid.uuid4().hex[:8]}@example.com"
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=email, name={"givenName": "Audited"})
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        create_scim_user(request, org.slug, body)

        log = AuditLog.objects.filter(action="scim_user_provisioned").first()
        assert log is not None
        assert log.actor_email == f"scim:{org.slug}"
        assert log.metadata["email"] == email
        assert log.metadata["user_created"] is True

    def test_provision_wrong_org_403(self, rf, org, other_org):
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName="test@example.com")
        # Token is for org, but slug is for other_org
        request = _scim_request(rf, "post", f"/scim/v2/{other_org.slug}/Users", org)
        status, data = create_scim_user(request, other_org.slug, body)
        assert status == 403


# ===========================================================================
# GET (SINGLE) TESTS
# ===========================================================================


class TestSCIMGetUser:
    """SCIM GET /Users/{id} — single user retrieval."""

    def test_get_existing_user(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = get_scim_user(request, org.slug, user.pk)
        assert status == 200
        assert data["userName"] == user.email
        assert data["id"] == str(user.pk)

    def test_get_nonexistent_user_404(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users/99999", org)
        status, data = get_scim_user(request, org.slug, 99999)
        assert status == 404

    def test_get_wrong_org_403(self, rf, org, other_org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(
            rf, "get", f"/scim/v2/{other_org.slug}/Users/{user.pk}", org
        )
        status, _ = get_scim_user(request, other_org.slug, user.pk)
        assert status == 403


# ===========================================================================
# LIST TESTS
# ===========================================================================


class TestSCIMListUsers:
    """SCIM GET /Users — list with pagination."""

    def test_list_empty_org(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        status, data = list_scim_users(request, org.slug)
        assert status == 200
        assert data["totalResults"] == 0
        assert data["Resources"] == []

    def test_list_with_members(self, rf, org):
        users = [UserFactory() for _ in range(3)]
        for u in users:
            OrganizationMembership.objects.create(
                organization=org, user=u, role=OrganizationRole.MEMBER
            )

        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        status, data = list_scim_users(request, org.slug)
        assert status == 200
        assert data["totalResults"] == 3
        assert len(data["Resources"]) == 3

    def test_list_pagination(self, rf, org):
        users = [UserFactory() for _ in range(5)]
        for u in users:
            OrganizationMembership.objects.create(
                organization=org, user=u, role=OrganizationRole.MEMBER
            )

        request = _scim_request(
            rf, "get", f"/scim/v2/{org.slug}/Users?startIndex=1&count=2", org
        )
        status, data = list_scim_users(request, org.slug, startIndex=1, count=2)
        assert status == 200
        assert data["totalResults"] == 5
        assert len(data["Resources"]) == 2
        assert data["startIndex"] == 1
        assert data["itemsPerPage"] == 2

    def test_list_pagination_offset(self, rf, org):
        users = [UserFactory() for _ in range(5)]
        for u in users:
            OrganizationMembership.objects.create(
                organization=org, user=u, role=OrganizationRole.MEMBER
            )

        request = _scim_request(
            rf, "get", f"/scim/v2/{org.slug}/Users?startIndex=4&count=10", org
        )
        status, data = list_scim_users(request, org.slug, startIndex=4, count=10)
        assert status == 200
        assert data["totalResults"] == 5
        assert len(data["Resources"]) == 2  # items 4 and 5


# ===========================================================================
# PUT (REPLACE) TESTS
# ===========================================================================


class TestSCIMReplaceUser:
    """SCIM PUT /Users/{id} — full replace."""

    def test_replace_user_name(self, rf, org):
        user = UserFactory(name="Original")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import ReplaceSCIMUserRequest

        body = ReplaceSCIMUserRequest(
            userName=user.email,
            name={"givenName": "Updated"},
            active=True,
        )
        request = _scim_request(rf, "put", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = replace_scim_user(request, org.slug, user.pk, body)
        assert status == 200
        assert data["name"]["givenName"] == "Updated"

        user.refresh_from_db()
        assert user.name == "Updated"

    def test_replace_deactivate_user(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import ReplaceSCIMUserRequest

        body = ReplaceSCIMUserRequest(userName=user.email, active=False)
        request = _scim_request(rf, "put", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = replace_scim_user(request, org.slug, user.pk, body)
        assert status == 200
        assert data["active"] is False

        user.refresh_from_db()
        assert user.is_active is False

    def test_replace_nonexistent_user_404(self, rf, org):
        from apps.workspace.scim_schemas import ReplaceSCIMUserRequest

        body = ReplaceSCIMUserRequest(userName="nobody@example.com")
        request = _scim_request(rf, "put", f"/scim/v2/{org.slug}/Users/99999", org)
        status, _ = replace_scim_user(request, org.slug, 99999, body)
        assert status == 404

    def test_replace_audit_log(self, rf, org):
        user = UserFactory(name="Before")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import ReplaceSCIMUserRequest

        body = ReplaceSCIMUserRequest(userName=user.email, name={"givenName": "After"})
        request = _scim_request(rf, "put", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        replace_scim_user(request, org.slug, user.pk, body)

        log = AuditLog.objects.filter(action="scim_user_updated").first()
        assert log is not None
        assert log.changes["name"]["old"] == "Before"
        assert log.changes["name"]["new"] == "After"


# ===========================================================================
# PATCH TESTS
# ===========================================================================


class TestSCIMPatchUser:
    """SCIM PATCH /Users/{id} — partial update."""

    def test_patch_deactivate(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import PatchOperation, PatchSCIMUserRequest

        body = PatchSCIMUserRequest(
            Operations=[PatchOperation(op="replace", path="active", value=False)]
        )
        request = _scim_request(
            rf, "patch", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = patch_scim_user(request, org.slug, user.pk, body)
        assert status == 200
        assert data["active"] is False

        user.refresh_from_db()
        assert user.is_active is False

    def test_patch_update_name(self, rf, org):
        user = UserFactory(name="Old Name")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import PatchOperation, PatchSCIMUserRequest

        body = PatchSCIMUserRequest(
            Operations=[
                PatchOperation(op="replace", path="name.givenName", value="New Name")
            ]
        )
        request = _scim_request(
            rf, "patch", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = patch_scim_user(request, org.slug, user.pk, body)
        assert status == 200

        user.refresh_from_db()
        assert user.name == "New Name"

    def test_patch_unsupported_op_400(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import PatchOperation, PatchSCIMUserRequest

        body = PatchSCIMUserRequest(
            Operations=[PatchOperation(op="invalid", path="active", value=True)]
        )
        request = _scim_request(
            rf, "patch", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = patch_scim_user(request, org.slug, user.pk, body)
        assert status == 400

    def test_patch_nonexistent_user_404(self, rf, org):
        from apps.workspace.scim_schemas import PatchOperation, PatchSCIMUserRequest

        body = PatchSCIMUserRequest(
            Operations=[PatchOperation(op="replace", path="active", value=False)]
        )
        request = _scim_request(rf, "patch", f"/scim/v2/{org.slug}/Users/99999", org)
        status, _ = patch_scim_user(request, org.slug, 99999, body)
        assert status == 404

    def test_patch_active_via_value_dict(self, rf, org):
        """Test PATCH with active in value dict (no path) — common IdP pattern."""
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        from apps.workspace.scim_schemas import PatchOperation, PatchSCIMUserRequest

        body = PatchSCIMUserRequest(
            Operations=[PatchOperation(op="replace", value={"active": False})]
        )
        request = _scim_request(
            rf, "patch", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = patch_scim_user(request, org.slug, user.pk, body)
        assert status == 200
        assert data["active"] is False


# ===========================================================================
# DELETE (DEPROVISION) TESTS
# ===========================================================================


class TestSCIMDeleteUser:
    """SCIM DELETE /Users/{id} — deprovision."""

    def test_deprovision_user(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = delete_scim_user(request, org.slug, user.pk)
        assert status == 200

        # User is deactivated but still exists
        user.refresh_from_db()
        assert user.is_active is False

        # User removed from org
        assert not org.has_member(user)

    def test_deprovision_nonexistent_user_404(self, rf, org):
        request = _scim_request(rf, "delete", f"/scim/v2/{org.slug}/Users/99999", org)
        status, _ = delete_scim_user(request, org.slug, 99999)
        assert status == 404

    def test_deprovision_audit_log(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        delete_scim_user(request, org.slug, user.pk)

        log = AuditLog.objects.filter(action="scim_user_deprovisioned").first()
        assert log is not None
        assert log.resource_id == str(user.pk)
        assert log.metadata["organization_id"] == str(org.pk)

    def test_deprovision_preserves_historical_data(self, rf, org):
        """User record is kept (is_active=False) but org membership removed."""
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        user_pk = user.pk

        request = _scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        delete_scim_user(request, org.slug, user.pk)

        # User still exists in DB
        assert User.objects.filter(pk=user_pk).exists()
        user.refresh_from_db()
        assert user.is_active is False


# ===========================================================================
# SCIM RESPONSE FORMAT TESTS
# ===========================================================================


class TestSCIMResponseFormat:
    """Verify SCIM-compliant response format (RFC 7644)."""

    def test_user_resource_has_schemas(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = get_scim_user(request, org.slug, user.pk)
        assert "urn:ietf:params:scim:schemas:core:2.0:User" in data["schemas"]

    def test_user_resource_has_meta(self, rf, org):
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = get_scim_user(request, org.slug, user.pk)
        assert "meta" in data
        assert data["meta"]["resourceType"] == "User"
        assert "location" in data["meta"]
        assert f"/Users/{user.pk}" in data["meta"]["location"]

    def test_list_response_has_schemas(self, rf, org):
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        status, data = list_scim_users(request, org.slug)
        assert "urn:ietf:params:scim:api:messages:2.0:ListResponse" in data["schemas"]

    def test_error_response_has_schemas(self, rf, org, other_org):
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName="test@example.com")
        request = _scim_request(rf, "post", f"/scim/v2/{other_org.slug}/Users", org)
        status, data = create_scim_user(request, other_org.slug, body)
        assert status == 403
        assert "urn:ietf:params:scim:api:messages:2.0:Error" in data["schemas"]
        assert data["status"] == "403"

    def test_user_attribute_mapping(self, rf, org):
        """userName->email, name.givenName->name, active->is_active."""
        user = UserFactory(name="Jane Doe")
        OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )

        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users/{user.pk}", org)
        status, data = get_scim_user(request, org.slug, user.pk)
        assert data["userName"] == user.email
        assert data["name"]["givenName"] == "Jane Doe"
        assert data["active"] == user.is_active


# ===========================================================================
# EDGE CASE TESTS
# ===========================================================================


class TestSCIMEdgeCases:
    """Edge cases from acceptance criteria."""

    def test_provision_reactivates_deactivated_account(self, rf, org):
        """SCIM provisions user whose email matches deactivated account → reactivate."""
        user = UserFactory(is_active=False)
        email = user.email

        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=email)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)

        assert status == 201
        user.refresh_from_db()
        assert user.is_active is True
        assert org.has_member(user)

    def test_provision_deactivated_account_stays_inactive_when_active_false(
        self, rf, org
    ):
        """If SCIM provisions with active=False, deactivated account stays inactive."""
        user = UserFactory(is_active=False)
        email = user.email

        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=email, active=False)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)

        assert status == 201
        user.refresh_from_db()
        assert user.is_active is False
        assert org.has_member(user)

    def test_deprovision_org_owner_409(self, rf, org):
        """SCIM deprovisions the org owner → refuse with 409 Conflict."""
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.OWNER,
        )

        request = _scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{user.pk}", org
        )
        status, data = delete_scim_user(request, org.slug, user.pk)
        assert status == 409
        assert "owner" in data["detail"].lower()

        # User still active and still a member
        user.refresh_from_db()
        assert user.is_active is True
        assert org.has_member(user)

    def test_deprovision_non_last_owner_succeeds(self, rf, org):
        """If org has multiple owners, one can be deprovisioned."""
        owner1 = UserFactory()
        owner2 = UserFactory()
        OrganizationMembership.objects.create(
            organization=org,
            user=owner1,
            role=OrganizationRole.OWNER,
        )
        OrganizationMembership.objects.create(
            organization=org,
            user=owner2,
            role=OrganizationRole.OWNER,
        )

        request = _scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{owner1.pk}", org
        )
        status, data = delete_scim_user(request, org.slug, owner1.pk)
        assert status == 200
        assert not org.has_member(owner1)

    def test_concurrent_invite_race_condition(self, rf, org):
        """SCIM and manual invite both target same user → graceful 409."""
        user = UserFactory()
        # Simulate manual invite already completed
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.MEMBER,
        )

        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName=user.email)
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 409
        assert "already a member" in data["detail"]

    def test_filter_username_eq_uses_email_hash(self, rf, org):
        """SCIM filter userName eq 'x@y.com' → use email_hash lookup."""
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org,
            user=user,
            role=OrganizationRole.MEMBER,
        )
        # Create another user that should NOT match
        other = UserFactory()
        OrganizationMembership.objects.create(
            organization=org,
            user=other,
            role=OrganizationRole.MEMBER,
        )

        filter_str = f'userName eq "{user.email}"'
        request = _scim_request(
            rf, "get", f"/scim/v2/{org.slug}/Users?filter={filter_str}", org
        )
        status, data = list_scim_users(request, org.slug, filter=filter_str)
        assert status == 200
        assert data["totalResults"] == 1
        assert data["Resources"][0]["userName"] == user.email

    def test_filter_username_no_match(self, rf, org):
        """SCIM filter for non-existent email returns empty list."""
        filter_str = 'userName eq "nobody@example.com"'
        request = _scim_request(
            rf, "get", f"/scim/v2/{org.slug}/Users?filter={filter_str}", org
        )
        status, data = list_scim_users(request, org.slug, filter=filter_str)
        assert status == 200
        assert data["totalResults"] == 0

    def test_rate_limit_flag_blocks_list(self, rf, org):
        """Rate-limited request returns 429 on list endpoint."""
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        request.scim_rate_limited = True
        status, data = list_scim_users(request, org.slug)
        assert status == 429
        assert "Rate limit" in data["detail"]

    def test_rate_limit_flag_blocks_create(self, rf, org):
        """Rate-limited request returns 429 on create endpoint."""
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        body = CreateSCIMUserRequest(userName="test@example.com")
        request = _scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        request.scim_rate_limited = True
        status, data = create_scim_user(request, org.slug, body)
        assert status == 429

    def test_rate_limit_flag_blocks_delete(self, rf, org):
        """Rate-limited request returns 429 on delete endpoint."""
        request = _scim_request(rf, "delete", f"/scim/v2/{org.slug}/Users/1", org)
        request.scim_rate_limited = True
        status, data = delete_scim_user(request, org.slug, 1)
        assert status == 429

    def test_rate_limit_flag_blocks_put(self, rf, org):
        """Rate-limited request returns 429 on replace endpoint."""
        from apps.workspace.scim_schemas import ReplaceSCIMUserRequest

        body = ReplaceSCIMUserRequest(userName="test@example.com")
        request = _scim_request(rf, "put", f"/scim/v2/{org.slug}/Users/1", org)
        request.scim_rate_limited = True
        status, data = replace_scim_user(request, org.slug, 1, body)
        assert status == 429

    def test_rate_limit_flag_blocks_patch(self, rf, org):
        """Rate-limited request returns 429 on patch endpoint."""
        from apps.workspace.scim_schemas import PatchSCIMUserRequest

        body = PatchSCIMUserRequest(Operations=[])
        request = _scim_request(rf, "patch", f"/scim/v2/{org.slug}/Users/1", org)
        request.scim_rate_limited = True
        status, data = patch_scim_user(request, org.slug, 1, body)
        assert status == 429

    def test_cursor_pagination_stable_ordering(self, rf, org):
        """Pagination uses stable ordering by user.id (cursor-based)."""
        users = sorted([UserFactory() for _ in range(5)], key=lambda u: u.pk)
        for u in users:
            OrganizationMembership.objects.create(
                organization=org,
                user=u,
                role=OrganizationRole.MEMBER,
            )

        # Fetch page 1 (items 1-3)
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        _, page1 = list_scim_users(request, org.slug, startIndex=1, count=3)

        # Fetch page 2 (items 4-5)
        request = _scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        _, page2 = list_scim_users(request, org.slug, startIndex=4, count=3)

        # No overlap
        page1_ids = {r["id"] for r in page1["Resources"]}
        page2_ids = {r["id"] for r in page2["Resources"]}
        assert page1_ids.isdisjoint(page2_ids)
        assert len(page1["Resources"]) == 3
        assert len(page2["Resources"]) == 2
