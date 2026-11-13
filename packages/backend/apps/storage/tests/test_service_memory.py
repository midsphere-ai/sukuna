"""Unit tests for MemoryService business logic."""

import logging
import uuid
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.storage.memory import ConversationNotFoundError, MemoryServiceError
from apps.storage.models import Conversation
from apps.storage.services.memory import MemoryService
from apps.users.tests.factories import UserFactory
from config.errors.common import InvalidInputError, UnauthorizedAccessError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(user):
    request = MagicMock()
    request.auth = user
    return request


def _make_service(user):
    svc = MemoryService.__new__(MemoryService)
    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._cache_service.get.return_value = None
    svc._logger = logging.getLogger("test.memory")
    svc._service_kwargs = {}
    svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


# ---------------------------------------------------------------------------
# _map_and_log_error
# ---------------------------------------------------------------------------
class TestMemoryErrorMapping:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_known_error_passthrough(self):
        e = ConversationNotFoundError("gone")
        assert self.svc._map_and_log_error(e, "ctx") is e

    def test_validation_error_maps_to_input(self):
        from django.core.exceptions import ValidationError

        e = ValidationError("bad")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_unexpected_maps_to_memory_error(self):
        e = RuntimeError("boom")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, MemoryServiceError)


# ---------------------------------------------------------------------------
# create_conversation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateConversation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_create_new(self):
        result = self.svc.create_conversation(self.request)
        assert result.is_new is True
        assert Conversation.objects.filter(user=self.user).count() == 1


# ---------------------------------------------------------------------------
# get_conversation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetConversation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.conv = Conversation.objects.create(user=self.user, title="Test")

    def test_get_by_uuid(self):
        result = self.svc.get_conversation(self.conv.id)
        assert result.id == self.conv.id

    def test_get_by_string(self):
        result = self.svc.get_conversation(str(self.conv.id))
        assert result.id == self.conv.id

    def test_get_nonexistent(self):
        result = self.svc.get_conversation(str(uuid.uuid4()))
        assert result is None


# ---------------------------------------------------------------------------
# get_user_conversations / get_all_user_conversations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetUserConversations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        Conversation.objects.create(user=self.user, title="A")
        Conversation.objects.create(user=self.user, title="B")

    def test_get_user_conversations(self):
        convs = self.svc.get_user_conversations(self.request)
        assert convs.count() == 2

    def test_get_all_user_conversations(self):
        convs = self.svc.get_all_user_conversations(self.user.id)
        assert convs.count() == 2


# ---------------------------------------------------------------------------
# _get_conversation_for_user
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetConversationForUser:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)

    def test_success(self):
        conv = Conversation.objects.create(user=self.user, title="Mine")
        result = self.svc._get_conversation_for_user(conv.id, self.user)
        assert result.id == conv.id

    def test_not_found(self):
        with pytest.raises(ConversationNotFoundError):
            self.svc._get_conversation_for_user(uuid.uuid4(), self.user)

    def test_wrong_user(self):
        other = UserFactory()
        conv = Conversation.objects.create(user=other, title="Other")
        with pytest.raises(UnauthorizedAccessError):
            self.svc._get_conversation_for_user(conv.id, self.user)

    def test_cache_hit(self):
        conv = Conversation.objects.create(user=self.user, title="Cached")
        self.svc._cache_service.get.return_value = conv
        result = self.svc._get_conversation_for_user(conv.id, self.user)
        assert result.id == conv.id


# ---------------------------------------------------------------------------
# delete_conversation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteConversation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_delete_success(self):
        conv = Conversation.objects.create(user=self.user, title="Gone")
        self.svc.delete_conversation(self.request, str(conv.id))
        assert Conversation.objects.filter(id=conv.id).count() == 0

    def test_delete_nonexistent(self):
        with pytest.raises(ConversationNotFoundError):
            self.svc.delete_conversation(self.request, str(uuid.uuid4()))

    def test_delete_wrong_user(self):
        other = UserFactory()
        conv = Conversation.objects.create(user=other, title="Other")
        with pytest.raises(UnauthorizedAccessError):
            self.svc.delete_conversation(self.request, str(conv.id))


# ---------------------------------------------------------------------------
# update_conversation
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUpdateConversation:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_update_title(self):
        conv = Conversation.objects.create(user=self.user, title="Old")
        updated = self.svc.update_conversation(self.request, str(conv.id), title="New")
        assert updated.title == "New"

    def test_update_metadata(self):
        conv = Conversation.objects.create(
            user=self.user, title="Meta", metadata={"a": 1}
        )
        updated = self.svc.update_conversation(
            self.request, str(conv.id), metadata={"b": 2}
        )
        assert updated.metadata == {"a": 1, "b": 2}

    def test_update_both(self):
        conv = Conversation.objects.create(user=self.user, title="Both")
        updated = self.svc.update_conversation(
            self.request, str(conv.id), title="New", metadata={"key": "val"}
        )
        assert updated.title == "New"
        assert updated.metadata["key"] == "val"


# ---------------------------------------------------------------------------
# delete_all_user_conversations
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteAllConversations:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_delete_all(self):
        Conversation.objects.create(user=self.user, title="A")
        Conversation.objects.create(user=self.user, title="B")
        count = self.svc.delete_all_user_conversations(self.request)
        assert count == 2
        assert Conversation.objects.filter(user=self.user).count() == 0


# ---------------------------------------------------------------------------
# upload_file
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadFile:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_upload_success(self):
        f = SimpleUploadedFile("test.txt", b"hello", content_type="text/plain")
        result = self.svc.upload_file(self.request, f)
        assert result.filename == "test.txt"
        assert result.size == 5

    def test_upload_no_file(self):
        with pytest.raises(InvalidInputError, match="File is required"):
            self.svc.upload_file(self.request, None)

    def test_upload_empty_name(self):
        f = MagicMock()
        f.name = ""
        f.size = 10
        f.content_type = "text/plain"
        with pytest.raises(InvalidInputError, match="File is required"):
            self.svc.upload_file(self.request, f)

    def test_upload_too_large(self):
        # Default max is 50MB, create a mock that reports >50MB
        f = MagicMock()
        f.name = "big.txt"
        f.size = 100 * 1024 * 1024  # 100MB
        f.content_type = "text/plain"
        with pytest.raises(InvalidInputError, match="exceeds limit"):
            self.svc.upload_file(self.request, f)


# ---------------------------------------------------------------------------
# get_user_files
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetUserFiles:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_get_files(self):
        f = SimpleUploadedFile("a.txt", b"hello", content_type="text/plain")
        self.svc.upload_file(self.request, f)
        files = self.svc.get_user_files(self.request)
        assert files.count() == 1


# ---------------------------------------------------------------------------
# get_system_memory
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetSystemMemory:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)

    def test_no_memory(self):
        result = self.svc.get_system_memory(self.user)
        assert result is None

    def test_invalid_user(self):
        with pytest.raises(InvalidInputError, match="Valid user"):
            self.svc.get_system_memory("not_a_user")

    def test_cache_hit(self):
        mem = MagicMock()
        self.svc._cache_service.get.return_value = mem
        result = self.svc.get_system_memory(self.user)
        assert result is mem


# ---------------------------------------------------------------------------
# search_threads
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSearchThreads:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        Conversation.objects.create(user=self.user, title="Python debugging tips")
        Conversation.objects.create(user=self.user, title="JavaScript frameworks")
        Conversation.objects.create(
            user=self.user, title="Other", summary="Python is great"
        )

    def test_search_title_match(self):
        results = self.svc.search_threads(self.request, "Python")
        titles = [c.title for c in results]
        assert "Python debugging tips" in titles

    def test_search_summary_match(self):
        results = self.svc.search_threads(self.request, "Python")
        titles = [c.title for c in results]
        assert "Other" in titles

    def test_search_no_match(self):
        results = self.svc.search_threads(self.request, "zzzznonexistent")
        assert results.count() == 0

    def test_search_empty_query(self):
        with pytest.raises(InvalidInputError, match="required"):
            self.svc.search_threads(self.request, "")

    def test_search_relevance_order(self):
        """Exact title match should rank higher than summary match."""
        Conversation.objects.create(user=self.user, title="python")
        results = list(self.svc.search_threads(self.request, "python"))
        # Exact title match ("python") should be first
        assert results[0].title == "python"

    def test_search_isolates_users(self):
        other = UserFactory()
        Conversation.objects.create(user=other, title="Python secrets")
        results = self.svc.search_threads(self.request, "Python")
        for c in results:
            assert c.user_id == self.user.id
