"""Service layer for conversation CRUD, file uploads, system memory, and thread search."""

import uuid
from functools import cached_property
from typing import Optional, Union

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction
from django.db.models import (
    Case,
    F,
    IntegerField,
    Q,
    QuerySet,
    Value,
    When,
)

from apps.storage.memory import (
    ConversationNotFoundError,
    MemoryServiceError,
)
from apps.storage.models import Conversation, StoredFile, SystemWideMemory
from apps.storage.schemas.memory import (
    ConversationCreateResult,
    FileUploadResult,
)
from apps.users.models import User
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    UnauthorizedAccessError,
)
from config.services.base import BaseService


# Service Layer
class MemoryService(BaseService):
    """
    Complete advanced storage services with all functionality including
    LangChain integration, caching, and comprehensive error handling.
    """

    SERVICE_NAME = "memory_service"
    SERVICE_VERSION = "1.0.0"

    def __init__(self, **kwargs):
        """Initialize MemoryService with base infrastructure."""
        super().__init__(**kwargs)

    @cached_property
    def config(self):
        """Service configuration."""
        return {
            "version": "1.0.0",
            "message_limit": getattr(settings, "MEMORY_MESSAGE_LIMIT", 50),
            "max_file_size": getattr(
                settings, "MAX_FILE_UPLOAD_SIZE", 50 * 1024 * 1024
            ),  # 50MB
            "cache_timeout": getattr(settings, "MEMORY_CACHE_TIMEOUT", 3600),  # 1 hour
        }

    def _get_conversation_for_user(
        self,
        conversation_id: uuid.UUID,
        user: User,
    ) -> Conversation:
        """
        Get conversation by ID with user authorization check and caching.

        Access is granted if the user is the conversation owner, an explicit
        participant, or has access derived from a ProjectShare.

        Args:
            conversation_id: UUID of the conversation
            user: User requesting the conversation

        Returns:
            Conversation: The requested conversation

        Raises:
            ConversationNotFoundError: If conversation doesn't exist
            UnauthorizedAccessError: If user doesn't have access
        """
        from apps.storage.models import conversation_can_view

        # Try cache first
        cache_key = self._get_cache_key("conversation", f"{conversation_id}:{user.id}")
        cached_conversation = self._cache_service.get(cache_key)

        if cached_conversation:
            return cached_conversation

        conversation = Conversation.objects.get_by_id(conversation_id)

        if conversation is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found")

        if not conversation_can_view(conversation, user):
            raise UnauthorizedAccessError("Access denied to this conversation")

        # Cache the conversation
        self._cache_set(cache_key, conversation, self.config["cache_timeout"])

        return conversation

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """Map raw exceptions to domain-specific errors."""
        known_exceptions = (
            ConversationNotFoundError,
            UnauthorizedAccessError,
            InvalidInputError,
            FileProcessingError,
        )
        if isinstance(e, known_exceptions):
            self._logger.info(f"MemoryError in {context}: {e}")
            return e

        if isinstance(e, ValidationError):
            self._logger.warning(f"Validation error in {context}: {e}")
            return InvalidInputError(str(e))

        self._logger.error(f"Unexpected error in {context}: {e}", exc_info=True)
        return MemoryServiceError(f"An unexpected error occurred: {e}")

    # Core Conversation Methods
    def create_conversation(self, request: WSGIRequest) -> ConversationCreateResult:
        """
        Create a new conversation or return existing empty one.

        Args:
            request: HTTP request containing user information

        Returns:
            ConversationCreateResult: Result containing conversation ID and creation status
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            # Create new conversation (messages now live in Exo's PostgresMemoryStore
            # inside the sandbox, not in sukuna DB)
            with transaction.atomic():
                conversation = Conversation.objects.create_conversation(user=user)
                self._logger.info(
                    f"Created new conversation {conversation.id} for user {user.id}"
                )

                return ConversationCreateResult(
                    conversation_id=conversation.id, is_new=True
                )

    def get_conversation(
        self, conversation_id: Union[str, uuid.UUID]
    ) -> Optional[Conversation]:
        """
        Get conversation by ID (backward compatibility method).

        Args:
            conversation_id: UUID or string ID of the conversation

        Returns:
            Optional[Conversation]: The conversation if found
        """
        with self._handle_service_errors():
            if isinstance(conversation_id, str):
                conversation_id = self._validate_uuid(
                    conversation_id, "Conversation ID"
                )

            return Conversation.objects.get_by_id(conversation_id)

    async def get_conversation_async(
        self, conversation_id: Union[str, uuid.UUID]
    ) -> Optional[Conversation]:
        """
        Async version of get_conversation.

        Args:
            conversation_id: UUID or string ID of the conversation

        Returns:
            Optional[Conversation]: The conversation if found
        """
        return await sync_to_async(self.get_conversation)(conversation_id)

    def _get_active_org(self, user):
        """Return the user's active organization or None (personal space)."""
        from apps.users.models import UserSettings

        settings, _ = UserSettings.objects.get_or_create(user=user)
        org = settings.last_active_org
        if org is None:
            return None
        # Verify user is still a member
        if not org.members.filter(pk=user.pk).exists():
            settings.last_active_org = None
            settings.save(update_fields=["last_active_org"])
            return None
        return org

    def get_user_conversations(self, request: WSGIRequest) -> QuerySet[Conversation]:
        """
        Get conversations scoped to the user's active organization context.

        Includes conversations the user owns AND conversations they participate in.
        Excludes soft-deleted conversations (is_deleted=True).

        Args:
            request: HTTP request containing user information

        Returns:
            QuerySet[Conversation]: Optimized queryset of conversations sorted by most recent activity
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            active_org = self._get_active_org(user)

            # Owned OR participating (excluding deleted)
            owned = Q(user=user)
            participating = Q(participants__user=user)
            base_filter = (owned | participating) & Q(is_deleted=False)

            qs = Conversation.objects.filter(base_filter)
            if active_org is not None:
                qs = qs.filter(project__organization=active_org)
            else:
                qs = qs.filter(
                    Q(project__isnull=True) | Q(project__organization__isnull=True)
                )

            return (
                qs.select_related("user", "current_task")
                .order_by("-date_updated")
                .distinct()
            )

    def get_all_user_conversations(self, user_id: int) -> QuerySet[Conversation]:
        """
        Get all conversations for a specific user ID (backward compatibility),
        sorted by latest activity.

        Args:
            user_id: UUID or string ID of the user

        Returns:
            QuerySet[Conversation]: All conversations for the user sorted by most recent activity
        """
        with self._handle_service_errors():
            return Conversation.objects.by_user_id(user_id)

    def delete_conversation(self, request: WSGIRequest, conversation_id: str) -> None:
        """
        Delete a conversation with proper authorization.

        Args:
            request: HTTP request containing user information
            conversation_id: UUID string of the conversation to delete
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            conv_uuid = self._validate_uuid(conversation_id, "Conversation ID")

            conversation = self._get_conversation_for_user(conv_uuid, user)

            with transaction.atomic():
                conversation.delete()
                # Clear cache
                cache_key = self._get_cache_key(
                    "conversation", f"{conv_uuid}:{user.id}"
                )
                self._cache_delete(cache_key)

                self._logger.info(
                    f"Deleted conversation {conv_uuid} for user {user.id}"
                )

    def update_conversation(
        self,
        request: WSGIRequest,
        conversation_id: str,
        title: str = None,
        metadata: dict = None,
    ) -> Conversation:
        """
        Update a conversation's title and/or metadata with proper authorization.

        Args:
            request: HTTP request containing user information
            conversation_id: UUID string of the conversation to update
            title: New title for the conversation (optional)
            metadata: Metadata fields to merge into existing metadata (optional)

        Returns:
            Conversation: The updated conversation
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)
            conv_uuid = self._validate_uuid(conversation_id, "Conversation ID")

            conversation = self._get_conversation_for_user(conv_uuid, user)

            update_fields = ["date_updated"]

            with transaction.atomic():
                if title is not None:
                    conversation.title = title
                    update_fields.append("title")

                if metadata is not None:
                    existing = conversation.metadata or {}
                    existing.update(metadata)
                    conversation.metadata = existing
                    update_fields.append("metadata")

                conversation.save(update_fields=update_fields)

                # Clear cache
                cache_key = self._get_cache_key(
                    "conversation", f"{conv_uuid}:{user.id}"
                )
                self._cache_delete(cache_key)

                self._logger.info(
                    f"Updated conversation {conv_uuid} for user {user.id}"
                )
                return conversation

    def delete_all_user_conversations(self, request: WSGIRequest) -> int:
        """
        Delete all conversations for the authenticated user.

        Args:
            request: HTTP request containing user information

        Returns:
            int: Number of conversations deleted
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            with transaction.atomic():
                deleted_count = Conversation.objects.delete_for_user(user)

                self._logger.info(
                    f"Deleted {deleted_count} conversations for user {user.id}"
                )
                return deleted_count

    # File Handling Methods

    def upload_file(
        self, request: WSGIRequest, uploaded_file: UploadedFile
    ) -> FileUploadResult:
        """
        Upload and store a file with validation.

        Args:
            request: HTTP request containing user information
            uploaded_file: The file to upload

        Returns:
            FileUploadResult: Information about the uploaded file
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            # Validate file
            if not uploaded_file or not uploaded_file.name:
                raise InvalidInputError("File is required")

            if uploaded_file.size > self.config["max_file_size"]:
                raise InvalidInputError(
                    f"File size exceeds limit of {self.config['max_file_size']} bytes"
                )

            mime_type = uploaded_file.content_type or ""

            # Store file
            with transaction.atomic():
                stored_file = StoredFile.objects.create_file(
                    owner=user,
                    file=uploaded_file,
                    name=uploaded_file.name,
                    size=uploaded_file.size,
                    mime_type=mime_type,
                )

                self._logger.info(f"Uploaded file {stored_file.id} for user {user.id}")

                return FileUploadResult(
                    file_id=stored_file.id,
                    filename=stored_file.name,
                    size=stored_file.size,
                    mime_type=stored_file.mime_type,
                )

    def get_user_files(self, request: WSGIRequest) -> QuerySet[StoredFile]:
        """
        Get all files for the authenticated user.

        Args:
            request: HTTP request containing user information

        Returns:
            QuerySet[StoredFile]: User's files
        """
        with self._handle_service_errors():
            user = self._get_authenticated_user(request)

            return StoredFile.objects.for_user(user)

    # System Memory Methods

    def get_system_memory(self, user: User) -> Optional[SystemWideMemory]:
        """
        Get system-wide storage for a user.

        Args:
            user: The user to get storage for

        Returns:
            Optional[SystemWideMemory]: System storage if found
        """
        with self._handle_service_errors():
            if not isinstance(user, User):
                raise InvalidInputError("Valid user required")

            # Try cache first
            cache_key = self._get_cache_key("system_memory", str(user.id))
            cached_memory = self._cache_service.get(cache_key)
            if cached_memory:
                return cached_memory

            memory = SystemWideMemory.objects.for_user(user)
            if memory:
                self._cache_set(cache_key, memory, self.config["cache_timeout"])

            return memory

    def search_threads(
        self, request: WSGIRequest, query: str
    ) -> Optional[QuerySet[Conversation]]:
        """Search conversations by title and summary with relevance-based ranking.

        Args:
            request: The HTTP request with authenticated user.
            query: The search query string.

        Returns:
            QuerySet[Conversation]: Matching conversations ranked by relevance.

        Raises:
            InvalidInputError: If the query is empty.
        """
        with self._handle_service_errors():
            self._validate_required_field(query, "query", str)
            if not query or query == "":
                raise InvalidInputError("Query cannot be empty")

            user = self._get_authenticated_user(request)
            query_lower = query.lower().strip()

            return (
                Conversation.objects.select_related("user", "project")
                .annotate(
                    # Exact title match gets highest score
                    exact_title=Case(
                        When(title__iexact=query_lower, then=Value(10)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Title contains gets high score
                    title_match=Case(
                        When(title__icontains=query_lower, then=Value(5)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                    # Summary contains gets medium score
                    summary_match=Case(
                        When(summary__icontains=query_lower, then=Value(3)),
                        default=Value(0),
                        output_field=IntegerField(),
                    ),
                )
                .annotate(
                    relevance_score=F("exact_title")
                    + F("title_match")
                    + F("summary_match")
                )
                .filter(
                    relevance_score__gt=0,
                )
                .filter(Q(user=user) | Q(participants__user=user))
                .filter(is_deleted=False)
                .order_by("-relevance_score", "-date_updated")
                .distinct()
            )
