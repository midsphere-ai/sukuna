"""Django ORM models for conversations, files, marketplace addons, agent runs, and system memory."""

import os
import uuid
from datetime import timedelta
from typing import Optional

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Prefetch, QuerySet
from django.utils import timezone

from apps.spaces.models import Project
from apps.users.models import ShortUUIDMixin, User


def upload_to(instance, filename):
    """Generate a unique upload path for a stored file.

    Args:
        instance: The StoredFile model instance.
        filename: The original filename.

    Returns:
        str: A path of the form 'uploads/<owner_id>/<uuid>.<ext>'.
    """
    ext = filename.split(".")[-1]
    new_filename = f"{uuid.uuid4()}.{ext}"
    return os.path.join("uploads", str(instance.owner.id), new_filename)


class MarketplaceAddonManager(models.Manager):
    """Custom manager for MarketplaceAddon CRUD operations."""

    def get_all(self) -> QuerySet["MarketplaceAddon"]:
        """Get all marketplace addons."""
        return self.all()

    def get_by_id(self, addon_id) -> Optional["MarketplaceAddon"]:
        """Get a single addon by ID."""
        return self.filter(id=addon_id).first()

    def get_by_id_with_user_prefetch(
        self, addon_id, user_id: Optional[int] = None
    ) -> Optional["MarketplaceAddon"]:
        """Get addon by ID, optionally prefetching user-specific registration."""
        if user_id:
            return (
                self.prefetch_related(
                    Prefetch(
                        "enabled_addons",
                        queryset=UserMarketplaceAddons.objects.filter(
                            owner__id=user_id
                        ),
                        to_attr="user_specific_addons",
                    )
                )
                .filter(id=addon_id)
                .first()
            )
        return self.filter(id=addon_id).first()


class MarketplaceAddon(ShortUUIDMixin):
    """A third-party addon available in the marketplace, backed by Composio toolkits."""

    CREDIT_TIER_CHOICES = [
        ("basic", "Basic — 2 credits/call"),
        ("standard", "Standard — 5 credits/call"),
        ("premium", "Premium — 10 credits/call"),
    ]

    # Category-based tier classification.
    # Categories/tags containing these keywords map to their tier.
    # Checked in order: premium first, then basic. Anything unmatched → standard.
    PREMIUM_KEYWORDS = frozenset(
        {
            "cloud",
            "infrastructure",
            "finance",
            "payment",
            "banking",
            "ai",
            "machine-learning",
            "database",
            "analytics",
            "security",
            "blockchain",
            "crypto",
            "erp",
            "crm",
        }
    )
    BASIC_KEYWORDS = frozenset(
        {
            "productivity",
            "calendar",
            "email",
            "notes",
            "todo",
            "social",
            "messaging",
            "communication",
            "news",
            "rss",
            "weather",
            "utility",
            "utilities",
        }
    )

    name = models.TextField(null=False, blank=False)
    description = models.TextField()
    link = models.TextField()
    logo = models.TextField()
    enum = models.TextField()
    categories = models.JSONField(default=list, blank=True)
    tags = models.JSONField(default=list, blank=True)
    credit_tier = models.CharField(
        max_length=20,
        choices=CREDIT_TIER_CHOICES,
        default="standard",
        help_text="Billing tier for per-tool-call credit deduction",
    )

    objects = MarketplaceAddonManager()

    def classify_credit_tier(self) -> str:
        """Derive credit tier from categories and tags.

        Premium: cloud, infra, finance, AI, database, security, etc.
        Basic: productivity, calendar, email, social, messaging, etc.
        Standard: everything else (dev-tools, code, search, etc.)
        """
        keywords = {kw.lower() for kw in (self.categories or []) + (self.tags or [])}
        if keywords & self.PREMIUM_KEYWORDS:
            return "premium"
        if keywords & self.BASIC_KEYWORDS:
            return "basic"
        return "standard"


class UserMarketplaceAddonsManager(models.Manager):
    """Custom manager for UserMarketplaceAddons CRUD operations."""

    def for_user(self, user: User) -> QuerySet["UserMarketplaceAddons"]:
        """Get all user addons with related data."""
        return self.select_related("enabled_addon", "owner").filter(owner__id=user.id)

    def get_by_id(self, addon_id) -> Optional["UserMarketplaceAddons"]:
        """Get a single user addon by ID with related data."""
        return self.select_related("enabled_addon", "owner").filter(id=addon_id).first()

    def count_for_user(self, user: User) -> int:
        """Count addons registered by a user."""
        return self.filter(owner=user).count()

    def pending_authorizations(self, user_id: int) -> QuerySet["UserMarketplaceAddons"]:
        """Get addons with pending authorization for a user."""
        return self.filter(
            owner_id=user_id,
            auth_complete=False,
            config_id__isnull=False,
        ).select_related("enabled_addon")

    def create_registration(
        self, marketplace_addon: "MarketplaceAddon", owner: User
    ) -> "UserMarketplaceAddons":
        """Register a marketplace addon for a user."""
        return self.create(enabled_addon=marketplace_addon, owner=owner)


class UserMarketplaceAddons(ShortUUIDMixin):
    """A user's registration of a marketplace addon, tracking auth state and Composio config."""

    enabled_addon = models.ForeignKey(
        MarketplaceAddon,
        default=None,
        on_delete=models.CASCADE,
        related_name="enabled_addons",
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="addon_owner",
        null=True,
        blank=True,
    )
    auth_complete = models.BooleanField(default=False)
    auth_link = models.TextField(null=True, blank=True)
    config_id = models.TextField(null=True, blank=True)
    server_id = models.TextField(null=True, blank=True)
    auth_link_created_at = models.DateTimeField(null=True, blank=True)

    objects = UserMarketplaceAddonsManager()

    def check_auth_status(self):
        """Validate the addon's authentication status.

        Raises:
            ValueError: If authentication is incomplete or the auth link has expired.
        """
        if self.auth_complete:
            return

        if self.auth_link:
            expiry_ref = self.auth_link_created_at or self.date_created
            if expiry_ref < timezone.now() - timedelta(hours=6):
                self.auth_link = None
                self.auth_link_created_at = None
                self.save()
                raise ValueError(
                    "Authentication link has expired. Please regenerate it."
                )

        raise ValueError("Authentication is not complete for this addon.")


class StoredFileManager(models.Manager):
    """Custom manager for StoredFile CRUD operations."""

    def for_user(self, user: User) -> QuerySet["StoredFile"]:
        """Get all files belonging to a user, ordered by newest first."""
        return self.filter(owner=user).order_by("-uploaded_at")

    def create_file(
        self, owner: User, file, name: str, size: int, mime_type: str = ""
    ) -> "StoredFile":
        """Create a new stored file record."""
        return self.create(
            owner=owner, file=file, name=name, size=size, mime_type=mime_type
        )


class StoredFile(models.Model):
    """A user-uploaded file stored in object storage with metadata."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="stored_files",
        null=True,
        blank=True,
    )
    file = models.FileField(upload_to=upload_to, max_length=500)
    name = models.CharField(max_length=255)  # Original display name
    size = models.BigIntegerField()  # Size in bytes
    mime_type = models.CharField(max_length=100, blank=True)  # e.g., "image/png"
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = StoredFileManager()

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["owner"]),
            models.Index(fields=["owner", "uploaded_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.size} bytes)"


class ConversationManager(models.Manager):
    """Custom manager for Conversation CRUD operations."""

    def for_user(self, user: User) -> QuerySet["Conversation"]:
        """Get all conversations for a user, ordered by latest activity."""
        return (
            self.filter(user=user)
            .select_related("user", "current_task")
            .order_by("-date_updated")
        )

    def by_user_id(self, user_id: int) -> QuerySet["Conversation"]:
        """Get all conversations for a user ID, ordered by latest activity."""
        return (
            self.filter(user__id=user_id)
            .select_related("user", "current_task")
            .order_by("-date_updated")
        )

    def get_by_id(self, conversation_id) -> Optional["Conversation"]:
        """Get a single conversation by ID with user and current_task pre-fetched."""
        return (
            self.select_related("user", "current_task")
            .filter(id=conversation_id)
            .first()
        )

    def create_conversation(self, user: User) -> "Conversation":
        """Create a new conversation for a user."""
        return self.create(user=user)

    def delete_for_user(self, user: User) -> int:
        """Delete all conversations for a user. Returns count deleted."""
        deleted_count, _ = self.filter(user=user).delete()
        return deleted_count


class Conversation(ShortUUIDMixin):
    """A user conversation thread with derived status from its current agent run."""

    title = models.CharField(
        max_length=512, unique=False, default="New chat", null=True, blank=True
    )
    icon = models.CharField(max_length=64, blank=True, default="")
    user = models.ForeignKey(
        User,
        related_name="speaking_to",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    summary = models.TextField(null=True, blank=True)

    objects = ConversationManager()
    project = models.ForeignKey(
        Project,
        related_name="conversations",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    current_task = models.ForeignKey(
        "storage.AgentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_conversation",
    )
    requires_user_input = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    metadata = models.JSONField(null=True, default=dict)

    def __str__(self):
        return f"{self.user}:{self.title}"

    # -- Derived properties (source of truth: current_task / AgentRun) --

    @property
    def on_going(self) -> bool:
        return self.get_is_ongoing()

    @property
    def has_error(self) -> bool:
        return self.get_has_error()

    @property
    def error(self) -> str:
        return self.get_error_message()

    @property
    def cancellation_requested(self) -> bool:
        return self.get_is_cancellation_requested()

    def get_is_ongoing(self) -> bool:
        """Derive ongoing status from current_task."""
        if self.current_task_id is None:
            return False
        try:
            return self.current_task.status in (
                "pending",
                "queued",
                "provisioning",
                "running",
            )
        except Exception:
            return False

    def get_has_error(self) -> bool:
        """Derive error status from current_task."""
        if self.current_task_id is None:
            return False
        try:
            return self.current_task.status == "failed"
        except Exception:
            return False

    def get_error_message(self) -> str:
        """Get error message from current_task."""
        if self.current_task_id is None:
            return ""
        try:
            return self.current_task.error or ""
        except Exception:
            return ""

    def get_is_cancellation_requested(self) -> bool:
        """Derive cancellation status from current_task."""
        if self.current_task_id is None:
            return False
        try:
            return self.current_task.status == "cancelled"
        except Exception:
            return False

    class Meta:
        verbose_name = "Conversation"

        verbose_name_plural = "Conversations"
        indexes = [
            models.Index(fields=["user"]),  # For user filtering
            models.Index(fields=["title"]),  # For title searches
            models.Index(fields=["user", "title"]),
            GinIndex(
                SearchVector("summary", config="pg_catalog.english"),
                name="summary_fts_idx",
            ),
        ]


class ParticipantRole(models.TextChoices):
    """Role a user holds within a conversation."""

    CREATOR = "creator", "Creator"
    COLLABORATOR = "collaborator", "Collaborator"
    VIEWER = "viewer", "Viewer"


class ConversationParticipant(models.Model):
    """Tracks users participating in a conversation with role-based permissions."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="participants",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="conversation_participations",
    )
    role = models.CharField(
        max_length=20,
        choices=ParticipantRole.choices,
        default=ParticipantRole.VIEWER,
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("conversation", "user")]
        indexes = [
            models.Index(fields=["user", "role"]),
        ]

    def __str__(self):
        return f"{self.user} in {self.conversation_id} ({self.role})"


# ── Conversation permission utilities ──────────────────────────────


def _get_participant_role(conversation, user) -> str | None:
    """Return the participant role for a user in a conversation, or None."""
    try:
        p = ConversationParticipant.objects.get(conversation=conversation, user=user)
        return p.role
    except ConversationParticipant.DoesNotExist:
        return None


def _get_project_share_role(conversation, user) -> str | None:
    """Derive a participant role from a ProjectShare, if any.

    Mapping: view -> viewer, collaborate -> collaborator, admin -> collaborator.
    """
    if not conversation.project_id:
        return None

    from apps.spaces.models import ProjectShare

    share = ProjectShare.objects.filter(
        project_id=conversation.project_id,
        user=user,
    ).first()
    if share is None:
        # Check org-wide share

        if conversation.project.organization_id:
            share = ProjectShare.objects.filter(
                project_id=conversation.project_id,
                organization_id=conversation.project.organization_id,
            ).first()
    if share is None:
        return None

    mapping = {
        "view": ParticipantRole.VIEWER,
        "collaborate": ParticipantRole.COLLABORATOR,
        "admin": ParticipantRole.COLLABORATOR,
    }
    return mapping.get(share.permission_level)


def conversation_can_view(conversation, user) -> bool:
    """Check if user can view a conversation."""
    if conversation.user_id == user.id:
        return True
    role = _get_participant_role(conversation, user)
    if role is not None:
        return True
    # Derive from project share
    return _get_project_share_role(conversation, user) is not None


def conversation_can_inject(conversation, user) -> bool:
    """Check if user can inject messages into a conversation."""
    if conversation.user_id == user.id:
        return True
    role = _get_participant_role(conversation, user)
    if role in (ParticipantRole.CREATOR, ParticipantRole.COLLABORATOR):
        return True
    share_role = _get_project_share_role(conversation, user)
    return share_role in (ParticipantRole.CREATOR, ParticipantRole.COLLABORATOR)


def conversation_can_cancel(conversation, user) -> bool:
    """Check if user can cancel an active agent run in a conversation."""
    return conversation_can_inject(conversation, user)


class AgentRun(models.Model):
    """An individual agent execution run within a conversation, with state machine transitions."""

    class Status(models.TextChoices):
        """Enumeration of possible agent run statuses."""

        QUEUED = "queued", "Queued"
        PROVISIONING = "provisioning", "Provisioning"
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    # Valid state transitions: source -> set of allowed targets
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "queued": {"provisioning", "failed", "cancelled"},
        "provisioning": {"running", "failed", "cancelled"},
        "running": {"completed", "failed", "cancelled"},
        "pending": {
            "queued",
            "provisioning",
            "running",
            "completed",
            "failed",
            "cancelled",
        },  # legacy compat
    }

    TERMINAL_STATUSES: set[str] = {"completed", "failed", "cancelled"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_id = models.CharField(
        max_length=36,
        blank=True,
        db_index=True,
        help_text="Run ID from agent_server (set after POST /runs)",
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="runs"
    )
    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="agent_runs"
    )
    task = models.TextField(help_text="The prompt/task sent to agent")
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    model = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    sandbox_id = models.CharField(max_length=100, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="User feedback rating (1-5) for this run",
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["conversation"]),
            models.Index(fields=["user"]),
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["run_id"]),
        ]

    def __str__(self):
        return f"AgentRun: {self.id} ({self.status})"

    def transition_to(self, new_status: str, error: str = "") -> None:
        """Transition to a new status with validation.

        Enforces the state machine:
            queued       -> provisioning, failed, cancelled
            provisioning -> running, failed, cancelled
            running      -> completed, failed, cancelled
            pending      -> any (legacy compat)
            completed/failed/cancelled -> terminal (no transitions)

        Raises ValueError for invalid transitions.
        """
        current = self.status

        if current in self.TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot transition from terminal status '{current}' to '{new_status}'"
            )

        allowed = self.VALID_TRANSITIONS.get(current)
        if allowed is not None and new_status not in allowed:
            raise ValueError(f"Invalid transition from '{current}' to '{new_status}'")

        self.status = new_status

        if error:
            self.error = error

        # Auto-set timestamps
        if new_status == self.Status.RUNNING and self.started_at is None:
            self.started_at = timezone.now()
        if new_status in self.TERMINAL_STATUSES:
            self.finished_at = timezone.now()

        self.save(
            update_fields=["status", "error", "started_at", "finished_at", "updated_at"]
        )

        # Schedule sandbox pause 60s after run reaches terminal state
        if new_status in self.TERMINAL_STATUSES and self.conversation_id:
            self._schedule_sandbox_pause_after_completion()

    def mark_running(self):
        """Transition this run to the RUNNING state."""
        self.transition_to(self.Status.RUNNING)

    def mark_completed(self):
        """Transition this run to the COMPLETED state."""
        self.transition_to(self.Status.COMPLETED)

    def mark_failed(self, error: str = None):
        """Transition this run to the FAILED state.

        Args:
            error: Optional error message describing the failure.
        """
        self.transition_to(self.Status.FAILED, error=error or "")

    def mark_cancelled(self):
        """Transition this run to the CANCELLED state."""
        self.transition_to(self.Status.CANCELLED)

    def _schedule_sandbox_pause_after_completion(self):
        """Schedule the conversation's sandbox to pause 60s after run completion."""
        try:
            from apps.agents.models import E2bSandbox

            # Check project sandbox first, then conversation-level
            conv = self.conversation
            project = getattr(conv, "project", None)
            sandbox = None
            if project is not None:
                sandbox = E2bSandbox.objects.active_for_project(project).first()
            if sandbox is None:
                sandbox = E2bSandbox.objects.active_for_conversation(conv).first()
            if sandbox is not None:
                sandbox.schedule_idle_pause(minutes=1)
        except Exception:
            pass


class ConversationFile(models.Model):
    """Join table linking a conversation to its associated stored files."""

    conversation = models.ForeignKey(
        Conversation,
        default=None,
        on_delete=models.CASCADE,
        related_name="conversation_file",
    )
    stored_file = models.ForeignKey(
        StoredFile,
        default=None,
        on_delete=models.CASCADE,
        related_name="actually_conversation_file",
    )


class ConversationComposioAddon(models.Model):
    """Join table linking a conversation to Composio addons enabled for that conversation."""

    conversation = models.ForeignKey(
        Conversation,
        default=None,
        on_delete=models.CASCADE,
        related_name="conversation_extra_tools",
    )
    addon = models.ForeignKey(
        UserMarketplaceAddons,
        default=None,
        on_delete=models.CASCADE,
        related_name="addon",
    )


class SystemWideMemoryManager(models.Manager):
    """Custom manager for SystemWideMemory CRUD operations."""

    def for_user(self, user: User) -> Optional["SystemWideMemory"]:
        """Get system-wide memory for a user."""
        return self.filter(user=user).first()


class SystemWideMemory(models.Model):
    """Persistent system-wide memory summary for a user, used for cross-conversation context."""

    user = models.ForeignKey(
        User, related_name="mem_speaking_to", on_delete=models.CASCADE
    )
    memory_summary = models.TextField()
    date_created = models.DateTimeField(auto_now_add=True)

    objects = SystemWideMemoryManager()

    def __str__(self):
        return self.user.email

    class Meta:
        verbose_name = "System Memory"
        verbose_name_plural = "System Memory"


class ConversationPlan(models.Model):
    """Stores the current plan for a conversation, synced from the sandbox agent."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.OneToOneField(
        Conversation,
        on_delete=models.CASCADE,
        related_name="plan",
    )
    goal = models.TextField()
    phases = models.JSONField(default=list, help_text="Ordered list of phase dicts")
    current_phase_id = models.CharField(max_length=100)
    sandbox_id = models.CharField(max_length=100, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["conversation"]),
        ]

    def __str__(self):
        return f"Plan for {self.conversation_id}: {self.goal[:60]}"


class SkillCatalogEntryManager(models.Manager):
    """Custom manager for SkillCatalogEntry queries."""

    def get_all(self) -> QuerySet["SkillCatalogEntry"]:
        return self.all().order_by("-is_featured", "name")

    def get_by_slug(self, slug: str) -> Optional["SkillCatalogEntry"]:
        return self.filter(slug=slug).first()

    def by_category(self, category: str) -> QuerySet["SkillCatalogEntry"]:
        return self.filter(category=category).order_by("-is_featured", "name")

    def search(self, query: str) -> QuerySet["SkillCatalogEntry"]:
        """Search skills by name, description, or tags."""
        from django.db.models import Q

        q = query.lower()
        return self.filter(
            Q(name__icontains=q) | Q(description__icontains=q) | Q(tags__icontains=q)
        ).order_by("-is_featured", "name")


class SkillCatalogEntry(ShortUUIDMixin):
    """A skill available in the marketplace, crawled from GitHub or bundled."""

    class SourceType(models.TextChoices):
        OFFICIAL = "official", "Official"
        COMMUNITY = "community", "Community"

    slug = models.SlugField(unique=True, max_length=128)
    name = models.CharField(max_length=128)
    description = models.TextField()
    category = models.CharField(max_length=64, blank=True, db_index=True)

    # Source tracking
    source_type = models.CharField(
        max_length=16,
        choices=SourceType.choices,
        default=SourceType.COMMUNITY,
    )
    source_repo = models.CharField(max_length=256, blank=True)
    source_path = models.CharField(max_length=256, blank=True)
    author = models.CharField(max_length=128, blank=True)

    # Content
    skill_md_content = models.TextField()
    has_scripts = models.BooleanField(default=False)
    has_templates = models.BooleanField(default=False)
    skill_files = models.JSONField(
        default=dict,
        blank=True,
        help_text="Mapping of relative file paths to text content for supporting files.",
    )

    # Metadata
    tags = models.JSONField(default=list, blank=True)
    license = models.CharField(max_length=64, blank=True)
    version = models.CharField(max_length=32, blank=True)
    icon = models.CharField(max_length=8, blank=True)
    install_count = models.IntegerField(default=0)
    is_featured = models.BooleanField(default=False)

    objects = SkillCatalogEntryManager()

    class Meta:
        verbose_name = "Skill"
        verbose_name_plural = "Skills"
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["category"]),
            models.Index(fields=["source_type"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.slug})"


class UserInstalledSkillManager(models.Manager):
    """Custom manager for UserInstalledSkill queries."""

    def for_user(self, user: User) -> QuerySet["UserInstalledSkill"]:
        return self.select_related("skill").filter(user=user).order_by("-installed_at")

    def is_installed(self, user: User, skill: "SkillCatalogEntry") -> bool:
        return self.filter(user=user, skill=skill).exists()

    def install(self, user: User, skill: "SkillCatalogEntry") -> "UserInstalledSkill":
        obj, created = self.get_or_create(user=user, skill=skill)
        if created:
            SkillCatalogEntry.objects.filter(pk=skill.pk).update(
                install_count=models.F("install_count") + 1
            )
        return obj

    def uninstall(self, user: User, skill: "SkillCatalogEntry") -> bool:
        deleted, _ = self.filter(user=user, skill=skill).delete()
        if deleted:
            SkillCatalogEntry.objects.filter(pk=skill.pk).update(
                install_count=models.F("install_count") - 1
            )
        return deleted > 0


class UserInstalledSkill(models.Model):
    """A user's installation of a marketplace skill."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="installed_skills",
    )
    skill = models.ForeignKey(
        SkillCatalogEntry,
        on_delete=models.CASCADE,
        related_name="installations",
    )
    installed_at = models.DateTimeField(auto_now_add=True)

    objects = UserInstalledSkillManager()

    class Meta:
        unique_together = ("user", "skill")
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["user", "skill"]),
        ]

    def __str__(self):
        return f"{self.user} -> {self.skill.slug}"


class UserSkillManager(models.Manager):
    """Custom manager for UserSkill queries."""

    def for_owner(self, owner: User) -> QuerySet["UserSkill"]:
        return self.filter(owner=owner).order_by("-date_updated")

    def get_for_owner(self, owner: User, pk) -> Optional["UserSkill"]:
        return self.filter(owner=owner, pk=pk).first()

    def slug_exists(self, owner: User, slug: str) -> bool:
        return self.filter(owner=owner, slug=slug).exists()


class UserSkill(ShortUUIDMixin):
    """A skill authored or uploaded by a user (parallel to SkillCatalogEntry).

    Mirrors the installable shape used by sandbox provisioning:
    {slug, skill_md_content, skill_files} so these can be unioned with
    marketplace skills without special handling.
    """

    class Source(models.TextChoices):
        EDITOR = "editor", "Created in editor"
        UPLOAD_MD = "upload_md", "Uploaded SKILL.md"
        UPLOAD_ZIP = "upload_zip", "Uploaded bundle"
        GITHUB = "github", "Imported from GitHub"

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="authored_skills",
    )
    slug = models.SlugField(max_length=128)
    name = models.CharField(max_length=128)
    description = models.TextField()
    category = models.CharField(max_length=64, blank=True, db_index=True)

    skill_md_content = models.TextField()
    skill_files = models.JSONField(
        default=dict,
        blank=True,
        help_text="Mapping of relative file paths to text content for supporting files.",
    )

    icon = models.CharField(max_length=8, blank=True)
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.EDITOR,
    )
    source_url = models.URLField(blank=True)
    version = models.CharField(max_length=32, blank=True)

    objects = UserSkillManager()

    class Meta:
        verbose_name = "User Skill"
        verbose_name_plural = "User Skills"
        unique_together = ("owner", "slug")
        indexes = [
            models.Index(fields=["owner", "-date_updated"]),
        ]

    def __str__(self):
        return f"{self.owner} :: {self.slug}"


class AgentServerEvent(models.Model):
    """Read-only mirror of the agent server's agent_events table (unmanaged)."""

    id = models.BigAutoField(primary_key=True)
    run_id = models.CharField(max_length=36, db_index=True)
    sequence = models.IntegerField()
    event_type = models.CharField(max_length=50)
    data = models.JSONField()
    created_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "agent_events"
        ordering = ["sequence"]
