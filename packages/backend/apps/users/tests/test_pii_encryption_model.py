"""Tests for US-004: PII encryption on User model + email hash lookup."""

import hashlib
import os

import pytest
from cryptography.fernet import Fernet
from django.core.management import call_command
from django.db import connection

from apps.users.models import User


def _raw_user_fields(user_id):
    """Read raw DB values bypassing EncryptedCharField.from_db_value()."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT email, name, nickname FROM users_user WHERE id = %s",
            [user_id],
        )
        row = cursor.fetchone()
    return {"email": row[0], "name": row[1], "nickname": row[2]}


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a stable Fernet key for all tests."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)
    return key


@pytest.fixture
def fernet_key(_set_encryption_key):
    """Return the current encryption key as a string."""
    return _set_encryption_key


# ---------------------------------------------------------------------------
# email_hash computation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEmailHash:
    def test_email_hash_computed_on_create(self):
        user = User.objects.create_user(
            email="alice@example.com", password="pw12345678"
        )
        expected = hashlib.sha256(b"alice@example.com").hexdigest()
        assert user.email_hash == expected

    def test_email_hash_lowercased(self):
        user = User.objects.create_user(
            email="Alice@Example.COM", password="pw12345678"
        )
        expected = hashlib.sha256(b"alice@example.com").hexdigest()
        assert user.email_hash == expected

    def test_email_hash_updated_on_save(self):
        user = User.objects.create_user(email="old@example.com", password="pw12345678")
        old_hash = user.email_hash
        user.email = "new@example.com"
        user.save()
        assert user.email_hash != old_hash
        assert user.email_hash == hashlib.sha256(b"new@example.com").hexdigest()

    def test_email_hash_unique(self):
        User.objects.create_user(email="unique@example.com", password="pw12345678")
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            User.objects.create_user(email="unique@example.com", password="pw12345678")

    def test_compute_email_hash_static(self):
        result = User.compute_email_hash("Test@Example.com")
        assert result == hashlib.sha256(b"test@example.com").hexdigest()


# ---------------------------------------------------------------------------
# get_by_email manager method
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetByEmail:
    def test_get_by_email_exact(self):
        created = User.objects.create_user(
            email="lookup@example.com", password="pw12345678"
        )
        found = User.objects.get_by_email("lookup@example.com")
        assert found.pk == created.pk

    def test_get_by_email_case_insensitive(self):
        created = User.objects.create_user(
            email="mixed@example.com", password="pw12345678"
        )
        found = User.objects.get_by_email("MIXED@Example.COM")
        assert found.pk == created.pk

    def test_get_by_email_not_found(self):
        with pytest.raises(User.DoesNotExist):
            User.objects.get_by_email("nobody@example.com")

    def test_get_by_natural_key(self):
        """Django auth backend uses get_by_natural_key for login."""
        created = User.objects.create_user(
            email="auth@example.com", password="pw12345678"
        )
        found = User.objects.get_by_natural_key("auth@example.com")
        assert found.pk == created.pk


# ---------------------------------------------------------------------------
# Encrypted field storage
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEncryptedFields:
    def test_email_decrypted_on_read(self):
        user = User.objects.create_user(
            email="encrypted@example.com", password="pw12345678"
        )
        user.refresh_from_db()
        assert user.email == "encrypted@example.com"

    def test_email_encrypted_in_db(self):
        user = User.objects.create_user(
            email="hidden@example.com", password="pw12345678"
        )
        raw = _raw_user_fields(user.pk)
        assert raw["email"].startswith("gAAAAA")

    def test_name_encrypted_in_db(self):
        user = User.objects.create_user(
            email="name-test@example.com", password="pw12345678", name="Alice Smith"
        )
        raw = _raw_user_fields(user.pk)
        assert raw["name"].startswith("gAAAAA")
        user.refresh_from_db()
        assert user.name == "Alice Smith"

    def test_nickname_encrypted_in_db(self):
        user = User.objects.create_user(
            email="nick-test@example.com", password="pw12345678", nickname="ally"
        )
        raw = _raw_user_fields(user.pk)
        assert raw["nickname"].startswith("gAAAAA")
        user.refresh_from_db()
        assert user.nickname == "ally"

    def test_empty_name_not_encrypted(self):
        user = User.objects.create_user(
            email="empty-name@example.com", password="pw12345678"
        )
        raw = _raw_user_fields(user.pk)
        assert raw["name"] == ""

    def test_empty_nickname_not_encrypted(self):
        user = User.objects.create_user(
            email="empty-nick@example.com", password="pw12345678"
        )
        raw = _raw_user_fields(user.pk)
        assert raw["nickname"] == ""

    def test_none_handling(self):
        """Fields should handle None gracefully."""
        user = User.objects.create_user(
            email="null-test@example.com", password="pw12345678"
        )
        # name/nickname default to "" so they're not None, but verify roundtrip
        assert user.name == ""
        assert user.nickname == ""


# ---------------------------------------------------------------------------
# Admin display (decrypted values readable)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAdminDisplay:
    def test_admin_sees_decrypted_email(self):
        user = User.objects.create_user(
            email="admin-view@example.com", password="pw12345678", name="Admin User"
        )
        user.refresh_from_db()
        # Admin accesses model attributes which go through from_db_value
        assert user.email == "admin-view@example.com"
        assert user.name == "Admin User"

    def test_str_uses_decrypted_name(self):
        user = User.objects.create_user(
            email="str@example.com", password="pw12345678", name="Display Name"
        )
        user.refresh_from_db()
        assert str(user) == "Display Name"

    def test_str_falls_back_to_decrypted_email(self):
        user = User.objects.create_user(
            email="fallback@example.com", password="pw12345678"
        )
        user.refresh_from_db()
        assert str(user) == "fallback@example.com"

    def test_get_full_name_decrypted(self):
        user = User.objects.create_user(
            email="full@example.com", password="pw12345678", name="Full Name"
        )
        user.refresh_from_db()
        assert user.get_full_name() == "Full Name"


# ---------------------------------------------------------------------------
# Key rotation management command
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRotatePiiKey:
    def test_rotate_key(self, monkeypatch):
        old_key = os.environ["PII_ENCRYPTION_KEY"]
        new_key = Fernet.generate_key().decode()

        # Create a user with the old key
        user = User.objects.create_user(
            email="rotate@example.com", password="pw12345678", name="Rotate Me"
        )

        # Verify encrypted with old key (raw SQL)
        raw_before = _raw_user_fields(user.pk)
        assert raw_before["email"].startswith("gAAAAA")

        # Run rotation
        call_command("rotate_pii_key", old_key=old_key, new_key=new_key)

        # Raw ciphertext changed
        raw_after = _raw_user_fields(user.pk)
        assert raw_after["email"] != raw_before["email"]
        assert raw_after["name"] != raw_before["name"]

        # New key can decrypt
        monkeypatch.setenv("PII_ENCRYPTION_KEY", new_key)
        user.refresh_from_db()
        assert user.email == "rotate@example.com"
        assert user.name == "Rotate Me"

    def test_rotate_key_dry_run(self):
        old_key = os.environ["PII_ENCRYPTION_KEY"]
        new_key = Fernet.generate_key().decode()

        user = User.objects.create_user(
            email="dryrun@example.com", password="pw12345678"
        )

        raw_before = _raw_user_fields(user.pk)

        call_command("rotate_pii_key", old_key=old_key, new_key=new_key, dry_run=True)

        # Data should be unchanged
        raw_after = _raw_user_fields(user.pk)
        assert raw_after["email"] == raw_before["email"]

    def test_rotate_key_wrong_old_key(self):
        wrong_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        User.objects.create_user(email="wrongkey@example.com", password="pw12345678")

        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="failed key rotation"):
            call_command("rotate_pii_key", old_key=wrong_key, new_key=new_key)


# ---------------------------------------------------------------------------
# Tier 2: additional coverage for model-level roundtrip and edge cases
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestEncryptedFieldModelRoundtrip:
    """Verify EncryptedCharField roundtrip through full Django ORM cycle."""

    def test_save_reload_multiple_users(self):
        """Create several users, reload all, verify decrypted values."""
        users_data = [
            ("u1@example.com", "Alice"),
            ("u2@example.com", "Bob"),
            ("u3@example.com", "Charlie"),
        ]
        created_pks = []
        for email, name in users_data:
            u = User.objects.create_user(email=email, password="pw12345678", name=name)
            created_pks.append(u.pk)

        # Reload all and verify decrypted
        for pk, (email, name) in zip(created_pks, users_data):
            u = User.objects.get(pk=pk)
            assert u.email == email
            assert u.name == name

    def test_raw_db_stores_ciphertext_for_all(self):
        """All encrypted fields for every user are stored as ciphertext."""
        users_data = [
            ("enc-a@example.com", "NameA", "nickA"),
            ("enc-b@example.com", "NameB", "nickB"),
        ]
        for email, name, nick in users_data:
            u = User.objects.create_user(
                email=email, password="pw12345678", name=name, nickname=nick
            )
            raw = _raw_user_fields(u.pk)
            assert raw["email"].startswith("gAAAAA"), f"email not encrypted for {email}"
            assert raw["name"].startswith("gAAAAA"), f"name not encrypted for {email}"
            assert raw["nickname"].startswith("gAAAAA"), (
                f"nickname not encrypted for {email}"
            )

    def test_email_hash_unique_per_user(self):
        """Each distinct email produces a unique email_hash."""
        u1 = User.objects.create_user(email="hash1@example.com", password="pw12345678")
        u2 = User.objects.create_user(email="hash2@example.com", password="pw12345678")
        assert u1.email_hash != u2.email_hash

    def test_update_email_updates_hash_and_encryption(self):
        """Changing email re-encrypts and updates the hash."""
        user = User.objects.create_user(
            email="before@example.com", password="pw12345678"
        )
        old_hash = user.email_hash
        old_raw = _raw_user_fields(user.pk)["email"]

        user.email = "after@example.com"
        user.save()

        assert user.email_hash != old_hash
        new_raw = _raw_user_fields(user.pk)["email"]
        assert new_raw != old_raw
        assert new_raw.startswith("gAAAAA")

        user.refresh_from_db()
        assert user.email == "after@example.com"
        assert user.email_hash == User.compute_email_hash("after@example.com")

    def test_rotate_key_multiple_users(self, monkeypatch):
        """Key rotation re-encrypts all users, not just one."""
        old_key = os.environ["PII_ENCRYPTION_KEY"]
        new_key = Fernet.generate_key().decode()

        u1 = User.objects.create_user(
            email="rot1@example.com", password="pw12345678", name="One"
        )
        u2 = User.objects.create_user(
            email="rot2@example.com", password="pw12345678", name="Two"
        )

        raw_before_1 = _raw_user_fields(u1.pk)
        raw_before_2 = _raw_user_fields(u2.pk)

        call_command("rotate_pii_key", old_key=old_key, new_key=new_key)

        raw_after_1 = _raw_user_fields(u1.pk)
        raw_after_2 = _raw_user_fields(u2.pk)

        # Both users re-encrypted
        assert raw_after_1["email"] != raw_before_1["email"]
        assert raw_after_2["email"] != raw_before_2["email"]

        # New key decrypts both
        monkeypatch.setenv("PII_ENCRYPTION_KEY", new_key)
        u1.refresh_from_db()
        u2.refresh_from_db()
        assert u1.email == "rot1@example.com"
        assert u2.email == "rot2@example.com"
