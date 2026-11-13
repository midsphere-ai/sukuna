"""Unit tests for ProjectsService business logic."""

import logging
import uuid
from unittest.mock import MagicMock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.spaces.errors import (
    ProjectFileNotFoundError,
    ProjectObjectNotFoundError,
    ProjectsServiceError,
)
from apps.spaces.models import Project
from apps.spaces.service import ProjectsService
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
    svc = ProjectsService.__new__(ProjectsService)
    svc._user_service = MagicMock()
    svc._cache_service = MagicMock()
    svc._cache_service.get.return_value = None
    svc._logger = logging.getLogger("test.projects")
    svc._service_kwargs = {}
    svc._get_authenticated_user = MagicMock(return_value=user)
    return svc


# ---------------------------------------------------------------------------
# _map_and_log_error
# ---------------------------------------------------------------------------
class TestProjectErrorMapping:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_known_error_passthrough(self):
        e = ProjectObjectNotFoundError("nope")
        assert self.svc._map_and_log_error(e, "ctx") is e

    def test_validation_error_maps_to_input(self):
        from django.core.exceptions import ValidationError

        e = ValidationError("bad")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, InvalidInputError)

    def test_unexpected_maps_to_projects_error(self):
        e = RuntimeError("boom")
        result = self.svc._map_and_log_error(e, "ctx")
        assert isinstance(result, ProjectsServiceError)


# ---------------------------------------------------------------------------
# _validate_project_fields
# ---------------------------------------------------------------------------
class TestValidateProjectFields:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_valid(self):
        # Should not raise
        self.svc._validate_project_fields("Title", "Description")

    def test_title_too_long(self):
        with pytest.raises(InvalidInputError, match="Title"):
            self.svc._validate_project_fields("x" * 200, "Description")

    def test_description_too_long(self):
        with pytest.raises(InvalidInputError, match="Description"):
            self.svc._validate_project_fields("Title", "x" * 600)

    def test_empty_title(self):
        with pytest.raises(InvalidInputError):
            self.svc._validate_project_fields("", "Description")

    def test_none_title(self):
        with pytest.raises(InvalidInputError):
            self.svc._validate_project_fields(None, "Description")


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateProject:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)

    def test_success(self):
        result = self.svc.create_project(self.request, "My Project", "A description")
        assert result.project_id is not None
        assert Project.objects.filter(user=self.user).count() == 1

    def test_invalid_title(self):
        with pytest.raises(InvalidInputError):
            self.svc.create_project(self.request, "", "desc")


# ---------------------------------------------------------------------------
# modify_project
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestModifyProject:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "Original", "Original desc")
        self.project_id = str(result.project_id)

    def test_modify_title(self):
        data = MagicMock()
        data.title = "Updated"
        data.description = None
        data.icon = None
        data.custom_instructions = None
        result = self.svc.modify_project(self.request, self.project_id, data)
        assert result.modified is True

    def test_no_changes(self):
        data = MagicMock()
        data.title = None
        data.description = None
        data.icon = None
        data.custom_instructions = None
        result = self.svc.modify_project(self.request, self.project_id, data)
        assert result.modified is False

    def test_nonexistent_project(self):
        fake_id = str(uuid.uuid4())
        data = MagicMock()
        data.title = "X"
        data.description = None
        data.icon = None
        data.custom_instructions = None
        with pytest.raises(ProjectObjectNotFoundError):
            self.svc.modify_project(self.request, fake_id, data)

    def test_wrong_user(self):
        other = UserFactory()
        svc2 = _make_service(other)
        req2 = _make_request(other)
        data = MagicMock()
        data.title = "Hack"
        data.description = None
        data.icon = None
        data.custom_instructions = None
        with pytest.raises(UnauthorizedAccessError):
            svc2.modify_project(req2, self.project_id, data)


# ---------------------------------------------------------------------------
# delete_project
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteProject:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "ToDelete", "Will be deleted")
        self.project_id = str(result.project_id)

    def test_delete_success(self):
        result = self.svc.delete_project(self.request, self.project_id)
        assert result.deleted is True
        assert Project.objects.filter(id=self.project_id).count() == 0

    def test_delete_nonexistent(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(ProjectObjectNotFoundError):
            self.svc.delete_project(self.request, fake_id)


# ---------------------------------------------------------------------------
# get_project_info
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetProjectInfo:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "Info", "Info desc")
        self.project_id = str(result.project_id)

    def test_get_info(self):
        project = self.svc.get_project_info(self.request, self.project_id)
        assert project.title == "Info"

    def test_cache_hit(self):
        project = Project.objects.get(id=self.project_id)
        self.svc._cache_service.get.return_value = project
        result = self.svc.get_project_info(self.request, self.project_id)
        assert result.id == project.id

    def test_nonexistent(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(ProjectObjectNotFoundError):
            self.svc.get_project_info(self.request, fake_id)


# ---------------------------------------------------------------------------
# get_all_user_projects
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestGetAllUserProjects:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        self.svc.create_project(self.request, "P1", "D1")
        self.svc.create_project(self.request, "P2", "D2")

    def test_get_all(self):
        projects = self.svc.get_all_user_projects(self.request)
        assert projects.count() == 2

    def test_annotated_with_conversation_count(self):
        projects = self.svc.get_all_user_projects(self.request)
        for p in projects:
            assert hasattr(p, "conversation_count")


# ---------------------------------------------------------------------------
# _validate_file
# ---------------------------------------------------------------------------
class TestValidateFile:
    def setup_method(self):
        self.svc = _make_service(MagicMock())

    def test_valid_file(self):
        f = SimpleUploadedFile("doc.pdf", b"data", content_type="application/pdf")
        # Should not raise
        self.svc._validate_file(f)

    def test_file_too_large(self):
        f = MagicMock()
        f.size = 100 * 1024 * 1024  # 100MB
        f.content_type = "text/plain"
        f.name = "big.txt"
        with pytest.raises(InvalidInputError, match="size exceeds"):
            self.svc._validate_file(f)

    def test_disallowed_mime_type(self):
        f = SimpleUploadedFile(
            "script.sh", b"#!/bin/bash", content_type="application/x-sh"
        )
        with pytest.raises(InvalidInputError, match="not allowed"):
            self.svc._validate_file(f)


# ---------------------------------------------------------------------------
# upload_project_file
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUploadProjectFile:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "Files", "With files")
        self.project_id = str(result.project_id)

    def test_upload_success(self):
        f = SimpleUploadedFile("readme.txt", b"hello", content_type="text/plain")
        result = self.svc.upload_project_file(self.request, self.project_id, f)
        assert result.filename == "readme.txt"
        assert result.size_bytes == 5

    def test_upload_to_nonexistent_project(self):
        f = SimpleUploadedFile("readme.txt", b"hello", content_type="text/plain")
        with pytest.raises(ProjectObjectNotFoundError):
            self.svc.upload_project_file(self.request, str(uuid.uuid4()), f)


# ---------------------------------------------------------------------------
# list_project_files
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestListProjectFiles:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "ListFiles", "List test")
        self.project_id = str(result.project_id)

    def test_list_empty(self):
        files = self.svc.list_project_files(self.request, self.project_id)
        assert files.count() == 0

    def test_list_with_files(self):
        f = SimpleUploadedFile("a.txt", b"aaa", content_type="text/plain")
        self.svc.upload_project_file(self.request, self.project_id, f)
        files = self.svc.list_project_files(self.request, self.project_id)
        assert files.count() == 1


# ---------------------------------------------------------------------------
# delete_project_file
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDeleteProjectFile:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.user = UserFactory()
        self.svc = _make_service(self.user)
        self.request = _make_request(self.user)
        result = self.svc.create_project(self.request, "DelFile", "Del test")
        self.project_id = str(result.project_id)

    def test_delete_success(self):
        f = SimpleUploadedFile("del.txt", b"bye", content_type="text/plain")
        upload_result = self.svc.upload_project_file(self.request, self.project_id, f)
        result = self.svc.delete_project_file(
            self.request, self.project_id, upload_result.file_id
        )
        assert result.deleted is True

    def test_delete_nonexistent_file(self):
        fake_id = str(uuid.uuid4())
        with pytest.raises(ProjectFileNotFoundError):
            self.svc.delete_project_file(self.request, self.project_id, fake_id)
