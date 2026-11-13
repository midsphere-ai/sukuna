"""Tests for the PII encryption utility and EncryptedCharField."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from apps.users.encryption import (
    EncryptedCharField,
    decrypt,
    encrypt,
    re_encrypt,
)


@pytest.fixture(autouse=True)
def _set_encryption_key(monkeypatch):
    """Provide a valid Fernet key for all tests in this module."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PII_ENCRYPTION_KEY", key)


# ---------------------------------------------------------------------------
# encrypt / decrypt roundtrip
# ---------------------------------------------------------------------------
class TestEncryptDecrypt:
    def test_roundtrip(self):
        plaintext = "alice@example.com"
        ciphertext = encrypt(plaintext)
        assert ciphertext != plaintext
        assert decrypt(ciphertext) == plaintext

    def test_roundtrip_unicode(self):
        plaintext = "用户名@example.com"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_ciphertext_is_base64(self):
        ciphertext = encrypt("hello")
        # Fernet tokens are URL-safe base64 and start with 'gAAAAA'
        assert ciphertext.startswith("gAAAAA")

    def test_different_encryptions_differ(self):
        """Fernet includes a timestamp, so encrypting twice produces different ciphertext."""
        a = encrypt("same")
        b = encrypt("same")
        assert a != b
        assert decrypt(a) == decrypt(b) == "same"


# ---------------------------------------------------------------------------
# None / empty handling
# ---------------------------------------------------------------------------
class TestNoneAndEmpty:
    def test_encrypt_none_via_field(self):
        field = EncryptedCharField()
        assert field.get_prep_value(None) is None

    def test_encrypt_empty_via_field(self):
        field = EncryptedCharField()
        assert field.get_prep_value("") == ""

    def test_decrypt_none_via_field(self):
        field = EncryptedCharField()
        assert field.from_db_value(None, None, None) is None

    def test_decrypt_empty_via_field(self):
        field = EncryptedCharField()
        assert field.from_db_value("", None, None) == ""


# ---------------------------------------------------------------------------
# Key rotation
# ---------------------------------------------------------------------------
class TestKeyRotation:
    def test_re_encrypt(self):
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        # Encrypt with old key
        old_fernet = Fernet(old_key.encode())
        original_ciphertext = old_fernet.encrypt(b"secret@example.com").decode()

        # Re-encrypt
        new_ciphertext = re_encrypt(old_key, new_key, original_ciphertext)

        # New ciphertext differs from old
        assert new_ciphertext != original_ciphertext

        # New key can decrypt
        new_fernet = Fernet(new_key.encode())
        assert (
            new_fernet.decrypt(new_ciphertext.encode()).decode() == "secret@example.com"
        )

        # Old key cannot decrypt new ciphertext
        with pytest.raises(InvalidToken):
            old_fernet.decrypt(new_ciphertext.encode())

    def test_re_encrypt_preserves_plaintext(self):
        old_key = Fernet.generate_key().decode()
        new_key = Fernet.generate_key().decode()

        old_fernet = Fernet(old_key.encode())
        ciphertext = old_fernet.encrypt(b"hello world").decode()

        new_ciphertext = re_encrypt(old_key, new_key, ciphertext)
        new_fernet = Fernet(new_key.encode())
        assert new_fernet.decrypt(new_ciphertext.encode()).decode() == "hello world"


# ---------------------------------------------------------------------------
# Invalid key errors
# ---------------------------------------------------------------------------
class TestInvalidKey:
    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError, match="PII_ENCRYPTION_KEY"):
            encrypt("test")

    def test_missing_key_decrypt_raises(self, monkeypatch):
        # Encrypt with a valid key first
        ciphertext = encrypt("test")
        monkeypatch.delenv("PII_ENCRYPTION_KEY", raising=False)
        with pytest.raises(ValueError, match="PII_ENCRYPTION_KEY"):
            decrypt(ciphertext)

    def test_wrong_key_decrypt_raises(self, monkeypatch):
        ciphertext = encrypt("test")
        # Switch to a different key
        different_key = Fernet.generate_key().decode()
        monkeypatch.setenv("PII_ENCRYPTION_KEY", different_key)
        with pytest.raises(InvalidToken):
            decrypt(ciphertext)


# ---------------------------------------------------------------------------
# EncryptedCharField
# ---------------------------------------------------------------------------
class TestEncryptedCharField:
    def test_get_prep_value_encrypts(self):
        field = EncryptedCharField()
        result = field.get_prep_value("plaintext")
        assert result != "plaintext"
        assert result.startswith("gAAAAA")

    def test_get_prep_value_no_double_encrypt(self):
        field = EncryptedCharField()
        ciphertext = encrypt("plaintext")
        result = field.get_prep_value(ciphertext)
        # Should return the same ciphertext, not double-encrypt
        assert result == ciphertext

    def test_from_db_value_decrypts(self):
        field = EncryptedCharField()
        ciphertext = encrypt("hello@example.com")
        result = field.from_db_value(ciphertext, None, None)
        assert result == "hello@example.com"

    def test_to_python_decrypts_ciphertext(self):
        field = EncryptedCharField()
        ciphertext = encrypt("data")
        result = field.to_python(ciphertext)
        assert result == "data"

    def test_to_python_returns_plaintext_as_is(self):
        field = EncryptedCharField()
        result = field.to_python("plain text value")
        assert result == "plain text value"

    def test_to_python_none(self):
        field = EncryptedCharField()
        assert field.to_python(None) is None

    def test_to_python_empty(self):
        field = EncryptedCharField()
        assert field.to_python("") == ""
