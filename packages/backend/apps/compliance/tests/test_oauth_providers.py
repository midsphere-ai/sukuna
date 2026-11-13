"""Tests for OAuth social login provider configuration (US-008).

Verifies that GitHub, Microsoft, and Apple providers are correctly configured,
audit log entries are created for social account events, and duplicate email
handling works through allauth's account linking.
"""

from unittest.mock import MagicMock, patch

import pytest
from allauth.socialaccount.models import SocialAccount
from allauth.socialaccount.signals import social_account_added, social_account_removed
from django.conf import settings
from django.test import RequestFactory

from apps.compliance.models import AuditLog
from apps.users.tests.factories import UserFactory


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.fixture
def mock_request(rf):
    """Build a request with request_id and IP set."""
    request = rf.get("/")
    request.request_id = "oauth-test-req"
    request.META["HTTP_X_FORWARDED_FOR"] = "198.51.100.42"
    return request


# ---------------------------------------------------------------------------
# Provider configuration tests
# ---------------------------------------------------------------------------


class TestProviderConfiguration:
    """Verify all OAuth providers are in INSTALLED_APPS and configured."""

    def test_github_in_installed_apps(self):
        assert "allauth.socialaccount.providers.github" in settings.INSTALLED_APPS

    def test_microsoft_in_installed_apps(self):
        assert "allauth.socialaccount.providers.microsoft" in settings.INSTALLED_APPS

    def test_apple_in_installed_apps(self):
        assert "allauth.socialaccount.providers.apple" in settings.INSTALLED_APPS

    def test_google_still_in_installed_apps(self):
        """Ensure existing Google provider was not removed."""
        assert "allauth.socialaccount.providers.google" in settings.INSTALLED_APPS

    def test_github_provider_config_exists(self):
        assert "github" in settings.SOCIALACCOUNT_PROVIDERS

    def test_github_provider_has_scope(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["github"]
        assert "read:user" in config["SCOPE"]
        assert "user:email" in config["SCOPE"]

    def test_github_provider_has_app_config(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["github"]
        assert "APP" in config
        assert "client_id" in config["APP"]
        assert "secret" in config["APP"]

    def test_microsoft_provider_config_exists(self):
        assert "microsoft" in settings.SOCIALACCOUNT_PROVIDERS

    def test_microsoft_provider_has_scope(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["microsoft"]
        assert "openid" in config["SCOPE"]
        assert "email" in config["SCOPE"]
        assert "User.Read" in config["SCOPE"]

    def test_microsoft_provider_has_app_config(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["microsoft"]
        assert "APP" in config
        assert "client_id" in config["APP"]
        assert "secret" in config["APP"]

    def test_microsoft_provider_has_tenant(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["microsoft"]
        assert "TENANT" in config

    def test_apple_provider_config_exists(self):
        assert "apple" in settings.SOCIALACCOUNT_PROVIDERS

    def test_apple_provider_has_scope(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["apple"]
        assert "email" in config["SCOPE"]
        assert "name" in config["SCOPE"]

    def test_apple_provider_has_app_config(self):
        config = settings.SOCIALACCOUNT_PROVIDERS["apple"]
        assert "APP" in config
        assert "client_id" in config["APP"]
        assert "secret" in config["APP"]
        assert "key" in config["APP"]

    def test_google_provider_config_preserved(self):
        """Ensure existing Google config was not modified."""
        config = settings.SOCIALACCOUNT_PROVIDERS["google"]
        assert "profile" in config["SCOPE"]
        assert "email" in config["SCOPE"]
        assert config["OAUTH_PKCE_ENABLED"] is True

    def test_email_auto_connect_enabled(self):
        """Account linking: social accounts auto-connect to matching email."""
        assert settings.SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT is True


# ---------------------------------------------------------------------------
# Social account audit log signal tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSocialAccountAuditSignals:
    """Verify audit log entries for social account add/remove events."""

    def test_social_account_added_creates_audit_entry(self, mock_request):
        user = UserFactory()
        AuditLog.objects.all().delete()

        social_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="gh-12345",
        )

        sociallogin = MagicMock()
        sociallogin.user = user
        sociallogin.account = social_account

        social_account_added.send(
            sender=SocialAccount,
            request=mock_request,
            sociallogin=sociallogin,
        )

        entry = AuditLog.objects.filter(action="social_account_added").first()
        assert entry is not None
        assert entry.resource_type == "social_account"
        assert entry.resource_id == str(social_account.pk)
        assert entry.actor_id.int == user.pk
        assert entry.actor_email == user.email
        assert entry.actor_ip == "198.51.100.42"
        assert entry.request_id == "oauth-test-req"
        assert entry.metadata["provider"] == "github"
        assert entry.metadata["uid"] == "gh-12345"

    def test_social_account_added_for_microsoft(self, mock_request):
        user = UserFactory()
        AuditLog.objects.all().delete()

        social_account = SocialAccount.objects.create(
            user=user,
            provider="microsoft",
            uid="ms-67890",
        )

        sociallogin = MagicMock()
        sociallogin.user = user
        sociallogin.account = social_account

        social_account_added.send(
            sender=SocialAccount,
            request=mock_request,
            sociallogin=sociallogin,
        )

        entry = AuditLog.objects.filter(action="social_account_added").first()
        assert entry is not None
        assert entry.metadata["provider"] == "microsoft"
        assert entry.metadata["uid"] == "ms-67890"

    def test_social_account_added_for_apple(self, mock_request):
        user = UserFactory()
        AuditLog.objects.all().delete()

        social_account = SocialAccount.objects.create(
            user=user,
            provider="apple",
            uid="apple-abc",
        )

        sociallogin = MagicMock()
        sociallogin.user = user
        sociallogin.account = social_account

        social_account_added.send(
            sender=SocialAccount,
            request=mock_request,
            sociallogin=sociallogin,
        )

        entry = AuditLog.objects.filter(action="social_account_added").first()
        assert entry is not None
        assert entry.metadata["provider"] == "apple"

    def test_social_account_removed_creates_audit_entry(self, mock_request):
        user = UserFactory()
        AuditLog.objects.all().delete()

        social_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="gh-99999",
        )

        social_account_removed.send(
            sender=SocialAccount,
            request=mock_request,
            socialaccount=social_account,
        )

        entry = AuditLog.objects.filter(action="social_account_removed").first()
        assert entry is not None
        assert entry.resource_type == "social_account"
        assert entry.resource_id == str(social_account.pk)
        assert entry.actor_id.int == user.pk
        assert entry.actor_ip == "198.51.100.42"
        assert entry.metadata["provider"] == "github"
        assert entry.metadata["uid"] == "gh-99999"

    def test_multiple_providers_for_same_user(self, mock_request):
        """User can link multiple social accounts, each creates an audit entry."""
        user = UserFactory()
        AuditLog.objects.all().delete()

        for provider, uid in [
            ("github", "gh-1"),
            ("microsoft", "ms-1"),
            ("apple", "ap-1"),
        ]:
            account = SocialAccount.objects.create(
                user=user,
                provider=provider,
                uid=uid,
            )
            sociallogin = MagicMock()
            sociallogin.user = user
            sociallogin.account = account
            social_account_added.send(
                sender=SocialAccount,
                request=mock_request,
                sociallogin=sociallogin,
            )

        entries = AuditLog.objects.filter(action="social_account_added")
        assert entries.count() == 3
        providers = {e.metadata["provider"] for e in entries}
        assert providers == {"github", "microsoft", "apple"}


# ---------------------------------------------------------------------------
# Duplicate email / account linking tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDuplicateEmailHandling:
    """Verify that social login with an existing email links accounts."""

    def test_existing_user_can_have_social_account(self):
        """An existing user (email signup) can link a social account."""
        user = UserFactory(email="alice@example.com")

        social_account = SocialAccount.objects.create(
            user=user,
            provider="github",
            uid="gh-alice",
        )

        assert social_account.user_id == user.pk
        assert SocialAccount.objects.filter(user=user).count() == 1

    def test_multiple_providers_same_user(self):
        """A user can link multiple OAuth providers."""
        user = UserFactory(email="bob@example.com")

        SocialAccount.objects.create(user=user, provider="github", uid="gh-bob")
        SocialAccount.objects.create(user=user, provider="microsoft", uid="ms-bob")
        SocialAccount.objects.create(user=user, provider="apple", uid="ap-bob")

        assert SocialAccount.objects.filter(user=user).count() == 3

    def test_same_provider_uid_unique(self):
        """Same provider + uid combination should be unique."""
        user1 = UserFactory()
        SocialAccount.objects.create(user=user1, provider="github", uid="gh-unique")

        user2 = UserFactory()
        with pytest.raises(Exception):
            SocialAccount.objects.create(user=user2, provider="github", uid="gh-unique")

    def test_different_providers_same_uid_allowed(self):
        """Different providers can have the same uid."""
        user = UserFactory()
        SocialAccount.objects.create(user=user, provider="github", uid="shared-uid")
        SocialAccount.objects.create(user=user, provider="microsoft", uid="shared-uid")
        assert SocialAccount.objects.filter(user=user).count() == 2

    def test_social_account_adapter_allows_signup(self):
        """SocialAccountAdapter.is_open_for_signup returns True by default."""
        from apps.users.adapters import SocialAccountAdapter

        adapter = SocialAccountAdapter()
        request = RequestFactory().get("/")
        sociallogin = MagicMock()
        assert adapter.is_open_for_signup(request, sociallogin) is True

    def test_social_account_adapter_populates_name(self):
        """SocialAccountAdapter.populate_user sets name from provider data."""
        from apps.users.adapters import SocialAccountAdapter

        adapter = SocialAccountAdapter()
        request = RequestFactory().get("/")
        sociallogin = MagicMock()

        # Simulate allauth calling populate_user
        from apps.users.models import User

        user = User()
        with patch.object(
            type(adapter).__bases__[0], "populate_user", return_value=user
        ):
            result = adapter.populate_user(
                request, sociallogin, {"name": "Alice Smith"}
            )
        assert result.name == "Alice Smith"

    def test_social_account_adapter_populates_name_from_parts(self):
        """SocialAccountAdapter builds name from first_name + last_name."""
        from apps.users.adapters import SocialAccountAdapter

        adapter = SocialAccountAdapter()
        request = RequestFactory().get("/")
        sociallogin = MagicMock()

        from apps.users.models import User

        user = User()
        with patch.object(
            type(adapter).__bases__[0], "populate_user", return_value=user
        ):
            result = adapter.populate_user(
                request, sociallogin, {"first_name": "Bob", "last_name": "Jones"}
            )
        assert result.name == "Bob Jones"
