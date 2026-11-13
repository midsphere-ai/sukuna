"""Request/response schemas and DTOs for conversation, file, and memory API endpoints."""

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from ninja import ModelSchema, Schema

from apps.storage.models import (
    AgentRun,
    Conversation,
    StoredFile,
    SystemWideMemory,
)


# Domain Models / DTOs
@dataclass(frozen=True)
class ConversationCreateResult:
    """Result of conversation creation operation."""

    conversation_id: uuid.UUID
    is_new: bool


@dataclass(frozen=True)
class FileUploadResult:
    """Result of file upload operation."""

    file_id: uuid.UUID
    filename: str
    size: int
    mime_type: str


class AgentRunSchema(ModelSchema):
    """Serialization schema for AgentRun with nested conversation data."""

    conversation: Optional["ConversationModelSchema"]

    class Meta:
        model = AgentRun
        fields = "__all__"


class ConversationModelSchema(ModelSchema):
    """Model Schema for Conversation Object"""

    status: str = None
    on_going: bool = False
    has_error: bool = False
    error: Optional[str] = None
    cancellation_requested: bool = False

    class Meta:
        model = Conversation
        exclude = ("current_task",)

    @staticmethod
    def resolve_status(obj):
        """Resolve the conversation's display status from its current agent run.

        Args:
            obj: The Conversation model instance.

        Returns:
            str: A status string such as 'idle', 'queued', 'running', 'completed', etc.
        """
        if not obj.current_task_id:
            return "idle"

        try:
            status = obj.current_task.status
            if status == "pending":
                return "queued"
            if status in (
                "queued",
                "provisioning",
                "running",
                "completed",
                "failed",
                "cancelled",
                "idle",
            ):
                return status
        except Exception:
            pass

        return "completed"

    @staticmethod
    def resolve_on_going(obj):
        """Resolve whether the conversation has an active agent run.

        Args:
            obj: The Conversation model instance.

        Returns:
            bool: True if the current task is in an active state.
        """
        return obj.get_is_ongoing()

    @staticmethod
    def resolve_has_error(obj):
        """Resolve whether the conversation's current task has failed.

        Args:
            obj: The Conversation model instance.

        Returns:
            bool: True if the current task status is 'failed'.
        """
        return obj.get_has_error()

    @staticmethod
    def resolve_error(obj):
        """Resolve the error message from the conversation's current task.

        Args:
            obj: The Conversation model instance.

        Returns:
            str: The error message, or empty string if none.
        """
        return obj.get_error_message()

    @staticmethod
    def resolve_cancellation_requested(obj):
        """Resolve whether the conversation's current task was cancelled.

        Args:
            obj: The Conversation model instance.

        Returns:
            bool: True if the current task status is 'cancelled'.
        """
        return obj.get_is_cancellation_requested()


class SystemWideMemorySchema(ModelSchema):
    """Model Schema for system wide memmory object"""

    class Meta:
        model = SystemWideMemory
        fields = "__all__"


class StoreFiledSchema(ModelSchema):
    """Model schema for a stored file, resolving the file field to its URL."""

    class Meta:
        model = StoredFile
        fields = "__all__"

    @staticmethod
    def resolve_file(obj):
        """Return the file URL instead of the storage path.

        Args:
            obj: The StoredFile model instance.

        Returns:
            str or None: The file URL, or None if no file is attached.
        """
        if obj.file:
            return obj.file.url
        return None


class SharedConversationSchema(Schema):
    """Response schema for shared conversation (unauthenticated)."""

    id: str
    title: str
    date_created: str
    date_updated: str


class ConversationUpdateRequest(Schema):
    """Request schema for updating a conversation."""

    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ConversationCreateResponse(Schema):
    """Response schema for conversation creation."""

    conversation_id: str
    is_new: bool
    message: str = "Conversation created successfully"


class DeleteResponse(Schema):
    """Response schema for delete operations."""

    message: str
    deleted_count: int = None


class FileUploadResponse(Schema):
    """Response schema for file uploads."""

    file_id: str
    filename: str
    size: int
    mime_type: str
    message: str = "File uploaded successfully"


class HealthResponse(Schema):
    """Response schema for health check."""

    status: str
    version: str
    cache_enabled: bool
    timestamp: str


class FileRetrieveResponse(Schema):
    """Response schema for file retrieval from storage."""

    url: str
    filename: str
    mime_type: Optional[str] = None
    size: Optional[int] = None


class UserSettingsSchema(Schema):
    """Response schema for user settings."""

    id: int
    theme: str = "system"
    accent_color: str = ""
    custom_instructions: str = ""
    nickname: str = ""
    occupation: str = ""
    about_you: str = ""
    onboarding_completed: Optional[bool] = None
    web_search: bool = True
    browser: bool = True
    shell_commands: bool = True
    complex_reasoning: bool = True
    computer_use: bool = True
    notification_email: bool = True
    notification_push: bool = True
    notification_marketing: bool = False
    data_share_analytics: bool = True
    data_share_training: bool = False
    backend_url: str = ""
    local_mode: bool = False
    local_sandbox_url: str = ""


class UserSettingsUpdateSchema(Schema):
    """Request schema for partial update of user settings."""

    theme: Optional[str] = None
    accent_color: Optional[str] = None
    custom_instructions: Optional[str] = None
    nickname: Optional[str] = None
    occupation: Optional[str] = None
    about_you: Optional[str] = None
    onboarding_completed: Optional[bool] = None
    web_search: Optional[bool] = None
    browser: Optional[bool] = None
    shell_commands: Optional[bool] = None
    complex_reasoning: Optional[bool] = None
    computer_use: Optional[bool] = None
    notification_email: Optional[bool] = None
    notification_push: Optional[bool] = None
    notification_marketing: Optional[bool] = None
    data_share_analytics: Optional[bool] = None
    data_share_training: Optional[bool] = None
    backend_url: Optional[str] = None
    local_mode: Optional[bool] = None
    local_sandbox_url: Optional[str] = None
