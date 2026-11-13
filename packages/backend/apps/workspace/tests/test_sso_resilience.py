"""SSO Resilience tests — emergency bypass login, bypass rate limiting,
certificate expiry detection, force logout, multi-org IdP selection,
and SAML email mismatch handling.

Covers US-039 acceptance criteria.
"""

import json
import uuid
from datetime import datetime, timedelta

import pytest
from django.core.cache import cache
from django.test import Client, RequestFactory

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SSOConfiguration,
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
    return Organization.objects.create(name="SSO Resilience Org")


@pytest.fixture
def owner(org):
    user = UserFactory(password="ownerpass123")
    OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.OWNER
    )
    return user


@pytest.fixture
def member(org):
    user = UserFactory(password="memberpass123")
    OrganizationMembership.objects.create(
        organization=org, user=user, role=OrganizationRole.MEMBER
    )
    return user


@pytest.fixture
def sso_config(org):
    """Create a basic active SSO config with bypass enabled."""
    return SSOConfiguration.objects.create(
        organization=org,
        provider_type="saml",
        is_active=True,
        enforce_sso=True,
        emergency_bypass_enabled=True,
    )


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear Django cache between tests for rate limiting."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def auth_client(owner):
    """Authenticated test client for the org owner."""
    from dj_rest_auth.models import get_token_model

    token_model = get_token_model()
    token, _ = token_model.objects.get_or_create(user=owner)
    return Client(headers={"authorization": f"Bearer {token.key}"})


@pytest.fixture
def member_client(member):
    """Authenticated test client for an org member."""
    from dj_rest_auth.models import get_token_model

    token_model = get_token_model()
    token, _ = token_model.objects.get_or_create(user=member)
    return Client(headers={"authorization": f"Bearer {token.key}"})


# ===========================================================================
# EMERGENCY BYPASS TESTS
# ===========================================================================


class TestSSOEmergencyBypass:
    """Emergency bypass login when SSO is enforced but IdP is down."""

    def test_model_auto_generates_bypass_code(self, org):
        """Bypass code is auto-generated on creation."""
        config = SSOConfiguration.objects.create(organization=org, provider_type="saml")
        assert config.emergency_bypass_code
        assert len(config.emergency_bypass_code) > 20

    def test_model_bypass_fields_defaults(self, org):
        """Emergency bypass defaults to disabled."""
        config = SSOConfiguration.objects.create(organization=org, provider_type="saml")
        assert config.emergency_bypass_enabled is False

    def test_bypass_login_success(self, org, sso_config, member):
        """Successful emergency bypass login with valid code and credentials."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data
        assert data["user_id"] == member.pk
        assert data["email"] == member.email

    def test_bypass_creates_audit_log(self, org, sso_config, member):
        """Bypass login creates an audit log with 'sso_emergency_bypass' action."""
        client = Client()
        client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        log = AuditLog.objects.filter(action="sso_emergency_bypass").first()
        assert log is not None
        assert log.actor_email == member.email
        assert log.metadata["organization_slug"] == org.slug

    def test_bypass_invalid_code(self, org, sso_config, member):
        """Invalid bypass code returns 403."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=wrong-code",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "Invalid emergency bypass code" in resp.json()["detail"]

    def test_bypass_no_code(self, org, sso_config, member):
        """Missing bypass code returns 403."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 403

    def test_bypass_disabled(self, org, member):
        """Bypass returns 403 when emergency_bypass_enabled=False."""
        config = SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            emergency_bypass_enabled=False,
        )
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={config.emergency_bypass_code}",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "not enabled" in resp.json()["detail"]

    def test_bypass_wrong_password(self, org, sso_config, member):
        """Wrong password returns 400."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}",
            data=json.dumps({"email": member.email, "password": "wrongpass"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "Invalid credentials" in resp.json()["detail"]

    def test_bypass_nonexistent_user(self, org, sso_config):
        """Nonexistent user email returns 400."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}",
            data=json.dumps({"email": "nobody@example.com", "password": "pass"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bypass_non_member(self, org, sso_config):
        """User not in the org returns 403."""
        outsider = UserFactory(password="outsiderpass")
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}",
            data=json.dumps({"email": outsider.email, "password": "outsiderpass"}),
            content_type="application/json",
        )
        assert resp.status_code == 403
        assert "not a member" in resp.json()["detail"]

    def test_bypass_nonexistent_org(self):
        """Nonexistent org slug returns 404."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/sso-bypass/nonexistent-org?code=abc",
            data=json.dumps({"email": "a@b.com", "password": "pass"}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_bypass_no_sso_config(self, org, member):
        """Org without SSO config returns 404."""
        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=abc",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 404


# ===========================================================================
# RATE LIMITING TESTS
# ===========================================================================


class TestSSOBypassRateLimiting:
    """Rate limiting: max 5 attempts per org per minute."""

    def test_rate_limit_enforced(self, org, sso_config, member):
        """6th attempt within a minute returns 429."""
        client = Client()
        url = f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}"
        body = json.dumps({"email": member.email, "password": "memberpass123"})

        # First 5 should work (even with correct creds)
        for i in range(5):
            resp = client.post(url, data=body, content_type="application/json")
            assert resp.status_code == 200, (
                f"Attempt {i + 1} failed: {resp.status_code}"
            )

        # 6th should be rate-limited
        resp = client.post(url, data=body, content_type="application/json")
        assert resp.status_code == 429
        assert "Too many" in resp.json()["detail"]

    def test_rate_limit_per_org(self, sso_config, member):
        """Rate limit is per-org, not global."""
        org2 = Organization.objects.create(name="Other Org")
        user2 = UserFactory(password="user2pass")
        OrganizationMembership.objects.create(
            organization=org2, user=user2, role=OrganizationRole.MEMBER
        )
        sso2 = SSOConfiguration.objects.create(
            organization=org2,
            provider_type="saml",
            is_active=True,
            emergency_bypass_enabled=True,
        )

        client = Client()
        # Exhaust rate limit on org1
        url1 = f"/api/v1/workspace/auth/sso-bypass/{sso_config.organization.slug}?code={sso_config.emergency_bypass_code}"
        body1 = json.dumps({"email": member.email, "password": "memberpass123"})
        for _ in range(5):
            client.post(url1, data=body1, content_type="application/json")

        # org2 should still work
        url2 = f"/api/v1/workspace/auth/sso-bypass/{org2.slug}?code={sso2.emergency_bypass_code}"
        body2 = json.dumps({"email": user2.email, "password": "user2pass"})
        resp = client.post(url2, data=body2, content_type="application/json")
        assert resp.status_code == 200

    def test_rate_limit_counts_failed_attempts(self, org, sso_config, member):
        """Failed attempts also count toward rate limit."""
        client = Client()
        url = f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso_config.emergency_bypass_code}"
        bad_body = json.dumps({"email": member.email, "password": "wrongpass"})
        good_body = json.dumps({"email": member.email, "password": "memberpass123"})

        # 5 failed attempts
        for _ in range(5):
            client.post(url, data=bad_body, content_type="application/json")

        # 6th attempt (even valid) should be rate limited
        resp = client.post(url, data=good_body, content_type="application/json")
        assert resp.status_code == 429


# ===========================================================================
# CERTIFICATE EXPIRY TESTS
# ===========================================================================


class TestCertificateExpiryDetection:
    """Daily Celery task checks SSO certificates for expiry."""

    def _make_self_signed_cert(self, not_after):
        """Create a self-signed X.509 certificate expiring at the given datetime."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, "test"),
            ]
        )
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime(2020, 1, 1))
            .not_valid_after(not_after)
            .sign(key, hashes.SHA256())
        )
        return cert.public_bytes(serialization.Encoding.PEM).decode()

    def test_expired_certificate_creates_critical_log(self, org):
        """Expired certificate creates audit log with severity=critical."""
        cert_pem = self._make_self_signed_cert(datetime(2025, 1, 1))
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            certificate=cert_pem,
        )

        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert org.name in result
        assert result[org.name]["status"] == "expired"

        log = AuditLog.objects.filter(
            resource_type="sso_certificate",
            metadata__severity="critical",
        ).first()
        assert log is not None
        assert "expired" in log.metadata["message"].lower()

    def test_expiring_soon_certificate_creates_warning_log(self, org):
        """Certificate expiring within 30 days creates warning audit log."""
        cert_pem = self._make_self_signed_cert(datetime.utcnow() + timedelta(days=15))
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            certificate=cert_pem,
        )

        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert org.name in result
        assert result[org.name]["status"] == "expiring_soon"

        log = AuditLog.objects.filter(
            resource_type="sso_certificate",
            metadata__severity="warning",
        ).first()
        assert log is not None

    def test_valid_certificate_no_log(self, org):
        """Certificate valid for >30 days creates no log entries."""
        cert_pem = self._make_self_signed_cert(datetime.utcnow() + timedelta(days=365))
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            certificate=cert_pem,
        )

        initial_count = AuditLog.objects.count()
        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert result[org.name]["status"] == "ok"
        assert AuditLog.objects.count() == initial_count

    def test_inactive_config_skipped(self, org):
        """Inactive SSO configs are not checked."""
        cert_pem = self._make_self_signed_cert(datetime(2025, 1, 1))
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=False,
            certificate=cert_pem,
        )

        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert org.name not in result

    def test_empty_certificate_skipped(self, org):
        """SSO config with empty certificate is skipped."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            certificate="",
        )

        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert org.name not in result

    def test_invalid_certificate_handled_gracefully(self, org):
        """Invalid certificate data doesn't crash the task."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            certificate="not-a-real-cert",
        )

        from apps.compliance.tasks import check_sso_certificate_expiry

        result = check_sso_certificate_expiry()
        assert org.name not in result

    def test_beat_schedule_entry(self):
        """Certificate check is in CELERY_BEAT_SCHEDULE."""
        from django.conf import settings

        assert "check-sso-certificate-expiry" in settings.CELERY_BEAT_SCHEDULE
        entry = settings.CELERY_BEAT_SCHEDULE["check-sso-certificate-expiry"]
        assert entry["task"] == "apps.compliance.tasks.check_sso_certificate_expiry"


# ===========================================================================
# FORCE LOGOUT TESTS
# ===========================================================================


class TestForceLogout:
    """POST /{org_id}/force-logout invalidates all member sessions."""

    def test_force_logout_success(self, org, owner, member, auth_client):
        """Admin can force-logout all members."""
        from apps.compliance.models import UserSession

        # Create tracked sessions for members
        UserSession.objects.create(user=owner, session_key="owner-sess-001")
        UserSession.objects.create(user=member, session_key="member-sess-001")

        resp = auth_client.post(
            f"/api/v1/workspace/organizations/{org.pk}/force-logout"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "2 member(s)" in data["message"]

        # Sessions should be cleared
        assert UserSession.objects.filter(user=owner).count() == 0
        assert UserSession.objects.filter(user=member).count() == 0

    def test_force_logout_creates_audit_log(self, org, owner, auth_client):
        """Force logout creates audit log entry."""
        auth_client.post(f"/api/v1/workspace/organizations/{org.pk}/force-logout")

        log = AuditLog.objects.filter(action="sso_force_logout").first()
        assert log is not None
        assert log.actor_email == owner.email
        assert log.metadata["organization_name"] == org.name

    def test_force_logout_requires_admin(self, org, member_client):
        """Member (non-admin) cannot force logout."""
        resp = member_client.post(
            f"/api/v1/workspace/organizations/{org.pk}/force-logout"
        )
        assert resp.status_code == 401

    def test_force_logout_nonexistent_org(self, auth_client):
        """Force logout on nonexistent org returns 404."""
        fake_id = str(uuid.uuid4())
        resp = auth_client.post(
            f"/api/v1/workspace/organizations/{fake_id}/force-logout"
        )
        assert resp.status_code == 404

    def test_force_logout_no_sessions(self, org, owner, auth_client):
        """Force logout with no active sessions still succeeds."""
        resp = auth_client.post(
            f"/api/v1/workspace/organizations/{org.pk}/force-logout"
        )
        assert resp.status_code == 200
        assert "0 session(s)" in resp.json()["message"]


# ===========================================================================
# MULTI-ORG IDP SELECTION TESTS
# ===========================================================================


class TestMultiOrgIdPSelection:
    """Org selection endpoint returns SSO-enabled orgs for the user."""

    def test_returns_sso_orgs(self, org, owner, sso_config, auth_client):
        """Returns list of SSO-enabled orgs for the user."""
        resp = auth_client.get("/api/v1/workspace/sso/org-selection")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["organization_id"] == str(org.pk)
        assert data[0]["organization_name"] == org.name
        assert data[0]["provider_type"] == "saml"

    def test_excludes_inactive_sso(self, org, owner, auth_client):
        """Inactive SSO configs are excluded."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=False,
        )
        resp = auth_client.get("/api/v1/workspace/sso/org-selection")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_excludes_orgs_without_sso(self, org, owner, auth_client):
        """Orgs without SSO config are excluded."""
        resp = auth_client.get("/api/v1/workspace/sso/org-selection")
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_multiple_sso_orgs(self, org, owner, sso_config, auth_client):
        """Returns multiple SSO orgs when user is member of several."""
        org2 = Organization.objects.create(name="Second SSO Org")
        OrganizationMembership.objects.create(
            organization=org2, user=owner, role=OrganizationRole.MEMBER
        )
        SSOConfiguration.objects.create(
            organization=org2,
            provider_type="oidc",
            is_active=True,
        )
        resp = auth_client.get("/api/v1/workspace/sso/org-selection")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        provider_types = {d["provider_type"] for d in data}
        assert provider_types == {"saml", "oidc"}


# ===========================================================================
# SAML EMAIL MISMATCH TESTS
# ===========================================================================


class TestSAMLEmailMismatch:
    """SAML assertion email matching via email_hash lookup."""

    def test_matching_email(self, member):
        """Matching SAML email returns matched=True."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/saml/verify-email",
            data=json.dumps({"email": member.email}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched"] is True
        assert data["user_id"] == member.pk

    def test_nonexistent_email(self):
        """Non-matching SAML email returns 404."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/saml/verify-email",
            data=json.dumps({"email": "unknown@nowhere.com"}),
            content_type="application/json",
        )
        assert resp.status_code == 404
        assert "does not match" in resp.json()["detail"]

    def test_empty_email(self):
        """Empty email returns 404."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/saml/verify-email",
            data=json.dumps({"email": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 404

    def test_case_insensitive_match(self, member):
        """Email matching is case-insensitive."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/saml/verify-email",
            data=json.dumps({"email": member.email.upper()}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["matched"] is True

    def test_invalid_json_body(self):
        """Invalid JSON body returns 404."""
        client = Client()
        resp = client.post(
            "/api/v1/workspace/auth/saml/verify-email",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 404


# ===========================================================================
# SSO CONFIG UPDATE (EMERGENCY BYPASS FIELD) TESTS
# ===========================================================================


class TestSSOConfigEmergencyBypassUpdate:
    """Verify emergency_bypass_enabled can be toggled via SSO config PATCH."""

    def test_enable_bypass_via_update(self, org, owner, rf):
        """Admin can enable emergency bypass via SSO config update."""
        from apps.workspace.org_api import update_sso_config
        from apps.workspace.org_schemas import UpdateSSOConfigRequest

        config = SSOConfiguration.objects.create(
            organization=org, provider_type="saml", is_active=True
        )
        assert config.emergency_bypass_enabled is False

        request = rf.patch(
            f"/organizations/{org.pk}/sso",
            data=json.dumps({"emergency_bypass_enabled": True}),
            content_type="application/json",
        )
        request.auth = owner
        request.request_id = "test"
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        body = UpdateSSOConfigRequest(emergency_bypass_enabled=True)
        status, data = update_sso_config(request, str(org.pk), body=body)
        assert status == 200
        config.refresh_from_db()
        assert config.emergency_bypass_enabled is True

    def test_bypass_enabled_in_sso_config_response(self, org, owner, rf):
        """emergency_bypass_enabled is included in SSO config API response."""
        from apps.workspace.org_api import get_sso_config

        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            emergency_bypass_enabled=True,
        )

        request = rf.get(f"/organizations/{org.pk}/sso")
        request.auth = owner
        request.request_id = "test"
        request.META["REMOTE_ADDR"] = "10.0.0.1"

        status, data = get_sso_config(request, str(org.pk))
        assert status == 200
        assert data["emergency_bypass_enabled"] is True
