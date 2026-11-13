"""Django ORM models for the sandbox agent server.

Two categories:

A. **Sandbox-owned** (managed=True) — DDL owned by sandbox migrations.
   - SandboxRun        → table ``agent_runs``
   - SandboxEvent      → table ``agent_events``
   - HitlRequest       → table ``hitl_requests``

B. **Backend-owned** (managed=False) — DDL owned by the Django backend.
   The sandbox reads/writes these directly instead of via webhooks.
   - DjangoAgentRun          → table ``storage_agentrun``
   - DjangoConversation      → table ``storage_conversation``
   - DjangoConversationPlan  → table ``storage_conversationplan``
   - DjangoStoredFile        → table ``storage_storedfile``       (attachments)
   - DjangoConversationFile  → table ``storage_conversationfile`` (attachments)
   - DjangoUser              → table ``users_user``               (auth — read-only)
   - DjangoAuthToken         → table ``authtoken_token``          (auth — read-only)
   - DjangoOrganization      → table ``workspace_organization``   (DLP — read-only)
   - DjangoProject           → table ``spaces_project``           (DLP — read-only)
   - DjangoDLPPolicy         → table ``workspace_dlppolicy``      (DLP scan patterns — read-only)
   - DjangoAuditLog          → table ``compliance_auditlog``      (DLP event audit writes)
   - DjangoTelegramLink      → table ``users_telegramlink``        (messaging — resolve user)
   - DjangoSlackLink         → table ``users_slacklink``           (messaging — resolve user)
   - DjangoOrgSlackApp       → table ``workspace_orgslackapp``     (messaging — org bot token)
   - DjangoSkillCatalogEntry → table ``storage_skillcatalogentry`` (toolkit — marketplace skills)
   - DjangoUserInstalledSkill → table ``storage_userinstalledskill`` (toolkit — user-installed skills)
   - DjangoUserSkill         → table ``storage_userskill``           (toolkit — user-authored skills)
   - DjangoProjectSkill      → table ``spaces_projectskill``         (toolkit — project-level skills)
   - DjangoProjectMCPConfig  → table ``spaces_projectmcpconfig``     (toolkit — project MCP servers)
   - DjangoProjectAddon      → table ``spaces_projectaddon``         (toolkit — project-scoped addons)
   - DjangoMarketplaceAddon  → table ``storage_marketplaceaddon``    (toolkit — marketplace addon rates)
   - DjangoUserMarketplaceAddons → table ``storage_usermarketplaceaddons`` (toolkit — user addon auth)
   - DjangoOrgAgentPolicy    → table ``workspace_orgagentpolicy``    (toolkit — blocked tools + HITL)
"""

import uuid

from django.db import models

# ═══════════════════════════════════════════════════════════════════════════════
# A. Sandbox-Owned Models (managed = True)
# ═══════════════════════════════════════════════════════════════════════════════


class SandboxRun(models.Model):
    """Agent run record — owned by the sandbox."""

    id = models.CharField(max_length=36, primary_key=True)
    task = models.TextField()
    status = models.CharField(max_length=20, default="running")
    model = models.TextField()
    mcp_servers = models.JSONField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True, db_column="metadata")
    error = models.TextField(null=True, blank=True)
    user_id = models.CharField(max_length=255, null=True, blank=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)
    parent_run = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="parent_run_id",
        related_name="branches",
    )
    conversation_id = models.CharField(max_length=36, null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_runs"

    def __str__(self) -> str:
        return f"SandboxRun {self.id} ({self.status})"


class SandboxEvent(models.Model):
    """Persisted SSE event — owned by the sandbox."""

    id = models.BigAutoField(primary_key=True)
    run = models.ForeignKey(
        SandboxRun,
        on_delete=models.CASCADE,
        related_name="events",
        db_column="run_id",
    )
    sequence = models.IntegerField()
    event_type = models.CharField(max_length=50)
    data = models.JSONField()
    # Pre-serialized JSON string for zero-copy SSE output.
    # When set, streaming sends data_raw directly without json.dumps().
    # Falls back to json.dumps(data) if data_raw is empty.
    data_raw = models.TextField(default="", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "agent_events"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"],
                name="uq_agent_events_run_seq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["run", "created_at", "sequence"],
                name="idx_evt_run_created_seq",
            ),
        ]
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"SandboxEvent run={self.run_id} seq={self.sequence}"

    @property
    def data_for_sse(self) -> str:
        """Return pre-serialized JSON for SSE output, falling back to json.dumps."""
        if self.data_raw:
            return self.data_raw
        import json

        return json.dumps(self.data)


class SandboxMessage(models.Model):
    """Materialized message — built incrementally by RunContext.emit(), ready to render.

    Unlike SandboxEvent (raw streaming deltas), each SandboxMessage row is a
    complete, render-ready message: full assistant text, tool call with result
    merged, etc.  Frontend loads these directly for history — no client-side
    event replay needed.
    """

    id = models.BigAutoField(primary_key=True)
    run = models.ForeignKey(
        SandboxRun,
        on_delete=models.CASCADE,
        related_name="messages",
        db_column="run_id",
    )
    sequence = models.IntegerField()
    msg_type = models.CharField(max_length=30)
    content = models.JSONField()
    is_complete = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_messages"
        constraints = [
            models.UniqueConstraint(
                fields=["run", "sequence"],
                name="uq_agent_msgs_run_seq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["run", "sequence"],
                name="idx_msg_run_seq",
            ),
        ]
        ordering = ["sequence"]

    def __str__(self) -> str:
        return f"SandboxMessage run={self.run_id} seq={self.sequence} type={self.msg_type}"


class HitlRequest(models.Model):
    """Human-in-the-loop request — owned by the sandbox."""

    id = models.CharField(max_length=36, primary_key=True)
    run = models.ForeignKey(
        SandboxRun,
        on_delete=models.CASCADE,
        related_name="hitl_requests",
        db_column="run_id",
    )
    prompt = models.TextField()
    choices = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, default="pending")
    response = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hitl_requests"

    def __str__(self) -> str:
        return f"HitlRequest {self.id} ({self.status})"


class VitalInformation(models.Model):
    """Knowledge extracted by the Knowledge Manager agent — sandbox-owned.

    Stores vital information that survives context compression: requirements,
    research findings, technical decisions, issues, resources, and visual findings.
    Scoped per conversation_id.  Supports soft-dedup via ``supersedes_id`` chain
    and ``is_active`` flag.
    """

    class Category(models.TextChoices):
        REQUIREMENT = "requirement", "Requirement"
        RESEARCH = "research", "Research Finding"
        DECISION = "decision", "Technical Decision"
        ISSUE = "issue", "Issue & Resolution"
        RESOURCE = "resource", "Resource"
        VISUAL = "visual", "Visual Finding"

    class Scope(models.TextChoices):
        CONVERSATION = "conversation", "Conversation"
        PROJECT = "project", "Project"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation_id = models.CharField(max_length=36, db_index=True)
    category = models.CharField(max_length=20, choices=Category.choices)
    title = models.CharField(max_length=512)
    content = models.TextField()
    rationale = models.TextField(blank=True, default="")
    source_run_id = models.CharField(max_length=36, blank=True, default="")
    supersedes_id = models.UUIDField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    # knowledge manager file-backing (Phase A of knowledge manager upgrade).
    # ``file_path`` is the canonical source of truth; this row is a derived index.
    file_path = models.CharField(max_length=512, blank=True, default="")
    content_hash = models.CharField(max_length=64, blank=True, default="")
    scope = models.CharField(
        max_length=20,
        choices=Scope.choices,
        default=Scope.CONVERSATION,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "agent_vital_information"
        indexes = [
            models.Index(
                fields=["conversation_id", "is_active", "category"],
                name="idx_vital_info_conv_active_cat",
            ),
            models.Index(
                fields=["conversation_id", "file_path"],
                name="idx_vital_info_conv_filepath",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"VitalInfo [{self.category}] {self.title[:60]}"


# ═══════════════════════════════════════════════════════════════════════════════
# B. Backend-Owned Models (managed = False)
# ═══════════════════════════════════════════════════════════════════════════════


class DjangoAgentRun(models.Model):
    """Mirror of the backend's ``storage.AgentRun`` — sandbox writes status/usage."""

    id = models.UUIDField(primary_key=True)
    run_id = models.CharField(max_length=36, db_index=True)
    conversation_id = models.UUIDField(null=True, blank=True)
    user_id = models.IntegerField(null=True, blank=True)
    task = models.TextField(blank=True)
    status = models.CharField(max_length=20)
    model = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    sandbox_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "storage_agentrun"

    def __str__(self) -> str:
        return f"DjangoAgentRun {self.id} ({self.status})"


class DjangoConversation(models.Model):
    """Mirror of the backend's ``storage.Conversation`` — sandbox updates current_task_id."""

    id = models.CharField(max_length=36, primary_key=True)
    user_id = models.BigIntegerField()
    project_id = models.UUIDField(null=True, blank=True)
    title = models.CharField(max_length=512, null=True, blank=True)
    icon = models.CharField(max_length=64, blank=True, default="")
    current_task_id = models.UUIDField(null=True, blank=True)
    requires_user_input = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    metadata = models.JSONField(null=True, blank=True, default=dict)
    date_created = models.DateTimeField()
    date_updated = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "storage_conversation"

    def __str__(self) -> str:
        return f"DjangoConversation {self.id}"


class DjangoOrganization(models.Model):
    """Mirror of backend's ``workspace.Organization`` — read-only for DLP lookup."""

    id = models.UUIDField(primary_key=True)
    name = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "workspace_organization"

    def __str__(self) -> str:
        return self.name


class DjangoProject(models.Model):
    """Mirror of backend's ``spaces.Project`` — read-only for DLP + toolkit lookup."""

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField(null=True, blank=True)
    user_id = models.BigIntegerField(null=True, blank=True)
    isolated_toolkit = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = "spaces_project"

    def __str__(self) -> str:
        return f"DjangoProject {self.id}"


class DjangoDLPPolicy(models.Model):
    """Mirror of backend's ``workspace.DLPPolicy`` — sandbox reads scan patterns at run start."""

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField(db_index=True, unique=True)
    scan_patterns = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "workspace_dlppolicy"

    def __str__(self) -> str:
        return f"DjangoDLPPolicy org={self.organization_id}"


class DjangoAuditLog(models.Model):
    """Mirror of backend's ``compliance.AuditLog`` — sandbox writes DLP events here."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    timestamp = models.DateTimeField(auto_now_add=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=50)
    resource_type = models.CharField(max_length=100)
    resource_id = models.CharField(max_length=255, blank=True, default="")
    request_id = models.CharField(max_length=64, blank=True, default="")
    changes = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        managed = False
        db_table = "compliance_auditlog"

    def __str__(self) -> str:
        return f"[{self.timestamp}] {self.action} {self.resource_type}/{self.resource_id}"


class DjangoConversationPlan(models.Model):
    """Mirror of the backend's ``storage.ConversationPlan`` — sandbox syncs plan state."""

    id = models.UUIDField(primary_key=True)
    conversation_id = models.UUIDField(null=True, blank=True)
    goal = models.TextField()
    phases = models.JSONField(default=list)
    current_phase_id = models.CharField(max_length=100)
    sandbox_id = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "storage_conversationplan"

    def __str__(self) -> str:
        goal_preview = self.goal[:60] if self.goal else ""
        return f"DjangoConversationPlan {self.id}: {goal_preview}"


class DjangoStoredFile(models.Model):
    """Backend's StoredFile — sandbox writes file records directly to S3 + DB."""

    id = models.UUIDField(primary_key=True)
    owner_id = models.BigIntegerField(null=True, blank=True)
    file = models.CharField(max_length=500)  # S3 path relative to MEDIA_ROOT
    name = models.CharField(max_length=255)  # Original display name
    size = models.BigIntegerField()
    mime_type = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "storage_storedfile"

    def __str__(self) -> str:
        return f"{self.name} ({self.size} bytes)"


class DjangoConversationFile(models.Model):
    """Backend's ConversationFile — links a StoredFile to a Conversation."""

    id = models.BigAutoField(primary_key=True)
    conversation_id = models.CharField(max_length=36)
    stored_file_id = models.UUIDField()

    class Meta:
        managed = False
        db_table = "storage_conversationfile"

    def __str__(self) -> str:
        return f"ConversationFile conv={self.conversation_id} file={self.stored_file_id}"


class DjangoUser(models.Model):
    """Backend's User model — read-only mirror for auth verification.

    The backend's ``users.User`` extends ``AbstractUser`` with BigAutoField PK
    (via ``DEFAULT_AUTO_FIELD``), email-based login, and no username field.
    """

    id = models.BigAutoField(primary_key=True)
    email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "users_user"

    def __str__(self) -> str:
        return self.email or f"User {self.id}"


class DjangoAuthToken(models.Model):
    """Backend's DRF auth token — read-only mirror for token verification.

    Maps to ``rest_framework.authtoken.Token`` (installed via ``dj_rest_auth``).
    The token ``key`` is a 40-char hex string sent in the ``Authorization: Bearer <key>``
    header by authenticated frontend clients.
    """

    key = models.CharField(max_length=40, primary_key=True)
    user = models.OneToOneField(
        DjangoUser,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_column="user_id",
    )
    created = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "authtoken_token"

    def __str__(self) -> str:
        return f"Token {self.key[:8]}... (user={self.user_id})"


class DjangoE2bSandbox(models.Model):
    """Mirror of the backend's ``agents.E2bSandbox`` — for extending idle pause timer."""

    sandbox_id = models.TextField(blank=True)
    sandbox_state = models.CharField(max_length=20)
    delayed_termination_at = models.DateTimeField(null=True, blank=True)
    date_updated = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "agents_e2bsandbox"

    def __str__(self) -> str:
        return f"DjangoE2bSandbox {self.pk} ({self.sandbox_id})"


# ─── Celery Beat mirrors (for creating schedules from sandbox) ────────────────


class DjangoCeleryCrontabSchedule(models.Model):
    """Mirror of ``django_celery_beat.CrontabSchedule``."""

    minute = models.CharField(max_length=240, default="*")
    hour = models.CharField(max_length=96, default="*")
    day_of_week = models.CharField(max_length=64, default="*")
    day_of_month = models.CharField(max_length=124, default="*")
    month_of_year = models.CharField(max_length=64, default="*")
    timezone = models.CharField(max_length=63, default="UTC")

    class Meta:
        managed = False
        db_table = "django_celery_beat_crontabschedule"

    def __str__(self) -> str:
        return f"{self.minute} {self.hour} {self.day_of_month} {self.month_of_year} {self.day_of_week}"


class DjangoCeleryIntervalSchedule(models.Model):
    """Mirror of ``django_celery_beat.IntervalSchedule``."""

    every = models.IntegerField()
    period = models.CharField(max_length=24)

    class Meta:
        managed = False
        db_table = "django_celery_beat_intervalschedule"

    def __str__(self) -> str:
        return f"every {self.every} {self.period}"


class DjangoCeleryPeriodicTask(models.Model):
    """Mirror of ``django_celery_beat.PeriodicTask``."""

    name = models.CharField(max_length=200, unique=True)
    task = models.CharField(max_length=200)
    args = models.TextField(default="[]")
    kwargs = models.TextField(default="{}")
    crontab = models.ForeignKey(DjangoCeleryCrontabSchedule, on_delete=models.CASCADE, null=True, blank=True)
    interval = models.ForeignKey(DjangoCeleryIntervalSchedule, on_delete=models.CASCADE, null=True, blank=True)
    one_off = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)
    expires = models.DateTimeField(null=True, blank=True)
    date_changed = models.DateTimeField(auto_now=True)

    class Meta:
        managed = False
        db_table = "django_celery_beat_periodictask"

    def __str__(self) -> str:
        return self.name


# ─── Credit billing mirrors (for per-tool-call billing from sandbox) ─────────


class DjangoCreditWallet(models.Model):
    """Mirror of backend's ``billing.CreditWallet`` — read wallet state for deductions."""

    id = models.UUIDField(primary_key=True)
    user_id = models.BigIntegerField()
    monthly_credits_remaining = models.IntegerField(default=0)
    addon_credits = models.IntegerField(default=0)
    free_credits = models.IntegerField(default=0)
    daily_credits_remaining = models.IntegerField(default=0)
    version = models.IntegerField(default=0)

    class Meta:
        managed = False
        db_table = "billing_creditwallet"

    def __str__(self) -> str:
        return f"DjangoCreditWallet user={self.user_id} v={self.version}"


class DjangoCreditHold(models.Model):
    """Mirror of backend's ``billing.CreditHold`` — consume credits during tool calls."""

    id = models.UUIDField(primary_key=True)
    wallet_id = models.UUIDField()
    run_id = models.UUIDField()
    amount_reserved = models.IntegerField()
    amount_consumed = models.IntegerField(default=0)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    settled_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        managed = False
        db_table = "billing_credithold"

    def __str__(self) -> str:
        return f"DjangoCreditHold {self.id} ({self.status})"


class DjangoCreditTransaction(models.Model):
    """Mirror of backend's ``billing.CreditTransaction`` — write ledger entries."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    wallet_id = models.UUIDField()
    hold_id = models.UUIDField(null=True, blank=True)
    amount = models.IntegerField()
    balance_after = models.IntegerField()
    category = models.CharField(max_length=20)
    source_type = models.CharField(max_length=100, blank=True)
    description = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = False
        db_table = "billing_credittransaction"

    def __str__(self) -> str:
        sign = "+" if self.amount >= 0 else ""
        return f"{sign}{self.amount} ({self.category})"


# ─── Messaging integration mirrors (Telegram/Slack webhooks → sandbox) ───────


class DjangoTelegramLink(models.Model):
    """Mirror of backend's ``users.TelegramLink`` — resolve chat_id → user on webhook."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(unique=True)
    telegram_chat_id = models.BigIntegerField(unique=True)
    telegram_username = models.CharField(max_length=255, blank=True, null=True)
    linked_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "users_telegramlink"

    def __str__(self) -> str:
        return f"DjangoTelegramLink user={self.user_id} chat={self.telegram_chat_id}"


class DjangoSlackLink(models.Model):
    """Mirror of backend's ``users.SlackLink`` — resolve Slack user_id → user on webhook."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.BigIntegerField(unique=True)
    slack_user_id = models.CharField(max_length=255, unique=True)
    slack_team_id = models.CharField(max_length=255, blank=True, default="")
    slack_username = models.CharField(max_length=255, blank=True, default="")
    slack_workspace_name = models.CharField(max_length=255, blank=True, default="")
    linked_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "users_slacklink"

    def __str__(self) -> str:
        return f"DjangoSlackLink user={self.user_id} slack={self.slack_user_id}"


class DjangoOrgSlackApp(models.Model):
    """Mirror of backend's ``workspace.OrgSlackApp`` — per-org bot token for Slack DMs.

    ``bot_token`` is encrypted at rest by the backend via ``EncryptedCharField``.
    The sandbox reads it raw; the transparent decrypt happens via the shared
    Fernet key inherited through env (``FIELD_ENCRYPTION_KEY``).  For webhook
    responses we tolerate missing tokens and fall back to the global
    ``SLACK_BOT_TOKEN`` env var.
    """

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField(unique=True)
    bot_token = models.TextField()  # EncryptedCharField on backend; raw bytes here
    app_id = models.CharField(max_length=255, blank=True, default="")
    team_id = models.CharField(max_length=255, blank=True, default="")
    channel_id = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "workspace_orgslackapp"

    def __str__(self) -> str:
        return f"DjangoOrgSlackApp org={self.organization_id} team={self.team_id}"


class DjangoCreditRate(models.Model):
    """Mirror of backend's ``billing.CreditRate`` — read-only rate card lookup."""

    id = models.UUIDField(primary_key=True)
    category = models.CharField(max_length=20)
    key = models.CharField(max_length=100)
    credits_per_unit = models.DecimalField(max_digits=10, decimal_places=4)
    unit = models.CharField(max_length=50)
    markup = models.DecimalField(max_digits=4, decimal_places=2)
    active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = "billing_creditrate"

    def __str__(self) -> str:
        return f"DjangoCreditRate {self.category}:{self.key}"


class DjangoScheduledTask(models.Model):
    """Mirror of backend's ``agents.ScheduledTask`` — sandbox creates tasks directly."""

    id = models.UUIDField(primary_key=True)
    prompt = models.TextField()
    name = models.CharField(max_length=255, blank=True, default="")
    user_id = models.BigIntegerField()
    schedule_type = models.CharField(max_length=10, default="cron")
    crontab = models.CharField(max_length=100, blank=True, default="")
    interval_seconds = models.PositiveIntegerField(null=True, blank=True)
    is_recurring = models.BooleanField(default=True)
    is_paused = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    playbook = models.TextField(blank=True, default="")
    celery_task = models.OneToOneField(DjangoCeleryPeriodicTask, on_delete=models.SET_NULL, null=True, blank=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    next_run_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "agents_scheduledtask"

    def __str__(self) -> str:
        label = self.name or self.prompt[:50]
        return f"DjangoScheduledTask {self.id}: {label}"


# ─── Toolkit resolution mirrors (skills, addons, project MCP configs) ─────────


class DjangoSkillCatalogEntry(models.Model):
    """Mirror of backend's ``storage.SkillCatalogEntry`` — marketplace skill content."""

    id = models.UUIDField(primary_key=True)
    slug = models.SlugField(max_length=128, unique=True)
    source_repo = models.CharField(max_length=256, blank=True)
    source_path = models.CharField(max_length=256, blank=True)
    skill_md_content = models.TextField()
    skill_files = models.JSONField(default=dict, blank=True)

    class Meta:
        managed = False
        db_table = "storage_skillcatalogentry"

    def __str__(self) -> str:
        return f"DjangoSkillCatalogEntry {self.slug}"


class DjangoUserInstalledSkill(models.Model):
    """Mirror of backend's ``storage.UserInstalledSkill`` — which marketplace skills a user installed."""

    id = models.UUIDField(primary_key=True)
    user_id = models.BigIntegerField()
    skill = models.ForeignKey(
        DjangoSkillCatalogEntry,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_column="skill_id",
    )
    installed_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "storage_userinstalledskill"

    def __str__(self) -> str:
        return f"DjangoUserInstalledSkill user={self.user_id} skill={self.skill_id}"


class DjangoUserSkill(models.Model):
    """Mirror of backend's ``storage.UserSkill`` — user-authored skills."""

    id = models.UUIDField(primary_key=True)
    owner_id = models.BigIntegerField()
    slug = models.SlugField(max_length=128)
    skill_md_content = models.TextField()
    skill_files = models.JSONField(default=dict, blank=True)
    source_url = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        managed = False
        db_table = "storage_userskill"

    def __str__(self) -> str:
        return f"DjangoUserSkill owner={self.owner_id} slug={self.slug}"


class DjangoProjectSkill(models.Model):
    """Mirror of backend's ``spaces.ProjectSkill`` — project-scoped marketplace skills."""

    id = models.UUIDField(primary_key=True)
    project_id = models.UUIDField()
    skill = models.ForeignKey(
        DjangoSkillCatalogEntry,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_column="skill_id",
    )

    class Meta:
        managed = False
        db_table = "spaces_projectskill"

    def __str__(self) -> str:
        return f"DjangoProjectSkill project={self.project_id} skill={self.skill_id}"


class DjangoProjectMCPConfig(models.Model):
    """Mirror of backend's ``spaces.ProjectMCPConfig`` — project-scoped MCP server configs."""

    id = models.UUIDField(primary_key=True)
    project_id = models.UUIDField()
    server_name = models.CharField(max_length=100)
    server_type = models.CharField(max_length=20, default="stdio")
    command = models.TextField(blank=True, null=True)
    arguments = models.TextField(blank=True, default="")
    env = models.TextField(blank=True, default="")
    url = models.CharField(max_length=200, blank=True, null=True)
    timeout = models.IntegerField(blank=True, null=True)
    sse_read_timeout = models.IntegerField(blank=True, null=True)
    client_session_timeout_seconds = models.FloatField(blank=True, null=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "spaces_projectmcpconfig"

    def __str__(self) -> str:
        return f"DjangoProjectMCPConfig project={self.project_id} {self.server_name}"


class DjangoMarketplaceAddon(models.Model):
    """Mirror of backend's ``storage.MarketplaceAddon`` — marketplace addon metadata + credit tier."""

    id = models.UUIDField(primary_key=True)
    name = models.TextField()
    credit_tier = models.CharField(max_length=20, default="standard")

    class Meta:
        managed = False
        db_table = "storage_marketplaceaddon"

    def __str__(self) -> str:
        return f"DjangoMarketplaceAddon {self.name} ({self.credit_tier})"


class DjangoUserMarketplaceAddons(models.Model):
    """Mirror of backend's ``storage.UserMarketplaceAddons`` — user auth registration for an addon."""

    id = models.UUIDField(primary_key=True)
    owner_id = models.BigIntegerField(null=True, blank=True)
    enabled_addon = models.ForeignKey(
        DjangoMarketplaceAddon,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_column="enabled_addon_id",
    )

    class Meta:
        managed = False
        db_table = "storage_usermarketplaceaddons"

    def __str__(self) -> str:
        return f"DjangoUserMarketplaceAddons {self.id} owner={self.owner_id}"


class DjangoProjectAddon(models.Model):
    """Mirror of backend's ``spaces.ProjectAddon`` — project-scoped addon references."""

    id = models.UUIDField(primary_key=True)
    project_id = models.UUIDField()
    addon = models.ForeignKey(
        DjangoUserMarketplaceAddons,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_column="addon_id",
    )

    class Meta:
        managed = False
        db_table = "spaces_projectaddon"

    def __str__(self) -> str:
        return f"DjangoProjectAddon project={self.project_id} addon={self.addon_id}"


class DjangoOrgAgentPolicy(models.Model):
    """Mirror of backend's ``workspace.OrgAgentPolicy`` — blocked tools + HITL tools per org."""

    id = models.UUIDField(primary_key=True)
    organization_id = models.UUIDField(unique=True)
    blocked_tools = models.JSONField(default=list, blank=True)
    blocked_tool_groups = models.JSONField(default=list, blank=True)
    require_hitl_for = models.JSONField(default=list, blank=True)

    class Meta:
        managed = False
        db_table = "workspace_orgagentpolicy"

    def __str__(self) -> str:
        return f"DjangoOrgAgentPolicy org={self.organization_id}"
