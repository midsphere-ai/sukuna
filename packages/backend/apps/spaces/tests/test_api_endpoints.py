"""
Integration tests for spaces app API endpoints.

US-060: Tests for spaces API endpoints with focus on:
- POST   /spaces/projects               (create project)
- GET    /spaces/projects               (list projects)
- GET    /spaces/projects/{id}          (get project details)
- PATCH  /spaces/projects/{id}          (update project)
- DELETE /spaces/projects/{id}          (delete project)
- POST   /spaces/projects/{id}/files    (upload file)
- GET    /spaces/projects/{id}/files    (list files)
- DELETE /spaces/projects/{id}/files/{fid} (delete file)
- GET    /spaces/projects/{id}/sandbox-status

Covers:
- Authentication and authorization
- Project CRUD
- File management
- Authorization (cross-user access)
- Error cases
"""

import json

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.spaces.models import Project, ProjectFile
from apps.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

_P = "/api/v1/spaces"


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture(autouse=True)
def _clear_rate_limit_cache():
    cache.clear()
    yield
    cache.clear()


# =============================================================================
# HELPERS
# =============================================================================


def _setup_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _setup_project(user, title="Test Project"):
    return Project.objects.create(
        title=title,
        description="Test description",
        user=user,
    )


def _auth_client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


# =============================================================================
# AUTHENTICATION TESTS
# =============================================================================


class TestSpacesAuthentication:
    """Verify auth on all spaces endpoints."""

    AUTHENTICATED_ENDPOINTS = [
        ("post", f"{_P}/projects"),
        ("get", f"{_P}/projects"),
    ]

    def _make_request(self, client, method, path, body=None):
        fn = getattr(client, method)
        kwargs = {"content_type": "application/json"}
        if body:
            kwargs["data"] = json.dumps(body)
        return fn(path, **kwargs)

    def test_no_token_returns_401(self):
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            resp = self._make_request(Client(), method, path)
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )

    def test_invalid_token_returns_401(self):
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            client = _auth_client("invalid-token")
            resp = self._make_request(client, method, path)
            assert resp.status_code == 401, (
                f"{method.upper()} {path} expected 401, got {resp.status_code}"
            )

    def test_valid_token_does_not_return_401(self):
        _, token = _setup_user()
        for method, path in self.AUTHENTICATED_ENDPOINTS:
            cache.clear()
            client = _auth_client(token)
            resp = self._make_request(client, method, path)
            assert resp.status_code != 401, (
                f"{method.upper()} {path} returned 401 with valid token"
            )


# =============================================================================
# PROJECT CRUD
# =============================================================================


class TestCreateProject:
    """Test POST /spaces/projects."""

    def test_create_project(self):
        _, token = _setup_user()
        resp = _auth_client(token).post(
            f"{_P}/projects",
            data=json.dumps(
                {
                    "title": "My Project",
                    "description": "A test project",
                    "icon": "rocket",
                    "custom_instructions": "Be helpful",
                }
            ),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data or "id" in data

    def test_create_project_requires_description(self):
        """Creating a project without a description returns 400."""
        _, token = _setup_user()
        resp = _auth_client(token).post(
            f"{_P}/projects",
            data=json.dumps({"title": "Minimal", "description": ""}),
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestListProjects:
    """Test GET /spaces/projects."""

    def test_list_projects(self):
        user, token = _setup_user()
        _setup_project(user, "P1")
        _setup_project(user, "P2")

        resp = _auth_client(token).get(f"{_P}/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert len(data["items"]) == 2

    def test_list_projects_empty(self):
        _, token = _setup_user()
        resp = _auth_client(token).get(f"{_P}/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []

    def test_only_own_projects(self):
        user1, token1 = _setup_user()
        user2, _ = _setup_user()
        _setup_project(user1, "User1 Project")
        _setup_project(user2, "User2 Project")

        resp = _auth_client(token1).get(f"{_P}/projects")
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["title"] == "User1 Project"


class TestGetProject:
    """Test GET /spaces/projects/{project_id}."""

    def test_get_project_details(self):
        user, token = _setup_user()
        project = _setup_project(user)

        resp = _auth_client(token).get(f"{_P}/projects/{project.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Project"

    def test_get_nonexistent_project(self):
        _, token = _setup_user()
        fake_id = "nonexistent-id-12345"
        resp = _auth_client(token).get(f"{_P}/projects/{fake_id}")
        assert resp.status_code in (400, 404, 422)

    def test_cannot_access_other_users_project(self):
        user1, _ = _setup_user()
        project = _setup_project(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).get(f"{_P}/projects/{project.id}")
        assert resp.status_code in (401, 403, 404)


class TestUpdateProject:
    """Test PATCH /spaces/projects/{project_id}."""

    def test_update_project(self):
        user, token = _setup_user()
        project = _setup_project(user)

        resp = _auth_client(token).patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Updated Title"}),
            content_type="application/json",
        )
        assert resp.status_code == 200

    def test_cannot_update_other_users_project(self):
        user1, _ = _setup_user()
        project = _setup_project(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).patch(
            f"{_P}/projects/{project.id}",
            data=json.dumps({"title": "Hacked"}),
            content_type="application/json",
        )
        assert resp.status_code in (401, 403, 404)


class TestDeleteProject:
    """Test DELETE /spaces/projects/{project_id}."""

    def test_delete_project(self):
        user, token = _setup_user()
        project = _setup_project(user)

        resp = _auth_client(token).delete(f"{_P}/projects/{project.id}")
        assert resp.status_code == 200
        assert not Project.objects.filter(id=project.id).exists()

    def test_cannot_delete_other_users_project(self):
        user1, _ = _setup_user()
        project = _setup_project(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).delete(f"{_P}/projects/{project.id}")
        assert resp.status_code in (401, 403, 404)
        # Project should still exist
        assert Project.objects.filter(id=project.id).exists()


# =============================================================================
# PROJECT FILES
# =============================================================================


class TestProjectFiles:
    """Test project file management endpoints."""

    def test_list_project_files_empty(self):
        user, token = _setup_user()
        project = _setup_project(user)

        resp = _auth_client(token).get(f"{_P}/projects/{project.id}/files")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    def test_upload_project_file(self):
        user, token = _setup_user()
        project = _setup_project(user)

        file = SimpleUploadedFile("test.txt", b"Hello world", content_type="text/plain")
        client = _auth_client(token)
        resp = client.post(
            f"{_P}/projects/{project.id}/files",
            data={"file": file},
        )
        assert resp.status_code == 200

    def test_delete_project_file(self):
        user, token = _setup_user()
        project = _setup_project(user)
        pf = ProjectFile.objects.create(
            project=project,
            filename="test.txt",
            file_path="/home/user/workspace/test.txt",
            size_bytes=100,
        )

        resp = _auth_client(token).delete(f"{_P}/projects/{project.id}/files/{pf.id}")
        assert resp.status_code == 200
        assert not ProjectFile.objects.filter(id=pf.id).exists()

    def test_cannot_access_other_users_project_files(self):
        user1, _ = _setup_user()
        project = _setup_project(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).get(f"{_P}/projects/{project.id}/files")
        assert resp.status_code in (401, 403, 404)


# =============================================================================
# SANDBOX STATUS
# =============================================================================


class TestSandboxStatus:
    """Test GET /spaces/projects/{id}/sandbox-status."""

    def test_sandbox_not_busy(self):
        user, token = _setup_user()
        project = _setup_project(user)

        resp = _auth_client(token).get(f"{_P}/projects/{project.id}/sandbox-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["busy"] is False

    def test_cannot_check_other_users_sandbox(self):
        user1, _ = _setup_user()
        project = _setup_project(user1)

        user2 = UserFactory()
        token2 = Token.objects.create(user=user2).key

        resp = _auth_client(token2).get(f"{_P}/projects/{project.id}/sandbox-status")
        assert resp.status_code == 404
