"""Schemas and data transfer objects for the projects API."""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from ninja import ModelSchema, Schema

from apps.spaces.models import Project, ProjectFile
from apps.storage.schemas.addons import UserAddonModelSchema
from apps.storage.schemas.skills import SkillCatalogSchema


@dataclass(frozen=True)
class CreateProjectResult:
    """Result returned after successfully creating a project."""

    project_id: str


@dataclass(frozen=True)
class ProjectUpdationResult:
    """Result returned after successfully updating a project."""

    project_id: str
    modified: bool


@dataclass(frozen=True)
class ProjectRemoveResult:
    """Result returned after successfully deleting a project."""

    project_id: str
    deleted: bool


class ProjectSchema(ModelSchema):
    """Model schema for serializing Project objects."""

    class Meta:
        model = Project
        fields = "__all__"


class ProjectListSchema(ModelSchema):
    """Schema for listing projects with conversation counts."""

    conversation_count: int = 0
    is_shared: bool = False

    class Meta:
        model = Project
        fields = "__all__"

    @staticmethod
    def resolve_conversation_count(obj):
        """Resolve conversation count from annotation or reverse relation."""
        if hasattr(obj, "conversation_count"):
            return obj.conversation_count
        return obj.conversations.count()

    @staticmethod
    def resolve_is_shared(obj):
        """True if the project was included via a ProjectShare (not owned by the requesting user)."""
        return getattr(obj, "_is_shared", False)


class ConversationSummarySchema(Schema):
    """Lightweight conversation schema for embedding in project detail."""

    id: UUID
    title: Optional[str] = None
    date_created: datetime
    date_updated: datetime


class ProjectDetailSchema(ModelSchema):
    """Schema for project detail including its conversations."""

    conversations: List[ConversationSummarySchema] = []
    conversation_count: int = 0

    class Meta:
        model = Project
        fields = "__all__"

    @staticmethod
    def resolve_conversations(obj):
        """Resolve the project's conversations ordered by newest first."""
        return obj.conversations.order_by("-date_created").values(
            "id", "title", "date_created", "date_updated"
        )

    @staticmethod
    def resolve_conversation_count(obj):
        """Resolve conversation count from annotation or reverse relation."""
        if hasattr(obj, "conversation_count"):
            return obj.conversation_count
        return obj.conversations.count()


class ProjectDataSchema(Schema):
    """Schema for project creation and update request payloads."""

    title: str
    description: str
    icon: str = ""
    custom_instructions: str = ""
    organization_id: Optional[str] = None
    template_id: Optional[str] = None
    initial_skill_ids: Optional[List[str]] = None
    isolated_toolkit: bool = False


class ProjectUpdateSchema(Schema):
    """Schema for partial project updates via PATCH."""

    title: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    custom_instructions: Optional[str] = None
    isolated_toolkit: Optional[bool] = None


class ProjectIdSchema(Schema):
    """Schema containing only a project identifier."""

    project_id: str


class ProjectSandboxStatusSchema(Schema):
    """Response schema for project sandbox busy status."""

    busy: bool
    active_conversation_id: Optional[str] = None
    active_conversation_title: Optional[str] = None


# --- ProjectFile schemas ---


class ProjectFileSchema(ModelSchema):
    """Schema for serializing ProjectFile objects."""

    class Meta:
        model = ProjectFile
        fields = [
            "id",
            "filename",
            "file_path",
            "mime_type",
            "size_bytes",
            "date_created",
        ]

    @staticmethod
    def resolve_file_path(obj):
        """Return the file URL if a file is stored, otherwise the sandbox path."""
        if obj.file:
            return obj.file.url
        return obj.file_path


@dataclass(frozen=True)
class ProjectFileUploadResult:
    """Result returned after successfully uploading a file to a project."""

    file_id: str
    filename: str
    size_bytes: int
    mime_type: str


@dataclass(frozen=True)
class ProjectFileRemoveResult:
    """Result returned after successfully deleting a project file."""

    file_id: str
    deleted: bool


# --- ProjectShare schemas ---


class CreateShareRequest(Schema):
    """Request to share a project with a user or organization."""

    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    permission_level: str = "view"


class UpdateShareRequest(Schema):
    """Request to update a share's permission level."""

    permission_level: str


class ProjectShareOut(Schema):
    """Output schema for a project share."""

    id: UUID
    project_id: UUID
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    permission_level: str
    shared_by_id: Optional[str] = None
    shared_at: datetime

    @staticmethod
    def resolve_user_id(obj):
        return str(obj.user_id) if obj.user_id else None

    @staticmethod
    def resolve_organization_id(obj):
        return str(obj.organization_id) if obj.organization_id else None

    @staticmethod
    def resolve_shared_by_id(obj):
        return str(obj.shared_by_id) if obj.shared_by_id else None

    @staticmethod
    def resolve_user_email(obj):
        if obj.user:
            return obj.user.email
        return None

    @staticmethod
    def resolve_organization_name(obj):
        if obj.organization:
            return obj.organization.name
        return None

    @staticmethod
    def resolve_shared_at(obj):
        return obj.date_created


@dataclass(frozen=True)
class ShareDeleteResult:
    """Result returned after revoking a share."""

    share_id: str
    deleted: bool


# --- Project move schemas ---


class MoveProjectRequest(Schema):
    """Request to move a project to/from an organization."""

    organization_id: Optional[str] = None


class BulkMoveProjectRequest(Schema):
    """Request to move multiple projects to/from an organization."""

    project_ids: List[str]
    organization_id: Optional[str] = None


class MoveProjectResult(Schema):
    """Result of moving a single project."""

    project_id: str
    organization_id: Optional[str] = None
    moved: bool
    warnings: List[str] = []


class BulkMoveProjectResult(Schema):
    """Result of a bulk move operation."""

    results: List[MoveProjectResult]
    total: int
    succeeded: int
    failed: int


# ── Project Toolkit schemas ─────────────────────────────────────────────────


# Skills


class ProjectSkillAddRequest(Schema):
    """Request to add a skill to a project."""

    skill_id: str
    config_overrides: Optional[dict] = None


class ProjectSkillOut(Schema):
    """Response schema for a project skill entry."""

    id: UUID
    skill: SkillCatalogSchema
    config_overrides: dict
    date_created: datetime

    @staticmethod
    def resolve_skill(obj):
        return obj.skill


@dataclass(frozen=True)
class ProjectSkillRemoveResult:
    """Result of removing a skill from a project."""

    skill_entry_id: str
    deleted: bool


# MCP Configs


class ProjectMCPConfigCreateRequest(Schema):
    """Request to create a project-scoped MCP config."""

    server_name: str
    server_type: str = "stdio"
    command: Optional[str] = None
    arguments: Optional[str] = ""
    env: Optional[str] = ""
    url: Optional[str] = None
    timeout: Optional[int] = None
    description: Optional[str] = ""


class ProjectMCPConfigUpdateRequest(Schema):
    """Request to update a project MCP config (partial)."""

    server_name: Optional[str] = None
    server_type: Optional[str] = None
    command: Optional[str] = None
    arguments: Optional[str] = None
    env: Optional[str] = None
    url: Optional[str] = None
    timeout: Optional[int] = None
    description: Optional[str] = None


class ProjectMCPConfigOut(Schema):
    """Response schema for a project MCP config."""

    id: UUID
    server_name: str
    server_type: str
    command: Optional[str] = None
    arguments: str = ""
    env: str = ""
    url: Optional[str] = None
    timeout: Optional[int] = None
    sse_read_timeout: Optional[int] = None
    client_session_timeout_seconds: Optional[float] = None
    description: str = ""
    date_created: datetime


@dataclass(frozen=True)
class ProjectMCPConfigRemoveResult:
    """Result of deleting a project MCP config."""

    config_id: str
    deleted: bool


# Addons


class ProjectAddonAddRequest(Schema):
    """Request to add an addon to a project."""

    addon_id: str
    config: Optional[dict] = None


class ProjectAddonOut(Schema):
    """Response schema for a project addon entry."""

    id: UUID
    addon: UserAddonModelSchema
    config: dict
    date_created: datetime

    @staticmethod
    def resolve_addon(obj):
        return obj.addon


@dataclass(frozen=True)
class ProjectAddonRemoveResult:
    """Result of removing an addon from a project."""

    addon_entry_id: str
    deleted: bool


# Bulk toolkit


class ProjectToolkitOut(Schema):
    """Combined response for all toolkit components."""

    isolated_toolkit: bool
    skills: List[ProjectSkillOut] = []
    mcp_configs: List[ProjectMCPConfigOut] = []
    addons: List[ProjectAddonOut] = []


class ProjectToolkitUpdateRequest(Schema):
    """Bulk update request for the entire toolkit."""

    isolated_toolkit: Optional[bool] = None
    skill_ids: Optional[List[str]] = None
    addon_ids: Optional[List[str]] = None
