import uuid
from unittest.mock import Mock

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from apps.storage.memory import (
    ConversationNotFoundError,
    MemoryServiceError,
)
from apps.storage.models import Conversation, StoredFile, SystemWideMemory
from apps.storage.schemas.memory import (
    ConversationCreateResult,
    FileUploadResult,
)
from apps.storage.services.memory import MemoryService
from apps.users.models import User
from config.errors.common import InvalidInputError, UnauthorizedAccessError


class MemoryServiceBaseTestCase(TestCase):
    """Base test case with common setup for MemoryService tests."""

    def setUp(self):
        """Set up test fixtures."""
        self.factory = RequestFactory()
        self.mock_user_service = Mock()
        self.mock_cache_service = Mock()
        self.mock_logger = Mock()

        # Create test user
        self.user = User.objects.create(email="test@example.com")

        # Create another user for authorization tests
        self.other_user = User.objects.create(email="other@example.com")

        # Initialize services with mocked dependencies
        self.service = MemoryService(
            user_service=self.mock_user_service,
            cache_service=self.mock_cache_service,
            logger=self.mock_logger,
        )

    def _create_authenticated_request(self, user=None, method="GET", path="/"):
        """Helper to create authenticated request."""
        request = (
            self.factory.get(path)
            if method == "GET"
            else getattr(self.factory, method.lower())(path)
        )
        request.user = user or self.user
        return request

    def _create_conversation(self, user=None):
        """Helper to create test conversation."""
        user = user or self.user
        conversation = Conversation.objects.create(user=user)
        return conversation


class MemoryServiceInitializationTest(MemoryServiceBaseTestCase):
    """Test MemoryService initialization and configuration."""

    def test_default_initialization(self):
        """Test services initializes with default dependencies."""
        service = MemoryService()

        self.assertIsNotNone(service._user_service)
        self.assertIsNotNone(service._cache_service)
        self.assertIsNotNone(service._logger)

    def test_custom_initialization(self):
        """Test services initializes with custom dependencies."""
        custom_user_service = Mock()
        custom_cache_service = Mock()
        custom_logger = Mock()

        service = MemoryService(
            user_service=custom_user_service,
            cache_service=custom_cache_service,
            logger=custom_logger,
        )

        self.assertEqual(service._user_service, custom_user_service)
        self.assertEqual(service._cache_service, custom_cache_service)
        self.assertEqual(service._logger, custom_logger)

    def test_config_property(self):
        """Test services configuration property."""
        config = self.service.config

        self.assertIn("version", config)
        self.assertIn("message_limit", config)
        self.assertIn("max_file_size", config)
        self.assertIn("cache_timeout", config)

        # Test caching of config property
        config2 = self.service.config
        self.assertIs(config, config2)  # Should be same object due to cached_property


class MemoryServiceAuthenticationTest(MemoryServiceBaseTestCase):
    """Test authentication and authorization functionality."""

    def test_get_authenticated_user_success(self):
        """Test successful user authentication."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service._get_authenticated_user(request)

        self.assertEqual(result, self.user)
        self.mock_user_service.get_profile_from_request.assert_called_once_with(request)

    def test_get_authenticated_user_no_profile(self):
        """Test authentication failure with no profile."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = None

        with self.assertRaises(UnauthorizedAccessError) as cm:
            self.service._get_authenticated_user(request)

        self.assertIn("Authentication required", str(cm.exception))
        self.mock_logger.warning.assert_called_once()

    def test_get_authenticated_user_invalid_profile(self):
        """Test authentication failure with invalid profile type."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = "invalid"

        with self.assertRaises(UnauthorizedAccessError):
            self.service._get_authenticated_user(request)

    def test_get_authenticated_user_service_exception(self):
        """Test authentication failure due to services exception."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.side_effect = Exception(
            "Service error"
        )

        with self.assertRaises(UnauthorizedAccessError) as cm:
            self.service._get_authenticated_user(request)

        self.assertIn("Invalid authentication", str(cm.exception))


class MemoryServiceValidationTest(MemoryServiceBaseTestCase):
    """Test input validation functionality."""

    def test_validate_uuid_success(self):
        """Test successful UUID validation."""
        test_uuid = uuid.uuid4()
        result = self.service._validate_uuid(str(test_uuid))

        self.assertEqual(result, test_uuid)

    def test_validate_uuid_none_value(self):
        """Test UUID validation with None value."""
        with self.assertRaises(InvalidInputError) as cm:
            self.service._validate_uuid(None)

        self.assertIn("is required", str(cm.exception))

    def test_validate_uuid_empty_string(self):
        """Test UUID validation with empty string."""
        with self.assertRaises(InvalidInputError) as cm:
            self.service._validate_uuid("")

        self.assertIn("is required", str(cm.exception))

    def test_validate_uuid_invalid_format(self):
        """Test UUID validation with invalid format."""
        with self.assertRaises(InvalidInputError) as cm:
            self.service._validate_uuid("invalid-uuid")

        self.assertIn("Invalid ID format", str(cm.exception))

    def test_validate_uuid_custom_field_name(self):
        """Test UUID validation with custom field name."""
        with self.assertRaises(InvalidInputError) as cm:
            self.service._validate_uuid("invalid", "Conversation ID")

        self.assertIn("Invalid Conversation ID format", str(cm.exception))


class MemoryServiceCacheTest(MemoryServiceBaseTestCase):
    """Test caching functionality."""

    def test_get_cache_key(self):
        """Test cache key generation."""
        key = self.service._get_cache_key("conversation", "123")
        expected = "memory_service:conversation:123"

        self.assertEqual(key, expected)

    def test_conversation_caching_on_get(self):
        """Test conversation is cached when retrieved."""
        conversation = self._create_conversation()
        self.mock_cache_service.get.return_value = None

        result = self.service._get_conversation_for_user(conversation.id, self.user)

        self.assertEqual(result, conversation)
        expected_cache_key = (
            f"memory_service:conversation:{conversation.id}:{self.user.id}"
        )
        self.mock_cache_service.set.assert_called_once_with(
            expected_cache_key, conversation, self.service.config["cache_timeout"]
        )

    def test_conversation_retrieved_from_cache(self):
        """Test conversation is retrieved from cache when available."""
        conversation = self._create_conversation()
        cache_key = f"memory_service:conversation:{conversation.id}:{self.user.id}"
        self.mock_cache_service.get.return_value = conversation

        result = self.service._get_conversation_for_user(conversation.id, self.user)

        self.assertEqual(result, conversation)
        self.mock_cache_service.get.assert_called_once_with(cache_key)
        # Should not hit database or set cache again
        self.mock_cache_service.set.assert_not_called()


class MemoryServiceConversationTest(MemoryServiceBaseTestCase):
    """Test conversation-related functionality."""

    def test_create_conversation_new(self):
        """Test creating a new conversation."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service.create_conversation(request)

        self.assertIsInstance(result, ConversationCreateResult)
        self.assertTrue(result.is_new)
        self.assertIsInstance(result.conversation_id, uuid.UUID)

        # Verify conversation was created in database
        conversation = Conversation.objects.get(id=result.conversation_id)
        self.assertEqual(conversation.user, self.user)

    def test_create_conversation_with_existing(self):
        """Test creating conversation when one already exists creates a new one."""
        Conversation.objects.create(user=self.user)
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service.create_conversation(request)

        self.assertIsInstance(result, ConversationCreateResult)
        self.assertTrue(result.is_new)

        # Should have created a new conversation
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 2)

    def test_create_conversation_always_creates_new(self):
        """Test creating conversation always creates a new one."""
        existing_conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service.create_conversation(request)

        self.assertTrue(result.is_new)
        self.assertNotEqual(result.conversation_id, existing_conversation.id)
        self.assertEqual(Conversation.objects.filter(user=self.user).count(), 2)

    def test_get_conversation_success(self):
        """Test successful conversation retrieval."""
        conversation = self._create_conversation()

        result = self.service.get_conversation(conversation.id)

        self.assertEqual(result, conversation)

    def test_get_conversation_string_id(self):
        """Test conversation retrieval with string ID."""
        conversation = self._create_conversation()

        result = self.service.get_conversation(str(conversation.id))

        self.assertEqual(result, conversation)

    def test_get_conversation_not_found(self):
        """Test conversation retrieval when not found."""
        non_existent_id = uuid.uuid4()

        result = self.service.get_conversation(non_existent_id)

        self.assertIsNone(result)

    def test_get_conversation_invalid_id(self):
        """Test conversation retrieval with invalid ID."""
        with self.assertRaises(InvalidInputError):
            self.service.get_conversation("invalid-id")

    def test_get_user_conversations(self):
        """Test retrieving all user conversations."""
        conversation1 = self._create_conversation()
        conversation2 = self._create_conversation()
        # Create conversation for other user (should not be included)
        self._create_conversation(user=self.other_user)

        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        conversations = self.service.get_user_conversations(request)

        self.assertEqual(conversations.count(), 2)
        conversation_ids = {conv.id for conv in conversations}
        self.assertIn(conversation1.id, conversation_ids)
        self.assertIn(conversation2.id, conversation_ids)

    def test_get_all_user_conversations_with_uuid(self):
        """Test retrieving all conversations for user ID (UUID)."""
        self._create_conversation()
        self._create_conversation()

        conversations = self.service.get_all_user_conversations(self.user.id)

        self.assertEqual(conversations.count(), 2)

    def test_get_all_user_conversations_with_string(self):
        """Test retrieving all conversations for user ID (string)."""
        self._create_conversation()
        conversations = self.service.get_all_user_conversations(str(self.user.id))

        self.assertEqual(conversations.count(), 1)

    def test_delete_conversation_success(self):
        """Test successful conversation deletion."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None  # Not cached

        self.service.delete_conversation(request, str(conversation.id))

        with self.assertRaises(Conversation.DoesNotExist):
            Conversation.objects.get(id=conversation.id)

        # Verify cache was cleared
        expected_cache_key = (
            f"memory_service:conversation:{conversation.id}:{self.user.id}"
        )
        self.mock_cache_service.delete.assert_called_once_with(expected_cache_key)

    def test_delete_conversation_unauthorized(self):
        """Test conversation deletion without authorization."""
        conversation = self._create_conversation(user=self.other_user)
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        with self.assertRaises(UnauthorizedAccessError):
            self.service.delete_conversation(request, str(conversation.id))

        # Conversation should still exist
        self.assertTrue(Conversation.objects.filter(id=conversation.id).exists())

    def test_delete_conversation_not_found(self):
        """Test deleting non-existent conversation."""
        non_existent_id = uuid.uuid4()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        with self.assertRaises(ConversationNotFoundError):
            self.service.delete_conversation(request, str(non_existent_id))

    def test_delete_all_user_conversations(self):
        """Test deleting all user conversations."""
        self._create_conversation()
        self._create_conversation()
        # Create conversation for other user (should not be deleted)
        other_conversation = self._create_conversation(user=self.other_user)

        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        deleted_count = self.service.delete_all_user_conversations(request)

        self.assertEqual(deleted_count, 2)
        self.assertFalse(Conversation.objects.filter(user=self.user).exists())
        self.assertTrue(Conversation.objects.filter(id=other_conversation.id).exists())

        # Verify caches were cleared
        self.assertEqual(self.mock_cache_service.delete.call_count, 2)


class MemoryServiceUpdateConversationTest(MemoryServiceBaseTestCase):
    """Test conversation update functionality including metadata/branch tracking."""

    def test_update_title_only(self):
        """Test updating only the title."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        result = self.service.update_conversation(
            request, str(conversation.id), title="New Title"
        )

        self.assertEqual(result.title, "New Title")
        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "New Title")

    def test_update_metadata_branches(self):
        """Test updating metadata with branch information."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        branches = [
            {
                "name": "main",
                "created_at": "2026-02-24T10:00:00Z",
                "parent_message_id": None,
            },
            {
                "name": "branch-1",
                "created_at": "2026-02-24T11:00:00Z",
                "parent_message_id": "msg-123",
            },
        ]
        self.service.update_conversation(
            request, str(conversation.id), metadata={"branches": branches}
        )

        conversation.refresh_from_db()
        self.assertEqual(conversation.metadata["branches"], branches)
        self.assertEqual(len(conversation.metadata["branches"]), 2)

    def test_update_metadata_merges_with_existing(self):
        """Test that metadata update merges with existing metadata."""
        conversation = Conversation.objects.create(
            user=self.user,
            metadata={"shared": True, "model": "gpt-4"},
        )
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        branches = [
            {
                "name": "main",
                "created_at": "2026-02-24T10:00:00Z",
                "parent_message_id": None,
            }
        ]
        self.service.update_conversation(
            request, str(conversation.id), metadata={"branches": branches}
        )

        conversation.refresh_from_db()
        # Existing keys should be preserved
        self.assertTrue(conversation.metadata["shared"])
        self.assertEqual(conversation.metadata["model"], "gpt-4")
        # New key should be added
        self.assertEqual(conversation.metadata["branches"], branches)

    def test_update_title_and_metadata(self):
        """Test updating both title and metadata simultaneously."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        branches = [
            {
                "name": "main",
                "created_at": "2026-02-24T10:00:00Z",
                "parent_message_id": None,
            }
        ]
        self.service.update_conversation(
            request,
            str(conversation.id),
            title="Updated",
            metadata={"branches": branches},
        )

        conversation.refresh_from_db()
        self.assertEqual(conversation.title, "Updated")
        self.assertEqual(conversation.metadata["branches"], branches)

    def test_update_no_fields_still_updates_date(self):
        """Test that calling update with no title or metadata still updates date_updated."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        self.service.update_conversation(request, str(conversation.id))

        conversation.refresh_from_db()
        # date_updated should be in update_fields so it gets updated
        self.assertIsNotNone(conversation.date_updated)

    def test_update_metadata_clears_cache(self):
        """Test that metadata update clears the conversation cache."""
        conversation = self._create_conversation()
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        self.service.update_conversation(
            request, str(conversation.id), metadata={"branches": []}
        )

        expected_cache_key = (
            f"memory_service:conversation:{conversation.id}:{self.user.id}"
        )
        self.mock_cache_service.delete.assert_called_once_with(expected_cache_key)

    def test_update_unauthorized(self):
        """Test updating another user's conversation fails."""
        conversation = self._create_conversation(user=self.other_user)
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        self.mock_cache_service.get.return_value = None

        with self.assertRaises(UnauthorizedAccessError):
            self.service.update_conversation(
                request, str(conversation.id), metadata={"branches": []}
            )


class MemoryServiceFileTest(MemoryServiceBaseTestCase):
    """Test file handling functionality."""

    def setUp(self):
        super().setUp()
        self.test_file_content = b"Test file content"
        self.test_file = SimpleUploadedFile(
            name="test.txt", content=self.test_file_content, content_type="text/plain"
        )

    def test_upload_file_success(self):
        """Test successful file upload."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service.upload_file(request, self.test_file)

        self.assertIsInstance(result, FileUploadResult)
        self.assertEqual(result.filename, "test.txt")
        self.assertEqual(result.size, len(self.test_file_content))
        self.assertEqual(result.mime_type, "text/plain")

        # Verify file was stored in database
        stored_file = StoredFile.objects.get(id=result.file_id)
        self.assertEqual(stored_file.owner, self.user)
        self.assertEqual(stored_file.name, "test.txt")

    def test_upload_file_no_file(self):
        """Test file upload with no file."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        with self.assertRaises(InvalidInputError) as cm:
            self.service.upload_file(request, None)

        self.assertIn("File is required", str(cm.exception))

    def test_upload_file_no_filename(self):
        """Test file upload with no filename."""
        from unittest.mock import Mock

        file_without_name = Mock()
        file_without_name.name = None  # or ""
        file_without_name.read.return_value = self.test_file_content
        file_without_name.content_type = "text/plain"

        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        with self.assertRaises(InvalidInputError) as cm:
            self.service.upload_file(request, file_without_name)

        self.assertIn("File is required", str(cm.exception))

    def test_upload_file_too_large(self):
        """Test file upload with oversized file."""
        large_content = b"x" * (self.service.config["max_file_size"] + 1)
        large_file = SimpleUploadedFile(
            name="large.txt", content=large_content, content_type="text/plain"
        )
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        with self.assertRaises(InvalidInputError) as cm:
            self.service.upload_file(request, large_file)

        self.assertIn("File size exceeds limit", str(cm.exception))

    def test_upload_file_any_mime_type(self):
        """Test file upload accepts any MIME type."""
        exe_file = SimpleUploadedFile(
            name="test.exe",
            content=self.test_file_content,
            content_type="application/x-executable",
        )
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        result = self.service.upload_file(request, exe_file)
        self.assertEqual(result.filename, "test.exe")
        self.assertEqual(result.mime_type, "application/x-executable")

    def test_upload_file_unauthorized(self):
        """Test file upload without authentication."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = None

        with self.assertRaises(UnauthorizedAccessError):
            self.service.upload_file(request, self.test_file)

    def test_get_user_files(self):
        """Test retrieving user files."""
        # Create test files
        stored_file1 = StoredFile.objects.create(
            owner=self.user, name="file1.txt", size=100, mime_type="text/plain"
        )
        stored_file2 = StoredFile.objects.create(
            owner=self.user, name="file2.txt", size=200, mime_type="text/plain"
        )
        # Create file for other user (should not be included)
        StoredFile.objects.create(
            owner=self.other_user, name="other.txt", size=50, mime_type="text/plain"
        )

        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user

        files = self.service.get_user_files(request)

        self.assertEqual(files.count(), 2)
        file_ids = {f.id for f in files}
        self.assertIn(stored_file1.id, file_ids)
        self.assertIn(stored_file2.id, file_ids)


class MemoryServiceSystemMemoryTest(MemoryServiceBaseTestCase):
    """Test system storage functionality."""

    def test_get_system_memory_success(self):
        """Test successful system storage retrieval."""
        system_memory = SystemWideMemory.objects.create(
            user=self.user, memory_summary="System storage content"
        )
        self.mock_cache_service.get.return_value = None

        result = self.service.get_system_memory(self.user)

        self.assertEqual(result, system_memory)
        # Verify caching
        expected_cache_key = f"memory_service:system_memory:{self.user.id}"
        self.mock_cache_service.set.assert_called_once_with(
            expected_cache_key, system_memory, self.service.config["cache_timeout"]
        )

    def test_get_system_memory_from_cache(self):
        """Test system storage retrieval from cache."""
        system_memory = SystemWideMemory.objects.create(
            user=self.user, memory_summary="System storage content"
        )
        self.mock_cache_service.get.return_value = system_memory

        result = self.service.get_system_memory(self.user)

        self.assertEqual(result, system_memory)
        self.mock_cache_service.set.assert_not_called()

    def test_get_system_memory_not_found(self):
        """Test system storage retrieval when not found."""
        self.mock_cache_service.get.return_value = None

        result = self.service.get_system_memory(self.user)

        self.assertIsNone(result)

    def test_get_system_memory_invalid_user(self):
        """Test system storage retrieval with invalid user."""
        with self.assertRaises(InvalidInputError) as cm:
            self.service.get_system_memory("invalid_user")

        self.assertIn("Valid user required", str(cm.exception))


class MemoryServiceErrorHandlingTest(MemoryServiceBaseTestCase):
    """Test error handling and logging functionality."""

    def test_handle_service_errors_domain_exception(self):
        """Test that domain exceptions are re-raised as-is."""
        with self.assertRaises(ConversationNotFoundError):
            with self.service._handle_service_errors():
                raise ConversationNotFoundError("Test error")

    def test_handle_service_errors_validation_error(self):
        """Test ValidationError is converted to InvalidInputError."""
        with self.assertRaises(InvalidInputError):
            with self.service._handle_service_errors():
                raise ValidationError("Validation failed")

    def test_handle_service_errors_unexpected_exception(self):
        """Test unexpected exceptions are converted to MemoryServiceError."""
        with self.assertRaises(MemoryServiceError) as cm:
            with self.service._handle_service_errors():
                raise ValueError("Unexpected error")

        self.assertIn("unexpected error occurred", str(cm.exception))
        self.mock_logger.error.assert_called_once()

    def test_conversation_not_found_during_get_for_user(self):
        """Test ConversationNotFoundError when conversation doesn't exist."""
        non_existent_id = uuid.uuid4()
        self.mock_cache_service.get.return_value = None

        with self.assertRaises(ConversationNotFoundError) as cm:
            self.service._get_conversation_for_user(non_existent_id, self.user)

        self.assertIn(str(non_existent_id), str(cm.exception))

    def test_unauthorized_access_during_get_for_user(self):
        """Test UnauthorizedAccessError when user doesn't own conversation."""
        conversation = self._create_conversation(user=self.other_user)
        self.mock_cache_service.get.return_value = None

        with self.assertRaises(UnauthorizedAccessError) as cm:
            self.service._get_conversation_for_user(conversation.id, self.user)

        self.assertIn("Access denied", str(cm.exception))


class MemoryServiceSpaceTest(MemoryServiceBaseTestCase):
    """Test space/workspace functionality (placeholder implementation)."""

    def test_get_spaces_conversations_placeholder(self):
        """Test spaces conversations returns empty queryset (placeholder)."""
        request = self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
        space_id = str(uuid.uuid4())

        conversations = self.service.get_spaces_conversations(request, space_id)

        self.assertEqual(conversations.count(), 0)

    def test_get_spaces_conversations_invalid_space_id(self):
        """Test spaces conversations with invalid space ID."""
        self._create_authenticated_request()
        self.mock_user_service.get_profile_from_request.return_value = self.user
