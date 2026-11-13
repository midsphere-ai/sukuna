"""SSO Configuration tests — model CRUD, API permission enforcement,
enforcement logic, SP metadata endpoint, and audit logging.

Covers US-010 acceptance criteria.
"""

import json

import pytest
from django.test import RequestFactory

from apps.compliance.models import AuditLog
from apps.compliance.security_middleware import (
    SecurityPolicyMiddleware,
    get_effective_policy,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SSOConfiguration,
    SSOProviderType,
)
from apps.workspace.org_api import (
    create_sso_config,
    delete_sso_config,
    get_sp_metadata,
    get_sso_config,
    update_sso_config,
)
from config.errors.common import UnauthorizedAccessError

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def org():
    return Organization.objects.create(name="SSO Test Org")


def _make_member(org, role):
    """Create a user and add as org member with the given role."""
    user = UserFactory()
    OrganizationMembership.objects.create(organization=org, user=user, role=role)
    return user


def _authed_request(rf, method, path, user, body=None):
    """Build a request with the auth user attached."""
    factory_method = getattr(rf, method)
    if body is not None:
        request = factory_method(
            path,
            data=json.dumps(body),
            content_type="application/json",
        )
    else:
        request = factory_method(path, **{})
    request.auth = user
    request.request_id = "sso-test"
    request.META["REMOTE_ADDR"] = "10.0.0.1"
    return request


# ===========================================================================
# MODEL TESTS
# ===========================================================================


class TestSSOConfigurationModel:
    """Tests for the SSOConfiguration model."""

    def test_create_sso_config(self, org):
        """Can create a basic SSO configuration."""
        sso = SSOConfiguration.objects.create(
            organization=org,
            provider_type=SSOProviderType.SAML,
            metadata_url="https://idp.example.com/metadata",
            entity_id="https://idp.example.com",
            certificate="-----BEGIN CERTIFICATE-----\nMIIBx...\n-----END CERTIFICATE-----",
        )
        assert sso.pk is not None
        assert sso.organization == org
        assert sso.provider_type == "saml"
        assert sso.is_active is False
        assert sso.enforce_sso is False

    def test_one_to_one_constraint(self, org):
        """Only one SSO config per organization."""
        SSOConfiguration.objects.create(organization=org)
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            SSOConfiguration.objects.create(organization=org)

    def test_provider_type_choices(self, org):
        """Both SAML and OIDC provider types are valid."""
        saml = SSOConfiguration.objects.create(
            organization=org, provider_type=SSOProviderType.SAML
        )
        assert saml.get_provider_type_display() == "SAML 2.0"

        saml.delete()
        oidc = SSOConfiguration.objects.create(
            organization=org, provider_type=SSOProviderType.OIDC
        )
        assert oidc.get_provider_type_display() == "OpenID Connect"

    def test_cascade_delete_with_org(self, org):
        """SSO config is deleted when organization is deleted."""
        sso = SSOConfiguration.objects.create(organization=org)
        sso_pk = sso.pk
        org.delete()
        assert not SSOConfiguration.objects.filter(pk=sso_pk).exists()

    def test_str_representation(self, org):
        """String representation includes provider type and org name."""
        sso = SSOConfiguration.objects.create(
            organization=org, provider_type=SSOProviderType.SAML
        )
        s = str(sso)
        assert "SAML" in s
        assert org.name in s

    def test_default_values(self, org):
        """Default values are set correctly."""
        sso = SSOConfiguration.objects.create(organization=org)
        assert sso.provider_type == "saml"
        assert sso.metadata_url == ""
        assert sso.entity_id == ""
        assert sso.certificate == ""
        assert sso.is_active is False
        assert sso.enforce_sso is False

    def test_timestamps(self, org):
        """created_at and updated_at are set."""
        sso = SSOConfiguration.objects.create(organization=org)
        assert sso.created_at is not None
        assert sso.updated_at is not None


# ===========================================================================
# API PERMISSION TESTS
# ===========================================================================


class TestSSOConfigAPIPermissions:
    """Test that SSO endpoints enforce admin+ role."""

    def test_viewer_cannot_create(self, rf, org):
        """Viewers cannot create SSO config."""
        viewer = _make_member(org, OrganizationRole.VIEWER)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", viewer, body={})
        with pytest.raises(UnauthorizedAccessError):
            create_sso_config(
                request,
                str(org.pk),
                body=type(
                    "B",
                    (),
                    {
                        "provider_type": "saml",
                        "metadata_url": "",
                        "entity_id": "",
                        "certificate": "",
                        "is_active": False,
                        "enforce_sso": False,
                    },
                )(),
            )

    def test_member_cannot_create(self, rf, org):
        """Members cannot create SSO config."""
        member = _make_member(org, OrganizationRole.MEMBER)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", member, body={})
        with pytest.raises(UnauthorizedAccessError):
            create_sso_config(
                request,
                str(org.pk),
                body=type(
                    "B",
                    (),
                    {
                        "provider_type": "saml",
                        "metadata_url": "",
                        "entity_id": "",
                        "certificate": "",
                        "is_active": False,
                        "enforce_sso": False,
                    },
                )(),
            )

    def test_admin_can_create(self, rf, org):
        """Admins can create SSO config."""
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", admin, body={})
        body = type(
            "B",
            (),
            {
                "provider_type": "saml",
                "metadata_url": "https://idp.example.com/metadata",
                "entity_id": "https://idp.example.com",
                "certificate": "cert",
                "is_active": False,
                "enforce_sso": False,
            },
        )()
        status, data = create_sso_config(request, str(org.pk), body=body)
        assert status == 201

    def test_owner_can_create(self, rf, org):
        """Owners can create SSO config."""
        owner = _make_member(org, OrganizationRole.OWNER)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", owner, body={})
        body = type(
            "B",
            (),
            {
                "provider_type": "saml",
                "metadata_url": "",
                "entity_id": "",
                "certificate": "",
                "is_active": False,
                "enforce_sso": False,
            },
        )()
        status, data = create_sso_config(request, str(org.pk), body=body)
        assert status == 201

    def test_viewer_cannot_get(self, rf, org):
        """Viewers cannot get SSO config."""
        SSOConfiguration.objects.create(organization=org)
        viewer = _make_member(org, OrganizationRole.VIEWER)
        request = _authed_request(rf, "get", f"/{org.pk}/sso", viewer)
        with pytest.raises(UnauthorizedAccessError):
            get_sso_config(request, str(org.pk))

    def test_viewer_cannot_update(self, rf, org):
        """Viewers cannot update SSO config."""
        SSOConfiguration.objects.create(organization=org)
        viewer = _make_member(org, OrganizationRole.VIEWER)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", viewer, body={})
        body = type(
            "B",
            (),
            {
                "provider_type": None,
                "metadata_url": None,
                "entity_id": None,
                "certificate": None,
                "is_active": True,
                "enforce_sso": None,
            },
        )()
        with pytest.raises(UnauthorizedAccessError):
            update_sso_config(request, str(org.pk), body=body)

    def test_viewer_cannot_delete(self, rf, org):
        """Viewers cannot delete SSO config."""
        SSOConfiguration.objects.create(organization=org)
        viewer = _make_member(org, OrganizationRole.VIEWER)
        request = _authed_request(rf, "delete", f"/{org.pk}/sso", viewer)
        with pytest.raises(UnauthorizedAccessError):
            delete_sso_config(request, str(org.pk))


# ===========================================================================
# API CRUD TESTS
# ===========================================================================


class TestSSOConfigAPICRUD:
    """Test SSO config CRUD operations."""

    def _admin(self, org, rf):
        admin = _make_member(org, OrganizationRole.ADMIN)
        return admin

    def test_create_full_config(self, rf, org):
        """Create SSO config with all fields."""
        admin = self._admin(org, rf)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "saml",
                "metadata_url": "https://idp.example.com/metadata",
                "entity_id": "https://idp.example.com",
                "certificate": "MIIB...",
                "is_active": True,
                "enforce_sso": False,
            },
        )()
        status, data = create_sso_config(request, str(org.pk), body=body)
        assert status == 201
        assert data["provider_type"] == "saml"
        assert data["metadata_url"] == "https://idp.example.com/metadata"
        assert data["entity_id"] == "https://idp.example.com"
        assert data["is_active"] is True
        assert data["enforce_sso"] is False
        assert data["organization_id"] == org.pk

    def test_create_duplicate_returns_409(self, rf, org):
        """Cannot create two SSO configs for the same org."""
        SSOConfiguration.objects.create(organization=org)
        admin = self._admin(org, rf)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "saml",
                "metadata_url": "",
                "entity_id": "",
                "certificate": "",
                "is_active": False,
                "enforce_sso": False,
            },
        )()
        status, data = create_sso_config(request, str(org.pk), body=body)
        assert status == 409

    def test_create_invalid_provider_type(self, rf, org):
        """Invalid provider_type returns 400."""
        admin = self._admin(org, rf)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "invalid",
                "metadata_url": "",
                "entity_id": "",
                "certificate": "",
                "is_active": False,
                "enforce_sso": False,
            },
        )()
        status, data = create_sso_config(request, str(org.pk), body=body)
        assert status == 400
        assert "provider_type" in data["detail"].lower()

    def test_get_config(self, rf, org):
        """Get existing SSO config."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            metadata_url="https://idp.example.com/metadata",
        )
        admin = self._admin(org, rf)
        request = _authed_request(rf, "get", f"/{org.pk}/sso", admin)
        status, data = get_sso_config(request, str(org.pk))
        assert status == 200
        assert data["provider_type"] == "saml"
        assert data["metadata_url"] == "https://idp.example.com/metadata"

    def test_get_nonexistent_returns_404(self, rf, org):
        """Getting SSO config for org without one returns 404."""
        admin = self._admin(org, rf)
        request = _authed_request(rf, "get", f"/{org.pk}/sso", admin)
        status, data = get_sso_config(request, str(org.pk))
        assert status == 404

    def test_update_config(self, rf, org):
        """Update SSO config fields."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            metadata_url="https://old.example.com/metadata",
        )
        admin = self._admin(org, rf)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": None,
                "metadata_url": "https://new.example.com/metadata",
                "entity_id": "https://new.example.com",
                "certificate": None,
                "is_active": True,
                "enforce_sso": None,
            },
        )()
        status, data = update_sso_config(request, str(org.pk), body=body)
        assert status == 200
        assert data["metadata_url"] == "https://new.example.com/metadata"
        assert data["entity_id"] == "https://new.example.com"
        assert data["is_active"] is True

    def test_update_provider_type(self, rf, org):
        """Can change provider type from SAML to OIDC."""
        SSOConfiguration.objects.create(organization=org, provider_type="saml")
        admin = self._admin(org, rf)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "oidc",
                "metadata_url": None,
                "entity_id": None,
                "certificate": None,
                "is_active": None,
                "enforce_sso": None,
            },
        )()
        status, data = update_sso_config(request, str(org.pk), body=body)
        assert status == 200
        assert data["provider_type"] == "oidc"

    def test_update_invalid_provider_type(self, rf, org):
        """Invalid provider_type on update returns 400."""
        SSOConfiguration.objects.create(organization=org)
        admin = self._admin(org, rf)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "invalid",
                "metadata_url": None,
                "entity_id": None,
                "certificate": None,
                "is_active": None,
                "enforce_sso": None,
            },
        )()
        status, data = update_sso_config(request, str(org.pk), body=body)
        assert status == 400

    def test_update_nonexistent_returns_404(self, rf, org):
        """Updating SSO config for org without one returns 404."""
        admin = self._admin(org, rf)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": None,
                "metadata_url": None,
                "entity_id": None,
                "certificate": None,
                "is_active": True,
                "enforce_sso": None,
            },
        )()
        status, data = update_sso_config(request, str(org.pk), body=body)
        assert status == 404

    def test_delete_config(self, rf, org):
        """Delete SSO config successfully."""
        SSOConfiguration.objects.create(organization=org)
        admin = self._admin(org, rf)
        request = _authed_request(rf, "delete", f"/{org.pk}/sso", admin)
        status, data = delete_sso_config(request, str(org.pk))
        assert status == 200
        assert data["success"] is True
        assert not SSOConfiguration.objects.filter(organization=org).exists()

    def test_delete_nonexistent_returns_404(self, rf, org):
        """Deleting SSO config for org without one returns 404."""
        admin = self._admin(org, rf)
        request = _authed_request(rf, "delete", f"/{org.pk}/sso", admin)
        status, data = delete_sso_config(request, str(org.pk))
        assert status == 404


# ===========================================================================
# AUDIT LOG TESTS
# ===========================================================================


class TestSSOConfigAuditLog:
    """Test that SSO config operations create audit log entries."""

    def test_create_audit_log(self, rf, org):
        """Creating SSO config creates an audit log entry."""
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "post", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": "saml",
                "metadata_url": "https://idp.example.com",
                "entity_id": "eid",
                "certificate": "",
                "is_active": True,
                "enforce_sso": False,
            },
        )()
        create_sso_config(request, str(org.pk), body=body)

        log = AuditLog.objects.filter(action="sso_config_created").first()
        assert log is not None
        assert log.resource_type == "sso_configuration"
        assert log.actor_id is not None
        assert log.actor_email == admin.email
        assert log.metadata["organization_id"] == str(org.pk)
        assert log.metadata["provider_type"] == "saml"

    def test_update_audit_log(self, rf, org):
        """Updating SSO config creates an audit log entry with changes."""
        SSOConfiguration.objects.create(
            organization=org, provider_type="saml", is_active=False
        )
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "patch", f"/{org.pk}/sso", admin)
        body = type(
            "B",
            (),
            {
                "provider_type": None,
                "metadata_url": None,
                "entity_id": None,
                "certificate": None,
                "is_active": True,
                "enforce_sso": None,
            },
        )()
        update_sso_config(request, str(org.pk), body=body)

        log = AuditLog.objects.filter(action="sso_config_updated").first()
        assert log is not None
        assert log.changes["is_active"]["old"] is False
        assert log.changes["is_active"]["new"] is True

    def test_delete_audit_log(self, rf, org):
        """Deleting SSO config creates an audit log entry."""
        sso = SSOConfiguration.objects.create(organization=org)
        config_id = str(sso.pk)
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "delete", f"/{org.pk}/sso", admin)
        delete_sso_config(request, str(org.pk))

        log = AuditLog.objects.filter(action="sso_config_deleted").first()
        assert log is not None
        assert log.resource_id == config_id
        assert log.metadata["organization_id"] == str(org.pk)


# ===========================================================================
# SSO ENFORCEMENT TESTS
# ===========================================================================


class TestSSOEnforcement:
    """Test SSO enforcement in SecurityPolicyMiddleware."""

    @pytest.fixture
    def middleware(self):
        return SecurityPolicyMiddleware(get_response=lambda r: None)

    def test_no_sso_no_enforcement(self, org):
        """Without SSO config, sso_enforced is False."""
        user = _make_member(org, OrganizationRole.MEMBER)
        _, _, _, sso_enforced = get_effective_policy(user)
        assert sso_enforced is False

    def test_inactive_sso_no_enforcement(self, org):
        """SSO config with is_active=False doesn't enforce."""
        SSOConfiguration.objects.create(
            organization=org, is_active=False, enforce_sso=True
        )
        user = _make_member(org, OrganizationRole.MEMBER)
        _, _, _, sso_enforced = get_effective_policy(user)
        assert sso_enforced is False

    def test_active_no_enforce_no_enforcement(self, org):
        """SSO config with enforce_sso=False doesn't block."""
        SSOConfiguration.objects.create(
            organization=org, is_active=True, enforce_sso=False
        )
        user = _make_member(org, OrganizationRole.MEMBER)
        _, _, _, sso_enforced = get_effective_policy(user)
        assert sso_enforced is False

    def test_active_enforce_sso(self, org):
        """Active SSO config with enforce_sso=True triggers enforcement."""
        SSOConfiguration.objects.create(
            organization=org, is_active=True, enforce_sso=True
        )
        user = _make_member(org, OrganizationRole.MEMBER)
        _, _, _, sso_enforced = get_effective_policy(user)
        assert sso_enforced is True

    def test_enforce_sso_blocks_non_sso_user(self, rf, org, middleware):
        """Middleware returns 403 for non-SSO user when SSO is enforced."""
        SSOConfiguration.objects.create(
            organization=org, is_active=True, enforce_sso=True
        )
        user = _make_member(org, OrganizationRole.MEMBER)

        request = rf.get("/api/v1/some-endpoint")
        request.user = user
        request.session = type(
            "S",
            (),
            {
                "is_empty": lambda self: False,
                "get": lambda self, k, d=None: None,
                "__setitem__": lambda self, k, v: None,
                "session_key": "test-key",
            },
        )()

        response = middleware.process_request(request)
        assert response is not None
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["code"] == "sso_required"

    def test_exempt_paths_bypass_sso_enforcement(self, rf, org, middleware):
        """SSO enforcement doesn't apply to exempt paths."""
        SSOConfiguration.objects.create(
            organization=org, is_active=True, enforce_sso=True
        )
        user = _make_member(org, OrganizationRole.MEMBER)

        request = rf.get("/accounts/login/")
        request.user = user
        request.session = type(
            "S",
            (),
            {
                "is_empty": lambda self: False,
                "get": lambda self, k, d=None: None,
                "__setitem__": lambda self, k, v: None,
                "session_key": "test-key",
            },
        )()

        response = middleware.process_request(request)
        assert response is None

    def test_multi_org_sso_enforcement(self):
        """If any org enforces SSO, enforcement applies."""
        org1 = Organization.objects.create(name="No SSO Org")
        org2 = Organization.objects.create(name="SSO Org")
        SSOConfiguration.objects.create(
            organization=org2, is_active=True, enforce_sso=True
        )
        user = UserFactory()
        OrganizationMembership.objects.create(
            organization=org1, user=user, role=OrganizationRole.MEMBER
        )
        OrganizationMembership.objects.create(
            organization=org2, user=user, role=OrganizationRole.MEMBER
        )

        _, _, _, sso_enforced = get_effective_policy(user)
        assert sso_enforced is True


# ===========================================================================
# SP METADATA ENDPOINT TESTS
# ===========================================================================


class TestSPMetadataEndpoint:
    """Test the SP metadata endpoint."""

    def test_get_metadata(self, rf, org):
        """Returns SP metadata with correct URLs."""
        SSOConfiguration.objects.create(organization=org)
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "get", f"/{org.pk}/sso/metadata", admin)
        status, data = get_sp_metadata(request, str(org.pk))
        assert status == 200
        assert org.slug in data["entity_id"]
        assert org.slug in data["acs_url"]
        assert org.slug in data["slo_url"]
        assert (
            data["name_id_format"]
            == "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
        )
        assert data["org_slug"] == org.slug

    def test_metadata_without_config_returns_404(self, rf, org):
        """SP metadata returns 404 if no SSO config exists."""
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "get", f"/{org.pk}/sso/metadata", admin)
        status, data = get_sp_metadata(request, str(org.pk))
        assert status == 404

    def test_metadata_requires_admin(self, rf, org):
        """SP metadata requires admin+ role."""
        SSOConfiguration.objects.create(organization=org)
        viewer = _make_member(org, OrganizationRole.VIEWER)
        request = _authed_request(rf, "get", f"/{org.pk}/sso/metadata", viewer)
        with pytest.raises(UnauthorizedAccessError):
            get_sp_metadata(request, str(org.pk))

    def test_metadata_urls_use_site_url(self, rf, org, settings):
        """SP metadata URLs are based on SITE_URL setting."""
        SSOConfiguration.objects.create(organization=org)
        settings.SITE_URL = "https://custom.example.com"
        admin = _make_member(org, OrganizationRole.ADMIN)
        request = _authed_request(rf, "get", f"/{org.pk}/sso/metadata", admin)
        status, data = get_sp_metadata(request, str(org.pk))
        assert status == 200
        assert data["entity_id"].startswith("https://custom.example.com")
        assert data["acs_url"].startswith("https://custom.example.com")
