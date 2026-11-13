from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.storage.models import MarketplaceAddon, UserMarketplaceAddons
from apps.users.models import User


class UserMarketplaceAddonsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create(email="test@example.com")
        self.addon = MarketplaceAddon.objects.create(name="Test Addon")
        self.user_addon = UserMarketplaceAddons.objects.create(
            owner=self.user,
            enabled_addon=self.addon,
            auth_link="http://example.com/auth",
        )

    def test_auth_complete(self):
        self.user_addon.auth_complete = True
        self.user_addon.save()
        # Should not raise
        self.user_addon.check_auth_status()

    def test_auth_incomplete_fresh_link(self):
        # Link created just now
        with self.assertRaises(ValueError) as cm:
            self.user_addon.check_auth_status()
        self.assertEqual(
            str(cm.exception), "Authentication is not complete for this addon."
        )
        self.assertIsNotNone(self.user_addon.auth_link)

    def test_auth_incomplete_expired_link(self):
        # Move date_created to past
        past = timezone.now() - timedelta(hours=7)
        UserMarketplaceAddons.objects.filter(id=self.user_addon.id).update(
            date_created=past
        )
        self.user_addon.refresh_from_db()

        with self.assertRaises(ValueError) as cm:
            self.user_addon.check_auth_status()

        self.assertEqual(
            str(cm.exception), "Authentication link has expired. Please regenerate it."
        )

        self.user_addon.refresh_from_db()
        self.assertIsNone(self.user_addon.auth_link)
