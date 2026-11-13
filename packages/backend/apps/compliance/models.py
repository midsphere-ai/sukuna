"""Compliance models for enterprise audit logging and consent versioning."""

import hashlib
import json
import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class AuditAction(models.TextChoices):
    """Enumeration of auditable actions."""

    # Auth
    LOGIN = "login", _("Login")
    LOGOUT = "logout", _("Logout")
    LOGIN_FAILED = "login_failed", _("Login Failed")

    # CRUD
    CREATE = "create", _("Create")
    UPDATE = "update", _("Update")
    DELETE = "delete", _("Delete")

    # Agent operations
    AGENT_RUN_START = "agent_run_start", _("Agent Run Start")
    AGENT_RUN_COMPLETE = "agent_run_complete", _("Agent Run Complete")
    AGENT_RUN_FAIL = "agent_run_fail", _("Agent Run Fail")
    AGENT_RUN_CANCEL = "agent_run_cancel", _("Agent Run Cancel")

    # Social auth
    SOCIAL_ACCOUNT_ADDED = "social_account_added", _("Social Account Added")
    SOCIAL_ACCOUNT_REMOVED = "social_account_removed", _("Social Account Removed")

    # Data access
    EXPORT = "export", _("Data Export")

    # Billing
    SUBSCRIPTION_CHANGE = "subscription_change", _("Subscription Change")

    # Consent
    CONSENT_GRANTED = "consent_granted", _("Consent Granted")
    CONSENT_REVOKED = "consent_revoked", _("Consent Revoked")

    # SSO
    SSO_CONFIG_CREATED = "sso_config_created", _("SSO Config Created")
    SSO_CONFIG_UPDATED = "sso_config_updated", _("SSO Config Updated")
    SSO_CONFIG_DELETED = "sso_config_deleted", _("SSO Config Deleted")

    # SCIM provisioning
    SCIM_USER_PROVISIONED = "scim_user_provisioned", _("SCIM User Provisioned")
    SCIM_USER_UPDATED = "scim_user_updated", _("SCIM User Updated")
    SCIM_USER_DEPROVISIONED = "scim_user_deprovisioned", _("SCIM User Deprovisioned")

    # SCIM token management
    SCIM_TOKEN_CREATED = "scim_token_created", _("SCIM Token Created")
    SCIM_TOKEN_REVOKED = "scim_token_revoked", _("SCIM Token Revoked")

    # Enterprise mode
    ENTERPRISE_MODE_ENABLED = "enterprise_mode_enabled", _("Enterprise Mode Enabled")
    ENTERPRISE_MODE_DISABLED = "enterprise_mode_disabled", _("Enterprise Mode Disabled")

    # Organization lifecycle
    ORG_DELETED = "org_deleted", _("Organization Deleted")
    ORG_FROZEN = "org_frozen", _("Organization Frozen")
    ORG_UNFROZEN = "org_unfrozen", _("Organization Unfrozen")
    ORG_SLUG_CHANGED = "org_slug_changed", _("Organization Slug Changed")

    # SSO resilience
    SSO_EMERGENCY_BYPASS = "sso_emergency_bypass", _("SSO Emergency Bypass")
    SSO_FORCE_LOGOUT = "sso_force_logout", _("SSO Force Logout")

    # Project sharing
    PROJECT_SHARED = "project_shared", _("Project Shared")
    PROJECT_SHARE_UPDATED = "project_share_updated", _("Project Share Updated")
    PROJECT_SHARE_REVOKED = "project_share_revoked", _("Project Share Revoked")

    # Conversation participants
    PARTICIPANT_JOINED = "participant_joined", _("Participant Joined Conversation")

    # Invitations
    INVITATION_CREATED = "invitation_created", _("Invitation Created")
    INVITATION_ACCEPTED = "invitation_accepted", _("Invitation Accepted")
    INVITATION_REVOKED = "invitation_revoked", _("Invitation Revoked")

    # User injection
    INJECTION = "injection", _("Message Injection")

    # Project moves
    PROJECT_MOVED = "project_moved", _("Project Moved")

    # IP allowlist
    IP_ALLOWLIST_ADDED = "ip_allowlist_added", _("IP Allowlist Entry Added")
    IP_ALLOWLIST_REMOVED = "ip_allowlist_removed", _("IP Allowlist Entry Removed")
    IP_ACCESS_BLOCKED = "ip_access_blocked", _("IP Access Blocked")

    # Org API keys
    ORG_API_KEY_CREATED = "org_api_key_created", _("Org API Key Created")
    ORG_API_KEY_REVOKED = "org_api_key_revoked", _("Org API Key Revoked")

    # Compliance exports
    COMPLIANCE_EXPORT_RUN = "compliance_export_run", _("Compliance Export Run")

    # DLP
    DLP_BLOCK = "dlp_block", _("DLP Block")
    DLP_REDACT = "dlp_redact", _("DLP Redact")

    # Webhooks
    WEBHOOK_CREATED = "webhook_created", _("Webhook Created")
    WEBHOOK_UPDATED = "webhook_updated", _("Webhook Updated")
    WEBHOOK_DELETED = "webhook_deleted", _("Webhook Deleted")
    WEBHOOK_AUTO_DISABLED = "webhook_auto_disabled", _("Webhook Auto-Disabled")

    # Conversation archival
    CONVERSATION_ARCHIVED = "conversation_archived", _("Conversation Archived")
    ARCHIVE_VERIFIED = "archive_verified", _("Archive Verified")

    # Conditional access
    ACCESS_POLICY_CREATED = "access_policy_created", _("Access Policy Created")
    ACCESS_POLICY_UPDATED = "access_policy_updated", _("Access Policy Updated")
    ACCESS_POLICY_DELETED = "access_policy_deleted", _("Access Policy Deleted")
    ACCESS_POLICY_BLOCKED = "access_policy_blocked", _("Access Policy Blocked")

    # Telegram integration
    TELEGRAM_LINKED = "telegram_linked", _("Telegram Account Linked")
    TELEGRAM_UNLINKED = "telegram_unlinked", _("Telegram Account Unlinked")
    TELEGRAM_MESSAGE = "telegram_message", _("Telegram Message")

    # Slack integration
    SLACK_LINKED = "slack_linked", _("Slack Account Linked")
    SLACK_UNLINKED = "slack_unlinked", _("Slack Account Unlinked")
    SLACK_MESSAGE = "slack_message", _("Slack Message")

    # Discord integration
    DISCORD_LINKED = "discord_linked", _("Discord Account Linked")
    DISCORD_UNLINKED = "discord_unlinked", _("Discord Account Unlinked")
    DISCORD_MESSAGE = "discord_message", _("Discord Message")

    # Multi-factor authentication
    MFA_ENROLLED = "mfa_enrolled", _("MFA Authenticator Enrolled")
    MFA_REMOVED = "mfa_removed", _("MFA Authenticator Removed")
    MFA_CHALLENGE_PASSED = "mfa_challenge_passed", _("MFA Challenge Passed")
    MFA_CHALLENGE_FAILED = "mfa_challenge_failed", _("MFA Challenge Failed")
    MFA_RECOVERY_CODES_GENERATED = (
        "mfa_recovery_codes_generated",
        _("MFA Recovery Codes Generated"),
    )


class ConsentType(models.TextChoices):
    """Types of consent that can be granted or revoked."""

    ANALYTICS = "analytics", _("Analytics Data Sharing")
    TRAINING = "training", _("AI Training Data Sharing")
    MARKETING = "marketing", _("Marketing Communications")
    TERMS_OF_SERVICE = "terms_of_service", _("Terms of Service")
    PRIVACY_POLICY = "privacy_policy", _("Privacy Policy")


class AuditLog(models.Model):
    """Immutable audit log entry for compliance tracking.

    This model enforces immutability: once created, records cannot be
    updated or deleted through the Django ORM. The save() and delete()
    methods are overridden to prevent modification of existing records.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    # Who performed the action
    actor_id = models.UUIDField(null=True, blank=True, db_index=True)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    actor_ip = models.GenericIPAddressField(null=True, blank=True)

    # What happened
    action = models.CharField(max_length=50, choices=AuditAction.choices, db_index=True)
    resource_type = models.CharField(max_length=100, db_index=True)
    resource_id = models.CharField(max_length=255, blank=True, default="")

    # Context
    request_id = models.CharField(max_length=64, blank=True, default="")
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        indexes = [
            models.Index(fields=["actor_id", "-timestamp"], name="audit_actor_ts_idx"),
            models.Index(
                fields=["resource_type", "resource_id"], name="audit_resource_idx"
            ),
            models.Index(fields=["action", "-timestamp"], name="audit_action_ts_idx"),
        ]

    def __str__(self):
        return f"[{self.timestamp}] {self.action} {self.resource_type}/{self.resource_id} by {self.actor_email or self.actor_id or 'system'}"

    def save(self, *args, **kwargs):
        """Only allow initial creation — updates are blocked."""
        if not self._state.adding:
            raise ValueError("AuditLog records are immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of audit log records."""
        raise ValueError("AuditLog records are immutable and cannot be deleted.")

    @classmethod
    def log(
        cls,
        *,
        action: str,
        resource_type: str,
        resource_id: str = "",
        actor_id=None,
        actor_email: str = "",
        actor_ip: str | None = None,
        request_id: str = "",
        changes: dict | None = None,
        metadata: dict | None = None,
    ) -> "AuditLog":
        """Convenience factory method for creating audit log entries.

        Args:
            action: The action performed (use AuditAction choices).
            resource_type: The type of resource affected (e.g., "user", "conversation").
            resource_id: The ID of the affected resource.
            actor_id: UUID of the user who performed the action.
            actor_email: Email of the actor (denormalized for immutability).
            actor_ip: IP address of the request.
            request_id: Correlation ID from the request middleware.
            changes: Dict of before/after values for updates.
            metadata: Additional context.

        Returns:
            The created AuditLog instance.
        """
        return cls.objects.create(
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            actor_id=actor_id,
            actor_email=actor_email,
            actor_ip=actor_ip,
            request_id=request_id,
            changes=changes or {},
            metadata=metadata or {},
        )


class ConsentRecord(models.Model):
    """Versioned, append-only consent record.

    Every consent change (grant or revoke) creates a new immutable record.
    This provides a full audit trail of consent history per user and type,
    satisfying GDPR's requirement for demonstrable, versioned consent.

    The ``user`` FK uses SET_NULL so records survive user deletion —
    the denormalized ``user_email`` preserves identity for compliance.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)

    # Who
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consent_records",
    )
    user_email = models.CharField(max_length=254, blank=True, default="")

    # What
    consent_type = models.CharField(
        max_length=50,
        choices=ConsentType.choices,
        db_index=True,
    )
    version = models.CharField(
        max_length=50,
        help_text="Version of the policy/terms the user consented to (e.g. '2.1', '2026-04-01').",
    )
    action = models.CharField(
        max_length=10,
        choices=[("granted", "Granted"), ("revoked", "Revoked")],
    )

    # When / Where
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-recorded_at"]
        verbose_name = "Consent Record"
        verbose_name_plural = "Consent Records"
        indexes = [
            models.Index(
                fields=["user", "consent_type", "-recorded_at"],
                name="consent_user_type_ts_idx",
            ),
            models.Index(
                fields=["consent_type", "-recorded_at"], name="consent_type_ts_idx"
            ),
        ]

    def __str__(self):
        return f"[{self.recorded_at}] {self.consent_type} {self.action} v{self.version} — {self.user_email or self.user_id or 'anonymous'}"

    def save(self, *args, **kwargs):
        """Only allow initial creation — consent records are append-only."""
        if not self._state.adding:
            raise ValueError(
                "ConsentRecord entries are immutable and cannot be updated."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of consent records."""
        raise ValueError("ConsentRecord entries are immutable and cannot be deleted.")


class RetentionAction(models.TextChoices):
    """Actions to take when retention period expires."""

    DELETE = "delete", _("Delete")
    ANONYMIZE = "anonymize", _("Anonymize")
    KEEP = "keep", _("Keep")


class RetentionPolicy(models.Model):
    """Configurable data retention policy per resource type.

    Defines how long different types of data are kept and what action
    (delete or anonymize) to take when the retention period expires.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    resource_type = models.CharField(
        max_length=100,
        unique=True,
        help_text="The type of resource this policy applies to (e.g. audit_logs, conversations).",
    )
    retention_days = models.PositiveIntegerField(
        help_text="Number of days to retain records before applying the action.",
    )
    action = models.CharField(
        max_length=20,
        choices=RetentionAction.choices,
        help_text="Action to take on expired records.",
    )
    is_active = models.BooleanField(default=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    records_affected_last_run = models.IntegerField(default=0)

    class Meta:
        ordering = ["resource_type"]
        verbose_name = "Retention Policy"
        verbose_name_plural = "Retention Policies"

    def __str__(self):
        return f"{self.resource_type}: {self.retention_days}d ({self.get_action_display()})"


class UserSession(models.Model):
    """Tracks active user sessions for concurrent session limit enforcement.

    Each record maps a Django session key to a user, allowing the system to
    count active sessions and evict the oldest when limits are exceeded.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tracked_sessions",
    )
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-last_activity"]
        verbose_name = "User Session"
        verbose_name_plural = "User Sessions"
        indexes = [
            models.Index(
                fields=["user", "-last_activity"], name="session_user_activity_idx"
            ),
        ]

    def __str__(self):
        return f"Session {self.session_key[:8]}… for {self.user_id} (last active {self.last_activity})"


class ExportType(models.TextChoices):
    """Types of compliance data that can be exported."""

    AUDIT_LOG = "audit_log", _("Audit Log")
    CONSENT = "consent", _("Consent Records")
    RETENTION = "retention", _("Retention Policy Status")


class ExportFormat(models.TextChoices):
    """Supported export file formats."""

    CSV = "csv", _("CSV")
    JSON = "json", _("JSON")


class ExportSchedule(models.TextChoices):
    """Export schedule frequency."""

    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")
    MONTHLY = "monthly", _("Monthly")


class DestinationType(models.TextChoices):
    """Export destination types."""

    S3 = "s3", _("Amazon S3")
    EMAIL = "email", _("Email")


class ComplianceExportConfig(models.Model):
    """Scheduled compliance export configuration.

    Defines automated exports of audit logs, consent records, or retention
    status to S3 or email destinations. Supports incremental exports
    (only records since last_export_at).
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    organization = models.ForeignKey(
        "workspace.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="compliance_export_configs",
        help_text="Organization scope. Null for platform-wide exports.",
    )
    export_type = models.CharField(
        max_length=20,
        choices=ExportType.choices,
        db_index=True,
        help_text="Type of compliance data to export.",
    )
    format = models.CharField(
        max_length=10,
        choices=ExportFormat.choices,
        default=ExportFormat.CSV,
        help_text="File format for the export.",
    )
    schedule = models.CharField(
        max_length=10,
        choices=ExportSchedule.choices,
        default=ExportSchedule.DAILY,
        help_text="How often to run the export.",
    )
    destination_type = models.CharField(
        max_length=10,
        choices=DestinationType.choices,
        help_text="Where to send the export.",
    )
    destination_config = models.JSONField(
        default=dict,
        help_text="Destination-specific config: {bucket, prefix} for S3, {emails: [...]} for email.",
    )
    is_active = models.BooleanField(default=True)
    last_export_at = models.DateTimeField(null=True, blank=True)
    last_export_record_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Compliance Export Config"
        verbose_name_plural = "Compliance Export Configs"

    def __str__(self):
        org_label = self.organization.name if self.organization else "platform"
        return f"{self.export_type} → {self.destination_type} ({org_label}, {self.schedule})"


class ConversationArchive(models.Model):
    """Immutable, tamper-evident archive of a conversation snapshot.

    Each archive captures a full conversation snapshot (messages, participants,
    agent runs, tool calls) at a point in time. A SHA-256 content_hash enables
    tamper-evidence verification. Multiple archive versions can exist for the
    same conversation (append-only versioning when conversations are updated
    after initial archival).

    Immutability is enforced via save()/delete() overrides, following the
    same pattern as AuditLog. The only exception is GDPR anonymization,
    which uses a dedicated method that bypasses the immutability guard.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    conversation = models.ForeignKey(
        "storage.Conversation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archives",
        help_text="Source conversation. SET_NULL so archive survives conversation deletion.",
    )
    organization = models.ForeignKey(
        "workspace.Organization",
        on_delete=models.CASCADE,
        related_name="conversation_archives",
    )
    archived_by = models.CharField(
        max_length=254,
        help_text="'auto' for automatic archival, or the email of the user who triggered it.",
    )
    archived_at = models.DateTimeField(auto_now_add=True, db_index=True)
    content_hash = models.CharField(
        max_length=64,
        db_index=True,
        help_text="SHA-256 hex digest of the JSON-serialized content field.",
    )
    content = models.JSONField(
        default=dict,
        help_text=(
            "Full conversation snapshot: messages, participants, timestamps, "
            "agent runs, tool calls."
        ),
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Archive version number for this conversation (append-only).",
    )

    class Meta:
        ordering = ["-archived_at"]
        verbose_name = "Conversation Archive"
        verbose_name_plural = "Conversation Archives"
        indexes = [
            models.Index(
                fields=["conversation", "-archived_at"],
                name="archive_conv_ts_idx",
            ),
            models.Index(
                fields=["organization", "-archived_at"],
                name="archive_org_ts_idx",
            ),
        ]

    def __str__(self):
        conv_label = self.conversation_id or "[deleted]"
        return f"Archive v{self.version} of {conv_label} at {self.archived_at}"

    def save(self, *args, **kwargs):
        """Only allow initial creation — archives are immutable."""
        if not self._state.adding:
            # Allow GDPR anonymization via internal flag
            if getattr(self, "_allow_gdpr_update", False):
                super().save(*args, **kwargs)
                return
            raise ValueError(
                "ConversationArchive records are immutable and cannot be updated."
            )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of archive records."""
        raise ValueError(
            "ConversationArchive records are immutable and cannot be deleted."
        )

    @staticmethod
    def compute_hash(content: dict) -> str:
        """Compute SHA-256 hash of content dict for tamper-evidence."""
        canonical = json.dumps(content, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def verify(self) -> bool:
        """Verify that the content has not been tampered with."""
        return self.compute_hash(self.content) == self.content_hash

    def anonymize_for_gdpr(self):
        """Anonymize archive content for GDPR compliance.

        Replaces user-identifying information with '[Deleted User]' while
        preserving the archive record structure. Updates content_hash to
        match the anonymized content.
        """
        content = self.content.copy()

        # Anonymize conversation-level fields
        if "user_email" in content:
            content["user_email"] = "[Deleted User]"
        if "title" in content:
            content["title"] = "[Deleted User]"

        # Anonymize participants
        for p in content.get("participants", []):
            if "email" in p:
                p["email"] = "[Deleted User]"
            if "username" in p:
                p["username"] = "[Deleted User]"

        # Anonymize agent run user references
        for run in content.get("agent_runs", []):
            if "user_email" in run:
                run["user_email"] = "[Deleted User]"

        self.content = content
        self.content_hash = self.compute_hash(content)
        self.archived_by = (
            "[Deleted User]" if self.archived_by != "auto" else self.archived_by
        )
        self._allow_gdpr_update = True
        try:
            self.save(update_fields=["content", "content_hash", "archived_by"])
        finally:
            self._allow_gdpr_update = False
