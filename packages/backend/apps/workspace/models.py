"""Database models for the workspace app, including password reset OTP management."""

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.utils.translation import gettext_lazy as _

from apps.users.encryption import EncryptedCharField


class OrganizationRole(models.TextChoices):
    """RBAC roles for organization membership, ordered by privilege level."""

    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")
    VIEWER = "viewer", _("Viewer")


# Role hierarchy: higher index = more privilege
ROLE_HIERARCHY = {
    OrganizationRole.VIEWER: 0,
    OrganizationRole.MEMBER: 1,
    OrganizationRole.ADMIN: 2,
    OrganizationRole.OWNER: 3,
}


class Organization(models.Model):
    """An organization that groups users, projects, and billing under a shared tenant.

    Organizations are the top-level container for multi-user collaboration.
    Every org must have exactly one owner at all times.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    description = models.TextField(blank=True, default="")

    # Security policy settings (SOC2 controls)
    mfa_required = models.BooleanField(
        default=False,
        help_text="Require all members to have MFA enabled before accessing org resources.",
    )
    session_timeout_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Per-org session timeout in minutes. Null = use global default.",
    )
    max_concurrent_sessions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Max active sessions per user in this org. Null = use global default.",
    )

    frozen_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When set, the org is frozen: no new runs, shares, or invites.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="OrganizationMembership",
        through_fields=("organization", "user"),
        related_name="organizations",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Organization"
        verbose_name_plural = "Organizations"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._generate_unique_slug()
        super().save(*args, **kwargs)

    def _generate_unique_slug(self) -> str:
        """Generate a unique slug from the name, appending a suffix if needed."""
        base_slug = slugify(self.name)
        if not base_slug:
            base_slug = "org"
        slug = base_slug
        counter = 1
        while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    def get_owner(self) -> "OrganizationMembership | None":
        """Return the owner membership, or None if somehow missing."""
        return self.memberships.filter(role=OrganizationRole.OWNER).first()

    def get_membership(self, user) -> "OrganizationMembership | None":
        """Return the membership for a user, or None if not a member."""
        return self.memberships.filter(user=user).first()

    def has_member(self, user) -> bool:
        """Check if a user is a member of this organization (any role)."""
        return self.memberships.filter(user=user).exists()

    def member_count(self) -> int:
        """Return the number of members in this organization."""
        return self.memberships.count()

    @property
    def is_frozen(self) -> bool:
        """Check if the organization is currently frozen."""
        return self.frozen_at is not None


class DeletedOrgSlug(models.Model):
    """Reserves deleted org slugs for 90 days to prevent reuse.

    When an org is deleted, its slug is stored here with a 90-day reservation
    window. This prevents confusion when IdP configs reference old slugs.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    slug = models.SlugField(max_length=255, unique=True, db_index=True)
    deleted_at = models.DateTimeField(auto_now_add=True)
    reserved_until = models.DateTimeField(
        help_text="Slug cannot be reused until this timestamp.",
    )

    class Meta:
        verbose_name = "Deleted Org Slug"
        verbose_name_plural = "Deleted Org Slugs"

    def __str__(self):
        return f"{self.slug} (reserved until {self.reserved_until})"

    @property
    def is_reserved(self) -> bool:
        return timezone.now() < self.reserved_until


class OrganizationMembership(models.Model):
    """Through table linking users to organizations with an RBAC role.

    Constraints:
    - Each user can have only one role per organization.
    - Every organization must have exactly one owner (enforced at application level).
    - The last owner cannot be removed or demoted.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="org_memberships",
    )
    role = models.CharField(
        max_length=20,
        choices=OrganizationRole.choices,
        default=OrganizationRole.MEMBER,
        db_index=True,
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="org_invitations_sent",
    )
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("organization", "user")]
        ordering = ["joined_at"]
        verbose_name = "Organization Membership"
        verbose_name_plural = "Organization Memberships"

    def __str__(self):
        return f"{self.user} → {self.organization.name} ({self.role})"

    @property
    def role_level(self) -> int:
        """Numeric privilege level for this membership's role."""
        return ROLE_HIERARCHY.get(self.role, 0)

    def has_role_or_higher(self, min_role: str) -> bool:
        """Check if this membership's role meets or exceeds the given minimum role."""
        return self.role_level >= ROLE_HIERARCHY.get(min_role, 0)

    def change_role(self, new_role: str) -> None:
        """Change this membership's role, enforcing owner constraints.

        Raises:
            ValueError: If demoting the last owner of the organization.
        """
        if self.role == OrganizationRole.OWNER and new_role != OrganizationRole.OWNER:
            owner_count = self.organization.memberships.filter(
                role=OrganizationRole.OWNER
            ).count()
            if owner_count <= 1:
                raise ValueError(
                    "Cannot demote the last owner. Transfer ownership first."
                )
        self.role = new_role
        self.save(update_fields=["role"])

    def delete(self, *args, **kwargs):
        """Prevent removing the last owner from an organization."""
        if self.role == OrganizationRole.OWNER:
            owner_count = self.organization.memberships.filter(
                role=OrganizationRole.OWNER
            ).count()
            if owner_count <= 1:
                raise ValueError(
                    "Cannot remove the last owner. Transfer ownership or delete the organization."
                )
        super().delete(*args, **kwargs)


class SSOProviderType(models.TextChoices):
    """Supported SSO provider types."""

    SAML = "saml", _("SAML 2.0")
    OIDC = "oidc", _("OpenID Connect")


class SSOConfiguration(models.Model):
    """SSO/SAML configuration for an organization.

    Each organization can have at most one SSO configuration. When
    ``enforce_sso`` is True, non-SSO login is blocked for org members
    (checked by SecurityPolicyMiddleware).
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="sso_config",
    )
    provider_type = models.CharField(
        max_length=10,
        choices=SSOProviderType.choices,
        default=SSOProviderType.SAML,
    )
    metadata_url = models.URLField(
        max_length=2048,
        blank=True,
        default="",
        help_text="IdP metadata URL for automatic configuration.",
    )
    entity_id = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="IdP entity ID / issuer.",
    )
    certificate = models.TextField(
        blank=True,
        default="",
        help_text="IdP X.509 certificate (PEM-encoded).",
    )
    is_active = models.BooleanField(default=False)
    enforce_sso = models.BooleanField(
        default=False,
        help_text="When True, password/OAuth login is blocked for org members.",
    )
    emergency_bypass_enabled = models.BooleanField(
        default=False,
        help_text="When True, emergency bypass login is available via bypass code.",
    )
    emergency_bypass_code = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Randomly generated code for emergency SSO bypass login.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "SSO Configuration"
        verbose_name_plural = "SSO Configurations"

    def __str__(self):
        return f"SSO ({self.get_provider_type_display()}) for {self.organization.name}"

    def save(self, *args, **kwargs):
        """Auto-generate emergency bypass code on creation if not set."""
        if not self.emergency_bypass_code:
            self.emergency_bypass_code = secrets.token_urlsafe(32)
        super().save(*args, **kwargs)


class SCIMToken(models.Model):
    """SCIM 2.0 bearer token for automated user provisioning.

    Tokens are stored as SHA-256 hashes; the plaintext is returned only on
    creation. Each token is scoped to a single organization.
    Multiple active tokens per org are allowed for zero-downtime rotation.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="scim_tokens",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional human-readable label for this token.",
    )
    token_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hex digest of the bearer token.",
    )
    prefix = models.CharField(
        max_length=8,
        help_text="First 8 chars of the token for identification.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        help_text="IP address of the most recent request using this token.",
    )
    allowed_cidrs = models.JSONField(
        default=list,
        blank=True,
        help_text='Optional IP allowlist as list of CIDR strings, e.g. ["10.0.0.0/8"]. Empty means allow all.',
    )

    class Meta:
        verbose_name = "SCIM Token"
        verbose_name_plural = "SCIM Tokens"

    def __str__(self):
        return f"SCIM token {self.prefix}... for {self.organization.name}"


class EnterpriseConfig(models.Model):
    """Per-user enterprise mode configuration.

    Controls whether enterprise features (orgs, teams, SCIM, SSO, sharing)
    are available for this user. Disabled by default — the platform is
    single-user oriented. Enterprise mode is opt-in for paid users.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="enterprise_config",
    )
    enabled = models.BooleanField(
        default=False,
        help_text="Whether enterprise features are active for this user.",
    )
    enabled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When enterprise mode was last enabled.",
    )
    disabled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When enterprise mode was last disabled.",
    )
    # Grace period: when a paid subscription lapses, enterprise features become
    # read-only for 30 days. After that, enterprise mode is forcibly disabled.
    grace_period_end = models.DateTimeField(
        null=True,
        blank=True,
        help_text="End of read-only grace period after subscription lapse.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Enterprise Configuration"
        verbose_name_plural = "Enterprise Configurations"

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"Enterprise ({status}) for user {self.user_id}"

    @property
    def is_in_grace_period(self) -> bool:
        """Check if enterprise mode is in read-only grace period."""
        if self.grace_period_end and self.enabled:
            return timezone.now() < self.grace_period_end
        return False

    @property
    def is_grace_period_expired(self) -> bool:
        """Check if the grace period has expired (should forcibly disable)."""
        if self.grace_period_end:
            return timezone.now() >= self.grace_period_end
        return False


class Invitation(models.Model):
    """Email or link invitation to join an organization.

    Invitations are identified by a unique token. They can be single-use
    (email invites) or multi-use (shareable links). An invitation is
    considered pending while it is active and not expired.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="invitations",
    )
    email = models.EmailField(
        null=True,
        blank=True,
        help_text="Target email for email invites. Null for link invites.",
    )
    role = models.CharField(
        max_length=20,
        choices=OrganizationRole.choices,
        default=OrganizationRole.MEMBER,
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the invitation expires. Null = never expires.",
    )
    max_uses = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Max number of times a link invite can be accepted. Null = unlimited.",
    )
    use_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Invitation"
        verbose_name_plural = "Invitations"

    def __str__(self):
        target = self.email or "link invite"
        return f"Invite to {self.organization.name} ({target})"

    @property
    def is_expired(self) -> bool:
        """Check if the invitation has passed its expiration time."""
        if self.expires_at is None:
            return False
        return timezone.now() > self.expires_at

    @property
    def is_usable(self) -> bool:
        """Check if the invitation can still be accepted."""
        if not self.is_active:
            return False
        if self.is_expired:
            return False
        if self.max_uses is not None and self.use_count >= self.max_uses:
            return False
        return True


class PasswordResetOTP(models.Model):
    """
    Stores OTP tokens for password reset functionality.
    OTPs expire after 15 minutes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_otps",
    )
    otp = models.CharField(max_length=6)  # 6-digit OTP
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Password Reset OTP"
        verbose_name_plural = "Password Reset OTPs"

    def __str__(self):
        return f"OTP for {self.user.email} - {'Used' if self.used else 'Active'}"

    @property
    def is_expired(self):
        """Check whether this OTP has passed its expiration time.

        Returns:
            bool: True if the OTP is expired, False otherwise.
        """
        from django.utils import timezone

        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        """Check whether this OTP is still usable (not used and not expired).

        Returns:
            bool: True if the OTP is valid, False otherwise.
        """
        return not self.used and not self.is_expired


class NotificationType(models.TextChoices):
    """Types of notifications the system can produce."""

    INJECTION = "injection", _("Injection")
    MENTION = "mention", _("Mention")
    AGENT_COMPLETED = "agent_completed", _("Agent Completed")
    INVITATION = "invitation", _("Invitation")
    SHARE = "share", _("Share")
    SPENDING_ALERT = "spending_alert", _("Spending Alert")


class Notification(models.Model):
    """A notification delivered to a user about an event in the platform.

    Notifications are created by the notification service and may be delivered
    via multiple channels (in-app, email, Slack, Discord) depending on the
    user's preferences.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True, default="")
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Metadata: conversation_id, project_id, actor_id, etc.",
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]

    def __str__(self):
        return f"[{self.type}] {self.title} → {self.user_id}"


class NotificationPreference(models.Model):
    """Per-notification-type channel preferences for a user.

    Each row controls which channels are enabled for a specific
    notification type. Missing rows default to in_app=True, email=True.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NotificationType.choices,
    )
    in_app = models.BooleanField(default=True)
    email = models.BooleanField(default=True)
    push = models.BooleanField(default=False)
    slack = models.BooleanField(default=False)
    discord = models.BooleanField(default=False)
    muted_project_ids = models.JSONField(
        default=list,
        blank=True,
        help_text="List of project UUIDs for which this notification type is muted.",
    )

    class Meta:
        unique_together = [("user", "notification_type")]
        verbose_name = "Notification Preference"
        verbose_name_plural = "Notification Preferences"

    def __str__(self):
        return f"{self.notification_type} prefs for {self.user_id}"


class OrgSlackIntegration(models.Model):
    """Slack incoming webhook integration for an organization.

    When active, notifications matching user preferences are forwarded
    to the configured Slack channel as formatted message blocks.
    Only available in enterprise mode.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="slack_integration",
    )
    webhook_url = models.URLField(max_length=2048)
    channel_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name of the Slack channel (informational only).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Slack Integration"
        verbose_name_plural = "Org Slack Integrations"

    def __str__(self):
        return f"Slack for {self.organization.name}"


class OrgSlackApp(models.Model):
    """Slack app installation for an organization.

    Stores the Slack app OAuth installation (bot token, app ID, team ID)
    for an org. Used for claw mode messaging and org notifications in Slack.
    Only available in enterprise mode.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        "Organization",
        on_delete=models.CASCADE,
        related_name="slack_app",
    )
    bot_token = EncryptedCharField(
        max_length=512,
        help_text="Encrypted Slack bot OAuth token (xoxb-...).",
    )
    app_id = models.CharField(max_length=255, blank=True, default="")
    team_id = models.CharField(max_length=255, blank=True, default="")
    channel_id = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Default Slack channel ID for org notifications.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Slack App"
        verbose_name_plural = "Org Slack Apps"

    def __str__(self):
        return f"SlackApp for {self.organization.name}"


class OrgDiscordIntegration(models.Model):
    """Discord webhook integration for an organization.

    When active, notifications matching user preferences are forwarded
    to the configured Discord channel as embed messages.
    Only available in enterprise mode.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="discord_integration",
    )
    webhook_url = models.URLField(max_length=2048)
    channel_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Display name of the Discord channel (informational only).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Discord Integration"
        verbose_name_plural = "Org Discord Integrations"

    def __str__(self):
        return f"Discord for {self.organization.name}"


class OrgCostPolicy(models.Model):
    """Per-organization spending controls: member monthly credit limits and alert thresholds.

    Null ``member_monthly_credit_limit`` means unlimited. The alert fires when a
    member's cumulative monthly usage crosses ``alert_threshold_percent`` of their limit.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="cost_policy",
    )
    member_monthly_credit_limit = models.IntegerField(
        null=True,
        blank=True,
        help_text="Max credits per member per month. Null = unlimited.",
    )
    alert_threshold_percent = models.IntegerField(
        default=80,
        help_text="Alert org admins when a member's usage crosses this % of their limit.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Cost Policy"
        verbose_name_plural = "Org Cost Policies"

    def __str__(self):
        limit = self.member_monthly_credit_limit or "unlimited"
        return f"Cost policy for {self.organization.name}: {limit}/member/month"


class OrgModelPolicy(models.Model):
    """Per-organization LLM model restrictions.

    Controls which models and providers org members can use in org projects.
    Empty allowed_models/allowed_providers means all are permitted (allow-all).
    When block_byom is True, members cannot use personal BYOM keys in org projects.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="model_policy",
    )
    allowed_models = models.JSONField(
        default=list,
        blank=True,
        help_text='List of allowed model ID strings (e.g. ["claude-sonnet-4", "gpt-4o"]). Empty = all allowed.',
    )
    allowed_providers = models.JSONField(
        default=list,
        blank=True,
        help_text='List of allowed provider strings (e.g. ["anthropic", "openai"]). Empty = all allowed.',
    )
    block_byom = models.BooleanField(
        default=False,
        help_text="When True, members cannot use personal BYOM keys in org projects.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Model Policy"
        verbose_name_plural = "Org Model Policies"

    def __str__(self):
        models_str = (
            ", ".join(self.allowed_models[:3]) if self.allowed_models else "all"
        )
        return f"Model policy for {self.organization.name}: {models_str}"


class OrgAgentPolicy(models.Model):
    """Per-organization agent guardrails.

    Controls which tools agents can use in org projects, which tool groups
    are blocked, and which tools require human-in-the-loop approval.
    Empty blocked_tools/blocked_tool_groups means nothing is blocked.
    Empty require_hitl_for means no tools require human approval.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="agent_policy",
    )
    blocked_tools = models.JSONField(
        default=list,
        blank=True,
        help_text='List of individual tool names to block (e.g. ["shell", "browse"]).',
    )
    blocked_tool_groups = models.JSONField(
        default=list,
        blank=True,
        help_text='List of tool group names to block (e.g. ["file", "shell", "media_gen"]).',
    )
    require_hitl_for = models.JSONField(
        default=list,
        blank=True,
        help_text="List of tool names requiring human approval before execution.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Agent Policy"
        verbose_name_plural = "Org Agent Policies"

    def __str__(self):
        blocked = len(self.blocked_tools) + len(self.blocked_tool_groups)
        hitl = len(self.require_hitl_for)
        return (
            f"Agent policy for {self.organization.name}: {blocked} blocked, {hitl} HITL"
        )


class IPAllowlistEntry(models.Model):
    """IP allowlist entry restricting org access to specific CIDR ranges.

    When an org has any active entries, only requests from matching IPs
    are permitted for org-scoped API calls. Empty allowlist = no restriction.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="ip_allowlist_entries",
    )
    cidr_range = models.CharField(
        max_length=50,
        help_text="IPv4 or IPv6 CIDR notation (e.g. 10.0.0.0/24, ::1/128).",
    )
    description = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "IP Allowlist Entry"
        verbose_name_plural = "IP Allowlist Entries"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.cidr_range} ({self.organization.name})"


class ConditionalAccessAction(models.TextChoices):
    ALLOW = "allow", "Allow"
    BLOCK = "block", "Block"
    REQUIRE_MFA = "require_mfa", "Require MFA"


class ConditionalAccessPolicy(models.Model):
    """Conditional access policy restricting org access based on conditions.

    Conditions are a list of objects, each with a ``type`` field and type-specific
    parameters. Supported types:

    - ``ip_range``: ``{"type": "ip_range", "cidr": "10.0.0.0/24"}``
    - ``time_of_day``: ``{"type": "time_of_day", "start_hour": 9, "end_hour": 17, "timezone": "UTC"}``
    - ``day_of_week``: ``{"type": "day_of_week", "days": [0, 1, 2, 3, 4]}``  (0=Mon, 6=Sun)
    - ``user_agent_pattern``: ``{"type": "user_agent_pattern", "pattern": ".*Mobile.*"}``

    All conditions within a policy must match for the policy to trigger (AND).
    Policies are evaluated in ``priority`` order (ascending); the first matching
    policy determines the action.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="access_policies",
    )
    name = models.CharField(max_length=255)
    conditions = models.JSONField(
        default=list,
        help_text="List of condition objects (AND logic).",
    )
    action = models.CharField(
        max_length=20,
        choices=ConditionalAccessAction.choices,
        default=ConditionalAccessAction.BLOCK,
    )
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(
        default=0,
        help_text="Lower number = higher priority. First match wins.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conditional Access Policy"
        verbose_name_plural = "Conditional Access Policies"
        ordering = ["priority", "created_at"]

    def __str__(self):
        return f"{self.name} ({self.organization.name}) - {self.action}"


class OrgAPIKey(models.Model):
    """API key belonging to an organization (not a specific user).

    Tokens are stored as SHA-256 hashes; the plaintext is returned only on
    creation. Each key is scoped to a single organization and has its own
    rate limit. Agent runs via org API keys are billed to the billing_user
    (defaults to the key creator).
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="api_keys",
    )
    key_hash = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="SHA-256 hex digest of the API key.",
    )
    key_prefix = models.CharField(
        max_length=8,
        help_text="First 8 chars of the key for identification.",
    )
    name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Human-readable label for this key.",
    )
    scopes = models.JSONField(
        default=list,
        blank=True,
        help_text='List of permission scopes (e.g. ["agent:run", "read"]).',
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_org_api_keys",
    )
    billing_user = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="billed_org_api_keys",
        help_text="User whose wallet is billed for agent runs via this key.",
    )
    is_active = models.BooleanField(default=True)
    rate_limit_per_minute = models.IntegerField(
        default=120,
        help_text="Max requests per minute for this key.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Org API Key"
        verbose_name_plural = "Org API Keys"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.key_prefix}... ({self.organization.name})"


class WebhookDestinationType(models.TextChoices):
    """Supported outbound webhook destination formats."""

    GENERIC = "generic", _("Generic (JSON + HMAC)")
    SLACK = "slack", _("Slack (Block Kit)")
    DISCORD = "discord", _("Discord (Embed)")


class OrgWebhook(models.Model):
    """Outbound webhook subscription for an organization.

    When events matching the subscribed types occur, a signed JSON payload
    is POSTed to the configured URL. Webhooks auto-disable after 10
    consecutive delivery failures.
    """

    WEBHOOK_EVENT_TYPES = [
        "agent_run.completed",
        "agent_run.failed",
        "member.joined",
        "member.removed",
        "project.created",
        "project.shared",
        "audit.security_event",
        "dlp.violation",
    ]

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="webhooks",
    )
    url = models.URLField(max_length=2048)
    secret = models.CharField(
        max_length=255,
        help_text="Shared secret for HMAC-SHA256 signing.",
    )
    events = models.JSONField(
        default=list,
        help_text="List of event types this webhook subscribes to.",
    )
    destination_type = models.CharField(
        max_length=10,
        choices=WebhookDestinationType.choices,
        default=WebhookDestinationType.GENERIC,
    )
    is_active = models.BooleanField(default=True)
    failure_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Webhook"
        verbose_name_plural = "Org Webhooks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Webhook {self.url} ({self.organization.name})"


class WebhookDeliveryLog(models.Model):
    """Log of webhook delivery attempts for debugging.

    Stores the last 100 deliveries per webhook. Older entries are
    pruned by the delivery task.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    webhook = models.ForeignKey(
        OrgWebhook,
        on_delete=models.CASCADE,
        related_name="delivery_logs",
    )
    event_type = models.CharField(max_length=50)
    status_code = models.IntegerField(null=True, blank=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Webhook Delivery Log"
        verbose_name_plural = "Webhook Delivery Logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["webhook", "-created_at"]),
        ]

    def __str__(self):
        status = "OK" if self.success else f"FAIL({self.status_code})"
        return f"{self.event_type} → {status}"


class DLPPolicy(models.Model):
    """Data Loss Prevention policy for an organization.

    Scans outgoing messages for sensitive data (PII, secrets, API keys)
    before they are sent to LLMs. Each pattern can block or redact matches.
    Only applies to org project conversations, not personal conversations.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="dlp_policy",
    )
    scan_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            'List of {name, regex, action} dicts. action is "block" or "redact".'
        ),
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "DLP Policy"
        verbose_name_plural = "DLP Policies"

    def __str__(self):
        count = len(self.scan_patterns) if self.scan_patterns else 0
        return f"DLP policy for {self.organization.name}: {count} patterns"


class OrgArchivalPolicy(models.Model):
    """Per-organization conversation archival policy for regulatory compliance.

    Controls whether conversations are automatically archived and how long
    archives are retained. Required for regulated industries (finance, healthcare).
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="archival_policy",
    )
    is_active = models.BooleanField(
        default=False,
        help_text="Whether automatic archival is enabled for this organization.",
    )
    archive_all_conversations = models.BooleanField(
        default=True,
        help_text="If True, archive all conversations. If False, archival is opt-in.",
    )
    retention_years = models.IntegerField(
        default=7,
        help_text="Number of years to retain archived conversations.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Org Archival Policy"
        verbose_name_plural = "Org Archival Policies"

    def __str__(self):
        status = "active" if self.is_active else "inactive"
        return f"Archival policy for {self.organization.name}: {status}, {self.retention_years}y"
