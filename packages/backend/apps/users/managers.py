"""Custom user manager using email as the unique identifier instead of username."""

import hashlib
from typing import TYPE_CHECKING

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import UserManager as DjangoUserManager

if TYPE_CHECKING:
    from .models import User  # noqa: F401


class UserManager(DjangoUserManager["User"]):
    """Custom manager for the User model, using email instead of username."""

    @staticmethod
    def _hash_email(email: str) -> str:
        """Return SHA-256 hex digest of the lowercase email."""
        return hashlib.sha256(email.lower().strip().encode()).hexdigest()

    def get_by_email(self, email: str) -> "User":
        """Look up a user by email using the email_hash index.

        Args:
            email: The plaintext email address.

        Returns:
            The User instance matching the given email.

        Raises:
            self.model.DoesNotExist: If no user matches.
        """
        return self.get(email_hash=self._hash_email(email))

    def get_by_natural_key(self, email: str) -> "User":
        """Override Django's natural key lookup to use email_hash.

        This ensures Django's authentication backend works with encrypted email.
        """
        return self.get(email_hash=self._hash_email(email))

    def _create_user(self, email: str, password: str | None, **extra_fields):
        """Create and save a user with the given email and password.

        Args:
            email: The user's email address.
            password: The user's password, or None for an unusable password.
            **extra_fields: Additional fields to set on the user model.

        Returns:
            The newly created User instance.

        Raises:
            ValueError: If the email is not provided.
        """
        if not email:
            msg = "The given email must be set"
            raise ValueError(msg)
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.password = make_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):  # type: ignore[override]
        """Create a regular user with the given email and password.

        Args:
            email: The user's email address.
            password: The user's password, or None for an unusable password.
            **extra_fields: Additional fields to set on the user model.

        Returns:
            The newly created User instance.
        """
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):  # type: ignore[override]
        """Create a superuser with the given email and password.

        Args:
            email: The user's email address.
            password: The user's password, or None for an unusable password.
            **extra_fields: Additional fields to set on the user model.

        Returns:
            The newly created User instance.

        Raises:
            ValueError: If is_staff or is_superuser is not True.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            msg = "Superuser must have is_staff=True."
            raise ValueError(msg)
        if extra_fields.get("is_superuser") is not True:
            msg = "Superuser must have is_superuser=True."
            raise ValueError(msg)

        return self._create_user(email, password, **extra_fields)
