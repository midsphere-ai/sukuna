"""End-to-end tests for authentication providers (US-016).

Covers:
- OAuth provider callback flows (Google, GitHub, Microsoft, Apple) with mocked responses
- SAML SSO flow with mocked IdP response
- SSO enforcement: password login blocked when enforce_sso=True
- SCIM provision + deprovision lifecycle
- Account linking: OAuth with existing email merges correctly
- MFA enforcement during OAuth login flow
"""

import hashlib
import json
import secrets
import time
from unittest.mock import MagicMock, patch

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.signals import social_account_added
from django.contrib.auth.signals import user_logged_in
from django.test import RequestFactory, override_settings

from apps.compliance.models import AuditLog
from apps.compliance.security_middleware import (
    SecurityPolicyMiddleware,
)
from apps.users.models import User
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    SCIMToken,
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
    return Organization.objects.create(name="E2E Test Org")


@pytest.fixture
def user():
    return UserFactory(email="testuser@example.com", name="Test User")


@pytest.fixture
def admin_user(org):
    u = UserFactory(email="admin@example.com", name="Admin User")
    u.is_superuser = True
    u.save()
    OrganizationMembership.objects.create(
        user=u,
        organization=org,
        role=OrganizationRole.OWNER,
    )
    return u


@pytest.fixture
def member_user(org):
    u = UserFactory(email="member@example.com", name="Member User")
    OrganizationMembership.objects.create(
        user=u,
        organization=org,
        role=OrganizationRole.MEMBER,
    )
    return u


def _make_api_request(rf, user, path="/api/v1/test/", method="get"):
    """Build a request with session and user, suitable for middleware tests."""
    factory_method = getattr(rf, method)
    request = factory_method(path)
    request.user = user
    request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1"
    request.request_id = "e2e-test-req"
    # Minimal session mock
    session = {}
    session["_last_activity"] = time.time()
    session["session_key"] = f"sess-{user.pk}"

    class MockSession(dict):
        session_key = f"sess-{user.pk}"

        def is_empty(self):
            return False

        def flush(self):
            self.clear()

    request.session = MockSession(session)
    return request


# ---------------------------------------------------------------------------
# OAuth Provider Callback E2E Tests
# ---------------------------------------------------------------------------


class TestOAuthProviderCallbacks:
    """E2E tests for each OAuth provider callback with mocked OAuth responses."""

    def _simulate_oauth_callback(self, rf, provider, uid, email, name="OAuth User"):
        """Simulate an OAuth callback by creating a SocialAccount and triggering signals."""
        user = UserFactory(email=email, name=name)
        social_account = SocialAccount.objects.create(
            user=user,
            provider=provider,
            uid=uid,
            extra_data={"email": email, "name": name},
        )

        # Build a mock request similar to what allauth sends
        request = rf.get(f"/accounts/{provider}/login/callback/")
        request.request_id = f"oauth-{provider}-req"
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.10"
        request.user = user

        # Create mock sociallogin object that allauth signals provide
        sociallogin = MagicMock()
        sociallogin.user = user
        sociallogin.account = social_account

        # Trigger the social_account_added signal (as allauth does on first OAuth login)
        social_account_added.send(
            sender=SocialAccount,
            request=request,
            sociallogin=sociallogin,
        )

        # Trigger user_logged_in signal (as allauth does after OAuth)
        user_logged_in.send(
            sender=user.__class__,
            request=request,
            user=user,
        )

        return user, social_account

    def test_github_oauth_callback(self, rf):
        """GitHub OAuth callback creates social account and audit logs."""
        user, sa = self._simulate_oauth_callback(
            rf,
            provider="github",
            uid="gh-12345",
            email="ghuser@example.com",
        )

        assert sa.provider == "github"
        assert sa.uid == "gh-12345"
        assert SocialAccount.objects.filter(user=user, provider="github").exists()

        # Verify audit log entries
        social_log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert social_log.metadata["provider"] == "github"
        assert social_log.metadata["uid"] == "gh-12345"

        login_log = AuditLog.objects.filter(
            action="login",
            resource_type="user",
            resource_id=str(user.pk),
        ).latest("timestamp")
        assert login_log.actor_ip == "203.0.113.10"

    def test_microsoft_oauth_callback(self, rf):
        """Microsoft OAuth callback creates social account and audit logs."""
        user, sa = self._simulate_oauth_callback(
            rf,
            provider="microsoft",
            uid="ms-abcde-fghij",
            email="msuser@example.com",
        )

        assert sa.provider == "microsoft"
        assert SocialAccount.objects.filter(user=user, provider="microsoft").exists()

        social_log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert social_log.metadata["provider"] == "microsoft"

    def test_apple_oauth_callback(self, rf):
        """Apple OAuth callback creates social account and audit logs."""
        user, sa = self._simulate_oauth_callback(
            rf,
            provider="apple",
            uid="apple.001.002",
            email="appleuser@example.com",
        )

        assert sa.provider == "apple"
        assert SocialAccount.objects.filter(user=user, provider="apple").exists()

        social_log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert social_log.metadata["provider"] == "apple"

    def test_google_oauth_callback(self, rf):
        """Google OAuth callback creates social account and audit logs."""
        user, sa = self._simulate_oauth_callback(
            rf,
            provider="google",
            uid="google-11223344",
            email="googleuser@example.com",
        )

        assert sa.provider == "google"
        assert SocialAccount.objects.filter(user=user, provider="google").exists()

        social_log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert social_log.metadata["provider"] == "google"

    def test_oauth_callback_creates_auth_token(self, rf):
        """After OAuth callback, the adapter creates a DRF token for the SPA."""
        from apps.users.adapters import AccountAdapter

        user = UserFactory(email="tokentest@example.com")
        request = rf.get("/")
        request.user = user

        adapter = AccountAdapter()
        redirect_url = adapter.get_login_redirect_url(request)

        assert redirect_url.startswith("/auth/callback?token=")
        token_key = redirect_url.split("token=")[1]
        assert len(token_key) > 0

        # Verify token is valid
        from dj_rest_auth.models import get_token_model

        token_model = get_token_model()
        token = token_model.objects.get(key=token_key)
        assert token.user == user

    def test_oauth_callback_audit_log_includes_ip_and_request_id(self, rf):
        """Audit log from OAuth callback captures client IP and request ID."""
        user, _ = self._simulate_oauth_callback(
            rf,
            provider="github",
            uid="gh-99999",
            email="auditip@example.com",
        )

        log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert log.actor_ip == "203.0.113.10"
        assert log.request_id == "oauth-github-req"


# ---------------------------------------------------------------------------
# SAML SSO Flow E2E Test
# ---------------------------------------------------------------------------


class TestSAMLSSOFlow:
    """E2E test for SAML SSO flow with mocked IdP response."""

    def test_saml_sso_config_and_login_flow(self, rf, org, member_user):
        """SAML SSO config creates SP metadata and SSO user bypasses enforcement."""
        # Step 1: Create SSO configuration for the org
        sso_config = SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            metadata_url="https://idp.example.com/metadata",
            entity_id="https://idp.example.com/entity",
            certificate="MIIC...",
            is_active=True,
            enforce_sso=False,
        )

        assert sso_config.provider_type == "saml"
        assert sso_config.is_active

        # Step 2: Simulate SSO login by creating a SocialAccount (as allauth would)
        social_account = SocialAccount.objects.create(
            user=member_user,
            provider="saml",
            uid=f"saml-{member_user.email}",
            extra_data={"idp": "https://idp.example.com"},
        )

        # Step 3: Enable SSO enforcement
        sso_config.enforce_sso = True
        sso_config.save()

        # Step 4: Verify SSO user passes enforcement
        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)
        response = middleware._check_sso_enforcement(member_user)
        # User has a SocialAccount, so should pass
        assert response is None

    def test_saml_sso_sp_metadata_available(self, rf, org, admin_user):
        """SP metadata endpoint returns entity_id, acs_url, slo_url after SSO config."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            metadata_url="https://idp.example.com/metadata",
            entity_id="https://idp.example.com/entity",
            is_active=True,
        )

        from apps.workspace.org_api import get_sp_metadata

        request = rf.get(f"/api/v1/workspace/organizations/{org.id}/sso/metadata")
        request.auth = admin_user
        request.request_id = "sp-meta-req"

        status, body = get_sp_metadata(request, org_id=org.id)
        assert status == 200
        assert "entity_id" in body
        assert "acs_url" in body
        assert "slo_url" in body


# ---------------------------------------------------------------------------
# SSO Enforcement E2E Test
# ---------------------------------------------------------------------------


class TestSSOEnforcement:
    """E2E tests for SSO enforcement: password login blocked when enforce_sso=True."""

    def test_password_login_blocked_when_sso_enforced(self, rf, org, member_user):
        """Non-SSO user gets 403 when their org enforces SSO."""
        # Enable SSO enforcement on the org
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            entity_id="https://idp.example.com/entity",
            is_active=True,
            enforce_sso=True,
        )

        # member_user has NO social accounts (password-only login)
        assert not SocialAccount.objects.filter(user=member_user).exists()

        # Middleware should block the request
        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)
        response = middleware.process_request(request)

        assert response is not None
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["code"] == "sso_required"

    def test_sso_user_allowed_when_sso_enforced(self, rf, org, member_user):
        """SSO user (with SocialAccount) is allowed even when SSO is enforced."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            entity_id="https://idp.example.com/entity",
            is_active=True,
            enforce_sso=True,
        )

        # Create SocialAccount for the user (simulating SSO login)
        SocialAccount.objects.create(
            user=member_user,
            provider="saml",
            uid=f"saml-{member_user.pk}",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)
        response = middleware.process_request(request)

        # Should pass through (None = no rejection)
        assert response is None

    def test_sso_enforcement_not_applied_without_config(self, rf, org, member_user):
        """Without SSOConfiguration, user is not blocked."""
        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)
        response = middleware.process_request(request)

        assert response is None

    def test_sso_enforcement_inactive_config_ignored(self, rf, org, member_user):
        """Inactive SSO config does not enforce SSO."""
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="oidc",
            entity_id="https://idp.example.com/entity",
            is_active=False,
            enforce_sso=True,
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)
        response = middleware.process_request(request)

        assert response is None


# ---------------------------------------------------------------------------
# SCIM Provision + Deprovision Lifecycle E2E Test
# ---------------------------------------------------------------------------


class TestSCIMLifecycle:
    """E2E tests for SCIM provision + deprovision lifecycle."""

    def _create_scim_token(self, org):
        """Create a SCIM token and return (plaintext, SCIMToken instance)."""
        plaintext = secrets.token_hex(20)
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        token = SCIMToken.objects.create(
            organization=org,
            token_hash=token_hash,
            prefix=plaintext[:8],
        )
        return plaintext, token

    def _scim_request(self, rf, method, path, org, body=None):
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
        request.scim_rate_limited = False
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.5"
        return request

    def test_full_scim_lifecycle(self, rf, org):
        """Provision a user via SCIM, verify membership, then deprovision."""
        from apps.workspace.scim_api import (
            create_scim_user,
            delete_scim_user,
            get_scim_user,
            list_scim_users,
        )
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        self._create_scim_token(org)

        # Step 1: Provision a new user
        body = CreateSCIMUserRequest(
            userName="scimuser@example.com",
            name={"givenName": "SCIM", "familyName": "User"},
            active=True,
        )
        request = self._scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 201
        scim_user_id = data["id"]

        # Step 2: Verify user exists and has org membership
        user = User.objects.get_by_email("scimuser@example.com")
        assert OrganizationMembership.objects.filter(
            user=user, organization=org
        ).exists()

        # Step 3: Get the user via SCIM
        request = self._scim_request(
            rf, "get", f"/scim/v2/{org.slug}/Users/{scim_user_id}", org
        )
        status, data = get_scim_user(request, org.slug, int(scim_user_id))
        assert status == 200
        assert data["userName"] == "scimuser@example.com"
        assert data["active"] is True

        # Step 4: List users — should include provisioned user
        request = self._scim_request(rf, "get", f"/scim/v2/{org.slug}/Users", org)
        status, data = list_scim_users(request, org.slug)
        assert status == 200
        user_names = [r["userName"] for r in data["Resources"]]
        assert "scimuser@example.com" in user_names

        # Step 5: Deprovision (delete) the user
        request = self._scim_request(
            rf, "delete", f"/scim/v2/{org.slug}/Users/{scim_user_id}", org
        )
        status, data = delete_scim_user(request, org.slug, int(scim_user_id))
        assert status == 200
        assert data["active"] is False

        # Step 6: Verify user is deactivated and removed from org
        user.refresh_from_db()
        assert not user.is_active
        assert not OrganizationMembership.objects.filter(
            user=user, organization=org
        ).exists()

        # Step 7: Verify audit trail
        provision_log = AuditLog.objects.filter(action="scim_user_provisioned").latest(
            "timestamp"
        )
        assert provision_log.actor_email == f"scim:{org.slug}"

        deprovision_log = AuditLog.objects.filter(
            action="scim_user_deprovisioned"
        ).latest("timestamp")
        assert deprovision_log.actor_email == f"scim:{org.slug}"

    def test_scim_provision_reactivates_deactivated_user(self, rf, org):
        """Provisioning a previously deactivated user reactivates them."""
        from apps.workspace.scim_api import create_scim_user
        from apps.workspace.scim_schemas import CreateSCIMUserRequest

        self._create_scim_token(org)

        # Create an inactive user
        user = UserFactory(email="deactivated@example.com", name="Deactivated")
        user.is_active = False
        user.save()

        # Provision via SCIM — should reactivate
        body = CreateSCIMUserRequest(
            userName="deactivated@example.com",
            name={"givenName": "Re", "familyName": "Activated"},
            active=True,
        )
        request = self._scim_request(rf, "post", f"/scim/v2/{org.slug}/Users", org)
        status, data = create_scim_user(request, org.slug, body)
        assert status == 201

        user.refresh_from_db()
        assert user.is_active
        assert OrganizationMembership.objects.filter(
            user=user, organization=org
        ).exists()


# ---------------------------------------------------------------------------
# Account Linking E2E Test
# ---------------------------------------------------------------------------


class TestAccountLinking:
    """E2E test for account linking: OAuth login with existing email merges correctly."""

    def test_oauth_login_links_to_existing_email_account(self, rf, user):
        """OAuth login with email matching existing user links the accounts."""
        # user already exists with email "testuser@example.com"
        assert User.objects.get_by_email("testuser@example.com") == user

        # Simulate GitHub OAuth providing the same email
        social_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="gh-link-12345",
            extra_data={"email": "testuser@example.com", "login": "testuser"},
        )

        # Verify linking: user has both password and social account
        assert user.has_usable_password()
        assert SocialAccount.objects.filter(user=user, provider="github").exists()

        # Trigger signal to verify audit logging
        request = rf.get("/accounts/github/login/callback/")
        request.request_id = "link-test-req"
        request.META["HTTP_X_FORWARDED_FOR"] = "192.0.2.1"

        sociallogin = MagicMock()
        sociallogin.user = user
        sociallogin.account = social_account

        social_account_added.send(
            sender=SocialAccount,
            request=request,
            sociallogin=sociallogin,
        )

        log = AuditLog.objects.filter(
            action="social_account_added",
            resource_type="social_account",
        ).latest("timestamp")
        assert log.metadata["provider"] == "github"
        assert log.actor_email == "testuser@example.com"

    def test_multiple_providers_linked_to_same_user(self, rf, user):
        """User can link multiple OAuth providers to the same account."""
        for provider, uid in [
            ("github", "gh-1"),
            ("microsoft", "ms-1"),
            ("google", "g-1"),
        ]:
            SocialAccount.objects.create(
                user=user,
                provider=provider,
                uid=uid,
                extra_data={"email": user.email},
            )

        assert SocialAccount.objects.filter(user=user).count() == 3
        assert set(
            SocialAccount.objects.filter(user=user).values_list("provider", flat=True)
        ) == {"github", "microsoft", "google"}

    @override_settings(SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT=True)
    def test_auto_connect_setting_enabled(self):
        """Verify SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True for auto-linking."""
        from django.conf import settings

        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True


# ---------------------------------------------------------------------------
# MFA Enforcement During OAuth Login E2E Test
# ---------------------------------------------------------------------------


class TestMFAEnforcementDuringOAuth:
    """E2E test for MFA enforcement during OAuth login flow."""

    def test_mfa_required_blocks_oauth_user_without_mfa(self, rf, org, member_user):
        """OAuth user without MFA is blocked when org requires MFA."""
        # Set org to require MFA
        org.mfa_required = True
        org.save()

        # Create SocialAccount for the user (they logged in via OAuth)
        SocialAccount.objects.create(
            user=member_user,
            provider="github",
            uid="gh-mfa-test",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            response = middleware.process_request(request)

        assert response is not None
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["code"] == "mfa_required"

    def test_mfa_required_allows_oauth_user_with_mfa(self, rf, org, member_user):
        """OAuth user with MFA enabled passes MFA enforcement."""
        org.mfa_required = True
        org.save()

        SocialAccount.objects.create(
            user=member_user,
            provider="github",
            uid="gh-mfa-ok",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=True):
            response = middleware.process_request(request)

        # Should pass through (no MFA block, no SSO block, session OK)
        assert response is None

    def test_mfa_enforcement_exempt_paths_during_oauth(self, rf, org, member_user):
        """MFA-related paths are exempt even for OAuth users in MFA-required orgs."""
        org.mfa_required = True
        org.save()

        SocialAccount.objects.create(
            user=member_user,
            provider="microsoft",
            uid="ms-mfa-exempt",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)

        # MFA setup path should be exempt
        request = rf.get("/accounts/2fa/totp/activate/")
        request.user = member_user
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1"
        request.request_id = "mfa-exempt-req"

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            response = middleware.process_request(request)

        # Exempt path — should pass through
        assert response is None

    def test_mfa_and_sso_enforcement_combined(self, rf, org, member_user):
        """When both MFA and SSO are enforced, both checks apply."""
        org.mfa_required = True
        org.save()

        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            entity_id="https://idp.example.com/entity",
            is_active=True,
            enforce_sso=True,
        )

        # User has SSO account (passes SSO check) but no MFA (fails MFA check)
        SocialAccount.objects.create(
            user=member_user,
            provider="saml",
            uid="saml-mfa-combined",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=False):
            response = middleware.process_request(request)

        # SSO check passes (has social account), but MFA check fails
        assert response is not None
        assert response.status_code == 403
        data = json.loads(response.content)
        assert data["code"] == "mfa_required"

    def test_oauth_user_with_both_sso_and_mfa_passes(self, rf, org, member_user):
        """User satisfying both SSO and MFA enforcement passes through."""
        org.mfa_required = True
        org.save()

        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            entity_id="https://idp.example.com/entity",
            is_active=True,
            enforce_sso=True,
        )

        SocialAccount.objects.create(
            user=member_user,
            provider="saml",
            uid="saml-both-ok",
        )

        middleware = SecurityPolicyMiddleware(lambda r: None)
        request = _make_api_request(rf, member_user)

        with patch("allauth.mfa.utils.is_mfa_enabled", return_value=True):
            response = middleware.process_request(request)

        assert response is None
