"""Fernet-based PII encryption utilities for the Midsphere platform."""

import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from django.db import models

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the PII_ENCRYPTION_KEY env var."""
    key = os.environ.get("PII_ENCRYPTION_KEY")
    if not key:
        raise ValueError(
            "PII_ENCRYPTION_KEY environment variable is not set. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string, returning base64-encoded Fernet ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Decrypt a base64-encoded Fernet ciphertext string."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def re_encrypt(old_key: str, new_key: str, ciphertext: str) -> str:
    """Re-encrypt ciphertext from old_key to new_key for key rotation.

    Args:
        old_key: The Fernet key used to originally encrypt the data.
        new_key: The new Fernet key to re-encrypt with.
        ciphertext: The base64-encoded Fernet ciphertext.

    Returns:
        New ciphertext encrypted with new_key.
    """
    old_fernet = Fernet(old_key.encode() if isinstance(old_key, str) else old_key)
    new_fernet = Fernet(new_key.encode() if isinstance(new_key, str) else new_key)
    plaintext = old_fernet.decrypt(ciphertext.encode("utf-8"))
    return new_fernet.encrypt(plaintext).decode("utf-8")


class EncryptedCharField(models.TextField):
    """A Django field that transparently encrypts/decrypts values using Fernet.

    Stores base64-encoded Fernet ciphertext in a TextField column.
    Returns decrypted plaintext when accessed from Python.
    Handles None and empty string gracefully.
    """

    def get_prep_value(self, value):
        """Encrypt the value before saving to the database."""
        if value is None or value == "":
            return value
        # Don't double-encrypt: if it's already ciphertext, return as-is.
        # Fernet tokens start with 'gAAAAA'.
        if isinstance(value, str) and value.startswith("gAAAAA"):
            return value
        return encrypt(value)

    def from_db_value(self, value, expression, connection):
        """Decrypt the value when reading from the database."""
        if value is None or value == "":
            return value
        try:
            return decrypt(value)
        except (InvalidToken, Exception):
            # If decryption fails, return the raw value (e.g. during migrations
            # before data is encrypted, or if the value is already plaintext).
            if isinstance(value, str) and value.startswith("gAAAAA"):
                logger.warning(
                    "Failed to decrypt EncryptedCharField value — "
                    "check PII_ENCRYPTION_KEY is set and matches the key used to encrypt data."
                )
            return value

    def to_python(self, value):
        """Convert value to Python string. Decrypts if needed (e.g. from deserialization)."""
        if value is None or value == "":
            return value
        # If this looks like Fernet ciphertext, decrypt it
        if isinstance(value, str) and value.startswith("gAAAAA"):
            try:
                return decrypt(value)
            except (InvalidToken, Exception):
                return value
        return value
