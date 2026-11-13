"""Django models for the spaces app, defining Project, ProjectFile, ProjectBudget, and ProjectShare."""

import uuid
from typing import Optional

from django.db import models
from django.db.models import QuerySet

from apps.users.models import ShortUUIDMixin, User


class SharePermission(models.TextChoices):
    VIEW = "view", "View"
    COLLABORATE = "collaborate", "Collaborate"
    ADMIN = "admin", "Admin"


class ProjectManager(models.Manager):
    """Custom manager for Project CRUD operations."""

    def for_user(self, user: User) -> QuerySet["Project"]:
        """Get all projects belonging to a user, ordered by newest first.

        Args:
            user: The user whose projects to retrieve.

        Returns:
            A QuerySet of Project objects ordered by date_created descending.
        """
        return self.filter(user=user).order_by("-date_created")

    def get_by_uuid(self, project_id) -> Optional["Project"]:
        """Get a single project by UUID with user pre-fetched.

        Args:
            project_id: The UUID of the project to retrieve.

        Returns:
            The matching Project instance, or None if not found.
        """
        return self.select_related("user").filter(id=project_id).first()

    def create_project(
        self, title: str, description: str, user: User, **kwargs
    ) -> "Project":
        """Create a new project for a user.

        Args:
            title: The display title for the project.
            description: A text description of the project.
            user: The owning user.
            **kwargs: Optional fields (icon, custom_instructions).

        Returns:
            The newly created Project instance.
        """
        return self.create(title=title, description=description, user=user, **kwargs)


class Project(ShortUUIDMixin):
    """Represents a project workspace owned by a user.

    A Project groups conversations under a shared context and optionally
    binds them to a single persistent E2B sandbox.
    """

    title = models.TextField(null=False, blank=False)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    custom_instructions = models.TextField(blank=True, default="")
    user = models.ForeignKey(User, related_name="projects", on_delete=models.CASCADE)
    organization = models.ForeignKey(
        "workspace.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="projects",
        help_text="If set, this project belongs to an organization rather than a personal workspace.",
    )
    sandbox = models.OneToOneField(
        "agents.E2bSandbox",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project",
    )
    isolated_toolkit = models.BooleanField(
        default=False,
        help_text="When True, only project-level toolkit is used; user globals excluded.",
    )

    objects = ProjectManager()

    def __str__(self):
        return f"{self.user}:{self.title}"

    def is_owned_by(self, user: User) -> bool:
        """Check if this project is owned by the given user.

        Args:
            user: The user to check ownership against.

        Returns:
            True if the user owns this project, False otherwise.
        """
        return self.user_id == user.id

    def update_details(self, title: str, description: str, **kwargs) -> None:
        """Update project title, description, and optional fields.

        Args:
            title: The new display title.
            description: The new description text.
            **kwargs: Optional fields to update (icon, custom_instructions).
        """
        self.title = title
        self.description = description
        for field in ("icon", "custom_instructions"):
            if field in kwargs:
                setattr(self, field, kwargs[field])
        self.save()


class ProjectBudget(models.Model):
    """Monthly credit budget for a project.

    ``current_month_usage`` is incremented as credits are consumed by runs in this
    project. A monthly Celery task resets the counter on the 1st of each month.
    """

    id = models.UUIDField(default=uuid.uuid4, primary_key=True, editable=False)
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="budget",
    )
    monthly_credit_limit = models.IntegerField(
        null=True,
        blank=True,
        help_text="Max credits this project can consume per month. Null = unlimited.",
    )
    alert_threshold_percent = models.IntegerField(
        default=80,
        help_text="Alert org admins when project usage crosses this % of its budget.",
    )
    current_month_usage = models.IntegerField(
        default=0,
        help_text="Credits consumed this calendar month. Reset on the 1st.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Project Budget"
        verbose_name_plural = "Project Budgets"

    def __str__(self):
        limit = self.monthly_credit_limit or "unlimited"
        return f"Budget for project {self.project_id}: {limit}/month (used {self.current_month_usage})"


class ProjectFile(ShortUUIDMixin):
    """A preloaded file attached to a project.

    These files are automatically available in the project sandbox
    when conversations start.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="files",
    )
    filename = models.CharField(max_length=512)
    file_path = models.TextField(
        help_text="Path within the sandbox where this file should be placed."
    )
    file = models.FileField(upload_to="project_files/%Y/%m/", blank=True)
    mime_type = models.CharField(max_length=128, blank=True, default="")
    size_bytes = models.BigIntegerField(default=0)

    class Meta:
        ordering = ["filename"]

    def __str__(self):
        return f"{self.project_id}:{self.filename}"


class ProjectTemplate(ShortUUIDMixin):
    """A reusable project template owned by an organization.

    Templates store configuration (custom_instructions, icon) and optional
    starter files that are copied into new projects created from the template.
    """

    organization = models.ForeignKey(
        "workspace.Organization",
        on_delete=models.CASCADE,
        related_name="project_templates",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    custom_instructions = models.TextField(blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_templates",
    )

    class Meta:
        ordering = ["-date_created"]

    def __str__(self):
        return f"{self.organization_id}:{self.name}"

    def total_file_size(self) -> int:
        """Return the sum of file content sizes in bytes."""
        return sum(
            len(f.file_content.encode("utf-8")) for f in self.template_files.all()
        )


class ProjectTemplateFile(ShortUUIDMixin):
    """A starter file attached to a project template.

    File content is stored as plaintext (not encrypted) since templates
    are org-shared resources, not user-specific PII.
    """

    template = models.ForeignKey(
        ProjectTemplate,
        on_delete=models.CASCADE,
        related_name="template_files",
    )
    file_name = models.CharField(max_length=512)
    file_content = models.TextField(default="")
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "file_name"]

    def __str__(self):
        return f"{self.template_id}:{self.file_name}"


class ProjectTemplateSkill(ShortUUIDMixin):
    """Snapshot of a skill in a project template."""

    template = models.ForeignKey(
        ProjectTemplate,
        on_delete=models.CASCADE,
        related_name="template_skills",
    )
    skill = models.ForeignKey(
        "storage.SkillCatalogEntry",
        on_delete=models.CASCADE,
        related_name="+",
    )
    config_overrides = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("template", "skill")

    def __str__(self):
        return f"{self.template_id} -> Skill {self.skill_id}"


class ProjectTemplateMCPConfig(ShortUUIDMixin):
    """Snapshot of an MCP server configuration in a project template."""

    template = models.ForeignKey(
        ProjectTemplate,
        on_delete=models.CASCADE,
        related_name="template_mcp_configs",
    )
    server_name = models.CharField(max_length=100)
    server_type = models.CharField(max_length=20, default="stdio")
    command = models.TextField(blank=True, null=True)
    arguments = models.TextField(blank=True, default="")
    env = models.TextField(blank=True, default="")
    url = models.URLField(blank=True, null=True)
    timeout = models.IntegerField(blank=True, null=True)
    description = models.TextField(blank=True, default="")

    class Meta:
        unique_together = ("template", "server_name")
        ordering = ["server_name"]

    def __str__(self):
        return f"{self.template_id}: {self.server_name}"


class ProjectShare(ShortUUIDMixin):
    """Records that a project is shared with a specific user or entire organization.

    - user-specific share: user is set, organization is null
    - org-wide share: organization is set, user is null
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="project_shares",
    )
    organization = models.ForeignKey(
        "workspace.Organization",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="project_shares",
    )
    permission_level = models.CharField(
        max_length=20,
        choices=SharePermission.choices,
        default=SharePermission.VIEW,
    )
    shared_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shares_given",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "user"],
                condition=models.Q(user__isnull=False),
                name="unique_project_user_share",
            ),
            models.UniqueConstraint(
                fields=["project", "organization"],
                condition=models.Q(organization__isnull=False),
                name="unique_project_org_share",
            ),
        ]

    def __str__(self):
        target = self.user or self.organization
        return f"{self.project_id} → {target} ({self.permission_level})"


# ── Project Toolkit models ──────────────────────────────────────────────────


class ProjectSkill(ShortUUIDMixin):
    """A skill attached to a project from the skill catalog.

    These skills are automatically provisioned for every conversation in the project.
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_skills",
    )
    skill = models.ForeignKey(
        "storage.SkillCatalogEntry",
        on_delete=models.CASCADE,
        related_name="project_installations",
    )
    config_overrides = models.JSONField(default=dict, blank=True)
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = ("project", "skill")
        ordering = ["-date_created"]

    def __str__(self):
        return f"{self.project_id} -> Skill {self.skill_id}"


class ProjectMCPConfig(ShortUUIDMixin):
    """A project-scoped MCP server configuration.

    These MCP servers are automatically available in every conversation in the project.
    """

    class ServerType(models.TextChoices):
        STDIO = "stdio", "Stdio"
        SSE = "sse", "SSE"
        STREAMABLE_HTTP = "streamable-http", "Streamable HTTP"

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_mcp_configs",
    )
    server_name = models.CharField(max_length=100)
    server_type = models.CharField(
        max_length=20,
        choices=ServerType.choices,
        default=ServerType.STDIO,
    )
    command = models.TextField(blank=True, null=True)
    arguments = models.TextField(blank=True, default="")
    env = models.TextField(
        blank=True,
        default="",
        help_text="JSON-formatted string of environment variables.",
    )
    url = models.URLField(blank=True, null=True)
    timeout = models.IntegerField(
        blank=True, null=True, help_text="Timeout in seconds."
    )
    sse_read_timeout = models.IntegerField(blank=True, null=True)
    client_session_timeout_seconds = models.FloatField(blank=True, null=True)
    description = models.TextField(blank=True, default="")
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = ("project", "server_name")
        ordering = ["server_name"]
        verbose_name = "Project MCP Configuration"
        verbose_name_plural = "Project MCP Configurations"

    def __str__(self):
        return f"Project {self.project_id}: {self.server_name}"


class ProjectAddon(ShortUUIDMixin):
    """A marketplace addon attached to a project.

    References the user's authenticated addon registration because addons
    require per-user auth state (OAuth tokens, config_id, server_id).
    """

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="project_addons",
    )
    addon = models.ForeignKey(
        "storage.UserMarketplaceAddons",
        on_delete=models.CASCADE,
        related_name="project_addon_refs",
    )
    config = models.JSONField(default=dict, blank=True)
    added_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        unique_together = ("project", "addon")
        ordering = ["-date_created"]

    def __str__(self):
        return f"Project {self.project_id} -> Addon {self.addon_id}"
