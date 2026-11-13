"""Unit tests for users app models — User, UserSettings, DeveloperAPIKey, ShortUUIDMixin."""

import uuid

import pytest

from apps.users.models import DeveloperAPIKey, User, UserSettings
from apps.users.tests.factories import UserFactory


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUser:
    def test_get_absolute_url(self):
        user = UserFactory()
        assert user.get_absolute_url() == f"/users/{user.pk}/"

    def test_str_with_name(self):
        user = UserFactory(name="Alice")
        assert str(user) == "Alice"

    def test_str_without_name(self):
        user = UserFactory(name="")
        assert str(user) == user.email

    def test_get_full_name(self):
        user = UserFactory(name="Bob")
        assert user.get_full_name() == "Bob"

    def test_get_full_name_empty(self):
        user = UserFactory(name="")
        assert user.get_full_name() == user.email

    def test_get_short_name(self):
        user = UserFactory(name="Charlie")
        assert user.get_short_name() == "Charlie"

    def test_get_short_name_empty(self):
        user = UserFactory(name="")
        assert user.get_short_name() == user.email

    def test_email_unique(self):
        from django.db import IntegrityError

        UserFactory(email="dup@example.com")
        with pytest.raises(IntegrityError):
            User.objects.create_user(email="dup@example.com", password="pass123!")  # noqa: S106

    def test_username_is_none(self):
        user = UserFactory()
        assert user.username is None

    def test_profile_fields_defaults(self):
        user = UserFactory()
        assert user.occupation == ""
        assert user.avatar == ""
        assert user.nickname == ""


# ---------------------------------------------------------------------------
# UserManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserManager:
    def test_create_user(self):
        user = User.objects.create_user(email="u@example.com", password="p@ss123!")  # noqa: S106
        assert user.email == "u@example.com"
        assert not user.is_staff
        assert not user.is_superuser
        assert user.check_password("p@ss123!")

    def test_create_user_no_email(self):
        with pytest.raises(ValueError, match="email must be set"):
            User.objects.create_user(email="", password="p@ss123!")  # noqa: S106

    def test_create_superuser(self):
        user = User.objects.create_superuser(email="su@example.com", password="p@ss!")  # noqa: S106
        assert user.is_staff
        assert user.is_superuser

    def test_create_superuser_not_staff_raises(self):
        with pytest.raises(ValueError, match="is_staff=True"):
            User.objects.create_superuser(
                email="bad@example.com",
                password="p!",
                is_staff=False,  # noqa: S106
            )

    def test_create_superuser_not_superuser_raises(self):
        with pytest.raises(ValueError, match="is_superuser=True"):
            User.objects.create_superuser(
                email="bad2@example.com",
                password="p!",
                is_superuser=False,  # noqa: S106
            )


# ---------------------------------------------------------------------------
# UserSettings
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserSettings:
    def test_str(self):
        user = UserFactory()
        settings = UserSettings.objects.create(user=user)
        assert f"Settings for {user}" in str(settings)

    def test_defaults(self):
        user = UserFactory()
        s = UserSettings.objects.create(user=user)
        assert s.theme == "system"
        assert s.accent_color == ""
        assert s.web_search is True
        assert s.browser is True
        assert s.shell_commands is True
        assert s.complex_reasoning is True
        assert s.computer_use is True
        assert s.notification_email is True
        assert s.notification_push is True
        assert s.notification_marketing is False
        assert s.data_share_analytics is True
        assert s.data_share_training is False
        assert s.backend_url == ""
        assert s.custom_instructions == ""

    def test_one_to_one(self):
        from django.db import IntegrityError

        user = UserFactory()
        UserSettings.objects.create(user=user)
        with pytest.raises(IntegrityError):
            UserSettings.objects.create(user=user)

    def test_cascade_delete(self):
        user = UserFactory()
        UserSettings.objects.create(user=user)
        user.delete()
        assert UserSettings.objects.count() == 0


# ---------------------------------------------------------------------------
# DeveloperAPIKey
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeveloperAPIKey:
    def test_generate_key(self):
        key = DeveloperAPIKey.generate_key()
        assert key.startswith("msk_")
        assert len(key) > 4

    def test_hash_key(self):
        raw = "msk_testkey123"
        hashed = DeveloperAPIKey.hash_key(raw)
        assert len(hashed) == 64  # SHA-256 hex
        # Same input → same hash
        assert DeveloperAPIKey.hash_key(raw) == hashed

    def test_str(self):
        user = UserFactory()
        key = DeveloperAPIKey.objects.create(
            name="My Key",
            key_hash=DeveloperAPIKey.hash_key("msk_abc"),
            key_prefix="msk_abc",
            user=user,
        )
        assert "My Key" in str(key)
        assert "msk_abc" in str(key)

    def test_defaults(self):
        user = UserFactory()
        key = DeveloperAPIKey.objects.create(
            name="K",
            key_hash=DeveloperAPIKey.hash_key("msk_def"),
            key_prefix="msk_def",
            user=user,
        )
        assert key.is_active is True
        assert key.scopes == []
        assert key.last_used_at is None
        assert key.expires_at is None

    def test_unique_key_hash(self):
        from django.db import IntegrityError

        user = UserFactory()
        h = DeveloperAPIKey.hash_key("msk_same")
        DeveloperAPIKey.objects.create(
            name="K1", key_hash=h, key_prefix="msk_s", user=user
        )
        with pytest.raises(IntegrityError):
            DeveloperAPIKey.objects.create(
                name="K2", key_hash=h, key_prefix="msk_s", user=user
            )

    def test_ordering(self):
        user = UserFactory()
        k1 = DeveloperAPIKey.objects.create(
            name="K1",
            key_hash=DeveloperAPIKey.hash_key("msk_1"),
            key_prefix="msk_1",
            user=user,
        )
        k2 = DeveloperAPIKey.objects.create(
            name="K2",
            key_hash=DeveloperAPIKey.hash_key("msk_2"),
            key_prefix="msk_2",
            user=user,
        )
        keys = list(DeveloperAPIKey.objects.all())
        assert keys[0] == k2  # newest first

    def test_cascade_delete(self):
        user = UserFactory()
        DeveloperAPIKey.objects.create(
            name="K",
            key_hash=DeveloperAPIKey.hash_key("msk_del"),
            key_prefix="msk_del",
            user=user,
        )
        user.delete()
        assert DeveloperAPIKey.objects.count() == 0


# ---------------------------------------------------------------------------
# ShortUUIDMixin (tested via DeveloperAPIKey which extends it)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestShortUUIDMixin:
    def test_short_id(self):
        user = UserFactory()
        key = DeveloperAPIKey.objects.create(
            name="S",
            key_hash=DeveloperAPIKey.hash_key("msk_sid"),
            key_prefix="msk_sid",
            user=user,
        )
        short = key.short_id
        assert isinstance(short, str)
        assert len(short) > 0
        # No padding characters
        assert "=" not in short

    def test_get_by_short_id(self):
        user = UserFactory()
        key = DeveloperAPIKey.objects.create(
            name="S2",
            key_hash=DeveloperAPIKey.hash_key("msk_sid2"),
            key_prefix="msk_sid2",
            user=user,
        )
        found = DeveloperAPIKey.get_by_short_id(key.short_id)
        assert found.id == key.id

    def test_get_by_short_id_not_found(self):
        # Encode a random UUID as short id
        import base64

        random_uuid = uuid.uuid4()
        short = base64.urlsafe_b64encode(random_uuid.bytes).decode("ascii").rstrip("=")
        with pytest.raises(DeveloperAPIKey.DoesNotExist):
            DeveloperAPIKey.get_by_short_id(short)

    def test_auto_timestamps(self):
        user = UserFactory()
        key = DeveloperAPIKey.objects.create(
            name="TS",
            key_hash=DeveloperAPIKey.hash_key("msk_ts"),
            key_prefix="msk_ts",
            user=user,
        )
        assert key.date_created is not None
        assert key.date_updated is not None
