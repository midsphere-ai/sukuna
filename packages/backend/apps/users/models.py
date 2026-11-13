"""User and related models for the Midsphere platform."""

import base64
import hashlib
import secrets
import uuid
from typing import ClassVar

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import CharField
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .encryption import EncryptedCharField
from .managers import UserManager


class ShortUUIDMixin(models.Model):
    """Abstract mixin providing a UUID primary key with a URL-safe short ID encoding."""

    id = models.UUIDField(
        editable=False, default=uuid.uuid4, unique=True, primary_key=True
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    class Meta:
        abstract = True

    @property
    def short_id(self):
        """Return a URL-safe base64-encoded short representation of the UUID.

        Returns:
            A compact string identifier derived from the UUID bytes.
        """
        return base64.urlsafe_b64encode(self.id.bytes).decode("ascii").rstrip("=")

    @classmethod
    def get_by_short_id(cls, short_id):
        """Look up an instance by its short base64-encoded ID.

        Args:
            short_id: The URL-safe base64-encoded short identifier.

        Returns:
            The model instance matching the given short ID.

        Raises:
            cls.DoesNotExist: If no matching instance is found.
        """
        padded = short_id + "=" * ((4 - len(short_id) % 4) % 4)
        uuid_bytes = base64.urlsafe_b64decode(padded)
        uuid_obj = uuid.UUID(bytes=uuid_bytes)
        return cls.objects.get(id=uuid_obj)


class User(AbstractUser):
    """
    Default custom user model for sukuna.
    If adding fields that need to be filled at user signup,
    check forms.SignupForm and forms.SocialSignupForms accordingly.
    """

    # First and last name do not cover name patterns around the globe
    name = EncryptedCharField(_("Name of User"), blank=True, default="")
    first_name = None  # type: ignore[assignment]
    last_name = None  # type: ignore[assignment]
    email = EncryptedCharField(_("email address"))
    email_hash = CharField(
        max_length=64,
        unique=True,
        db_index=True,
        editable=False,
        help_text="SHA-256 hex digest of lowercase email for lookups.",
    )
    username = None  # type: ignore[assignment]
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    # Profile fields
    occupation = CharField(max_length=100, blank=True, default="")
    avatar = models.URLField(blank=True, default="")
    nickname = EncryptedCharField(blank=True, default="")

    objects: ClassVar[UserManager] = UserManager()

    @staticmethod
    def compute_email_hash(email: str) -> str:
        """Return SHA-256 hex digest of the lowercase email."""
        return hashlib.sha256(email.lower().strip().encode()).hexdigest()

    def save(self, *args, **kwargs):
        """Auto-compute email_hash from the plaintext email before saving."""
        if self.email:
            self.email_hash = self.compute_email_hash(self.email)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        """Get URL for user's detail view.

        Returns:
            str: URL for user detail.

        """
        return reverse("users:detail", kwargs={"pk": self.id})

    def get_full_name(self) -> str:
        """Return the name field, or email if name is empty."""
        return self.name or self.email

    def get_short_name(self) -> str:
        """Return the name field, or email if name is empty."""
        return self.name or self.email

    def __str__(self) -> str:
        return self.name or self.email


class UserSettings(models.Model):
    """Persistent user preferences — one-to-one with User, auto-created on first access."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="settings")

    # Appearance
    theme = models.CharField(max_length=20, default="system")
    accent_color = models.CharField(max_length=50, blank=True, default="")

    # Profile / personalisation
    custom_instructions = models.TextField(blank=True, default="")
    nickname = models.CharField(max_length=50, blank=True, default="")
    occupation = models.CharField(max_length=100, blank=True, default="")
    about_you = models.TextField(blank=True, default="")
    # Nullable for backwards-compatibility with legacy accounts.
    # None means "unknown" and callers should use fallback heuristics.
    onboarding_completed = models.BooleanField(null=True, default=None)

    # Tool toggles
    web_search = models.BooleanField(default=True)
    browser = models.BooleanField(default=True)
    shell_commands = models.BooleanField(default=True)
    complex_reasoning = models.BooleanField(default=True)
    computer_use = models.BooleanField(default=True)

    # Notifications
    notification_email = models.BooleanField(default=True)
    notification_push = models.BooleanField(default=True)
    notification_marketing = models.BooleanField(default=False)

    # Data sharing
    data_share_analytics = models.BooleanField(default=True)
    data_share_training = models.BooleanField(default=False)

    # Advanced
    backend_url = models.CharField(max_length=500, blank=True, default="")
    local_mode = models.BooleanField(default=False)
    local_sandbox_url = models.CharField(max_length=500, blank=True, default="")

    # Multi-org context
    last_active_org = models.ForeignKey(
        "workspace.Organization",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="Last active organization for org switcher context. Null = personal space.",
    )

    class Meta:
        verbose_name = "User Settings"
        verbose_name_plural = "User Settings"

    def __str__(self) -> str:
        return f"Settings for {self.user}"


class TelegramLink(models.Model):
    """Links a Midsphere user to their Telegram account for claw mode messaging."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="telegram_link",
    )
    telegram_chat_id = models.BigIntegerField(unique=True)
    telegram_username = models.CharField(max_length=255, blank=True, null=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Telegram Link"
        verbose_name_plural = "Telegram Links"

    def __str__(self) -> str:
        return f"TelegramLink(user={self.user_id}, chat_id={self.telegram_chat_id}, active={self.is_active})"


class SlackLink(models.Model):
    """Links a Midsphere user to their Slack account for claw mode messaging."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="slack_link",
    )
    slack_user_id = models.CharField(max_length=255, unique=True)
    slack_team_id = models.CharField(max_length=255, blank=True, default="")
    slack_username = models.CharField(max_length=255, blank=True, default="")
    slack_workspace_name = models.CharField(max_length=255, blank=True, default="")
    linked_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Slack Link"
        verbose_name_plural = "Slack Links"

    def __str__(self) -> str:
        return f"SlackLink(user={self.user_id}, slack_user_id={self.slack_user_id}, active={self.is_active})"


class DiscordLink(models.Model):
    """Links a Midsphere user to their Discord account for claw mode messaging."""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="discord_link",
    )
    discord_user_id = models.CharField(max_length=255, unique=True)
    discord_username = models.CharField(max_length=255, blank=True, default="")
    discord_guild_id = models.CharField(max_length=255, blank=True, default="")
    linked_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Discord Link"
        verbose_name_plural = "Discord Links"

    def __str__(self) -> str:
        return f"DiscordLink(user={self.user_id}, discord_user_id={self.discord_user_id}, active={self.is_active})"


class DeveloperAPIKey(ShortUUIDMixin):
    """A hashed API key for programmatic access to the Midsphere developer API."""

    PREFIX = "msk_"
    KEY_LENGTH = 32

    name = models.CharField(max_length=255)
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        help_text="SHA-256 hash of the API key. The raw key is only shown once at creation.",
    )
    key_prefix = models.CharField(
        max_length=12,
        blank=True,
        help_text="First few characters of the key for identification.",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="developer_api_keys",
    )
    is_active = models.BooleanField(default=True)
    scopes = models.JSONField(
        default=list,
        blank=True,
        help_text="List of permission scopes granted to this key.",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Developer API Key"
        verbose_name_plural = "Developer API Keys"
        ordering = ["-date_created"]

    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix}****)"

    @classmethod
    def generate_key(cls) -> str:
        """Generate a new raw API key with the standard prefix.

        Returns:
            The raw API key string (e.g., 'msk_abc123...').
        """
        return f"{cls.PREFIX}{secrets.token_urlsafe(cls.KEY_LENGTH)}"

    @staticmethod
    def hash_key(raw_key: str) -> str:
        """Hash a raw API key using SHA-256.

        Args:
            raw_key: The plaintext API key.

        Returns:
            The hex-encoded SHA-256 hash.
        """
        return hashlib.sha256(raw_key.encode()).hexdigest()
