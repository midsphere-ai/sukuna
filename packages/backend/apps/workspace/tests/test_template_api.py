"""Tests for project template API endpoints.

Covers:
- POST /{org_id} — create template (admin+)
- GET /{org_id} — list templates (member+)
- GET /{org_id}/{template_id} — template detail (member+)
- PATCH /{org_id}/{template_id} — update template (admin+)
- DELETE /{org_id}/{template_id} — delete template (admin+)
- POST /{org_id}/from-project/{project_id} — snapshot project as template (admin+)
- POST /api/v1/spaces/projects with template_id — create project from template
- Permission enforcement: viewer can list but not create/update/delete
- File size limits: 1 MB per file, 10 MB total
"""

import json
import uuid

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.spaces.models import (
    Project,
    ProjectTemplate,
    ProjectTemplateFile,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations/templates"
_SPACES = "/api/v1/spaces"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user():
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _delete(client, path):
    return client.delete(path)


def _create_org(name="Test Org"):
    owner, token = _make_user()
    org = Organization.objects.create(name=name)
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    return org, owner, token


def _add_member(org, role, invited_by=None):
    user, token = _make_user()
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


# =============================================================================
# CREATE TEMPLATE
# =============================================================================


class TestCreateTemplate:
    def test_admin_can_create(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}",
            {
                "name": "Starter Kit",
                "description": "A starter template",
                "custom_instructions": "Use Python 3.12",
                "icon": "rocket",
                "files": [
                    {
                        "file_name": "README.md",
                        "file_content": "# Hello",
                        "sort_order": 0,
                    },
                    {
                        "file_name": "main.py",
                        "file_content": "print('hi')",
                        "sort_order": 1,
                    },
                ],
            },
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["name"] == "Starter Kit"
        assert data["description"] == "A starter template"
        assert data["custom_instructions"] == "Use Python 3.12"
        assert data["icon"] == "rocket"
        assert len(data["files"]) == 2
        assert data["files"][0]["file_name"] == "README.md"

    def test_admin_member_can_create(self):
        org, owner, _ = _create_org()
        admin, token = _add_member(org, OrganizationRole.ADMIN)
        resp = _post(_client(token), f"{_BASE}/{org.pk}", {"name": "T"})
        assert resp.status_code == 201

    def test_member_cannot_create(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(_client(token), f"{_BASE}/{org.pk}", {"name": "T"})
        assert resp.status_code == 401

    def test_viewer_cannot_create(self):
        org, owner, _ = _create_org()
        viewer, token = _add_member(org, OrganizationRole.VIEWER)
        resp = _post(_client(token), f"{_BASE}/{org.pk}", {"name": "T"})
        assert resp.status_code == 401

    def test_non_member_cannot_create(self):
        org, owner, _ = _create_org()
        outsider, token = _make_user()
        resp = _post(_client(token), f"{_BASE}/{org.pk}", {"name": "T"})
        assert resp.status_code == 401

    def test_no_files_ok(self):
        org, owner, token = _create_org()
        resp = _post(_client(token), f"{_BASE}/{org.pk}", {"name": "Empty"})
        assert resp.status_code == 201
        assert resp.json()["files"] == []

    def test_file_over_1mb_rejected(self):
        org, owner, token = _create_org()
        big_content = "x" * (1 * 1024 * 1024 + 1)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}",
            {
                "name": "Big",
                "files": [{"file_name": "big.txt", "file_content": big_content}],
            },
        )
        assert resp.status_code == 413

    def test_total_files_over_10mb_rejected(self):
        org, owner, token = _create_org()
        # Use the model-level validation directly since Django's
        # DATA_UPLOAD_MAX_MEMORY_SIZE rejects large HTTP bodies first.
        from apps.workspace.template_api import TemplateFileIn, _validate_file_sizes

        files = [
            TemplateFileIn(file_name=f"f{i}.txt", file_content="x" * (1 * 1024 * 1024))
            for i in range(11)
        ]
        from ninja.errors import HttpError

        with pytest.raises(HttpError) as exc_info:
            _validate_file_sizes(files)
        assert exc_info.value.status_code == 413

    def test_org_not_found(self):
        _, _, token = _create_org()
        fake_id = str(uuid.uuid4())
        resp = _post(_client(token), f"{_BASE}/{fake_id}", {"name": "T"})
        assert resp.status_code == 404


# =============================================================================
# LIST TEMPLATES
# =============================================================================


class TestListTemplates:
    def test_member_can_list(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        ProjectTemplate.objects.create(organization=org, name="T1", created_by=owner)
        ProjectTemplate.objects.create(organization=org, name="T2", created_by=owner)
        resp = _client(token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_viewer_can_list(self):
        org, owner, _ = _create_org()
        viewer, token = _add_member(org, OrganizationRole.VIEWER)
        ProjectTemplate.objects.create(organization=org, name="T1", created_by=owner)
        resp = _client(token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 200

    def test_non_member_cannot_list(self):
        org, owner, _ = _create_org()
        outsider, token = _make_user()
        resp = _client(token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 401

    def test_empty_list(self):
        org, owner, token = _create_org()
        resp = _client(token).get(f"{_BASE}/{org.pk}")
        assert resp.status_code == 200
        assert resp.json() == []


# =============================================================================
# GET TEMPLATE DETAIL
# =============================================================================


class TestGetTemplate:
    def test_member_can_view(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="Detail", created_by=owner
        )
        ProjectTemplateFile.objects.create(
            template=tmpl, file_name="readme.md", file_content="# Hi", sort_order=0
        )
        resp = _client(token).get(f"{_BASE}/{org.pk}/{tmpl.pk}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail"
        assert len(data["files"]) == 1

    def test_template_not_found(self):
        org, owner, token = _create_org()
        fake_id = str(uuid.uuid4())
        resp = _client(token).get(f"{_BASE}/{org.pk}/{fake_id}")
        assert resp.status_code == 404

    def test_template_in_other_org_not_found(self):
        org1, owner1, token1 = _create_org("Org1")
        org2, owner2, _ = _create_org("Org2")
        tmpl = ProjectTemplate.objects.create(
            organization=org2, name="Foreign", created_by=owner2
        )
        resp = _client(token1).get(f"{_BASE}/{org1.pk}/{tmpl.pk}")
        assert resp.status_code == 404


# =============================================================================
# UPDATE TEMPLATE
# =============================================================================


class TestUpdateTemplate:
    def test_admin_can_update(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="Old", created_by=owner
        )
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/{tmpl.pk}",
            {
                "name": "New Name",
                "description": "Updated description",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "New Name"
        assert data["description"] == "Updated description"

    def test_update_replaces_files(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="T", created_by=owner
        )
        ProjectTemplateFile.objects.create(
            template=tmpl, file_name="old.txt", file_content="old"
        )
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/{tmpl.pk}",
            {
                "files": [
                    {"file_name": "new.txt", "file_content": "new", "sort_order": 0}
                ],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["files"]) == 1
        assert data["files"][0]["file_name"] == "new.txt"
        assert ProjectTemplateFile.objects.filter(template=tmpl).count() == 1

    def test_member_cannot_update(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="T", created_by=owner
        )
        resp = _patch(_client(token), f"{_BASE}/{org.pk}/{tmpl.pk}", {"name": "Nope"})
        assert resp.status_code == 401

    def test_partial_update_preserves_fields(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org,
            name="Original",
            description="Desc",
            custom_instructions="Instr",
            icon="star",
            created_by=owner,
        )
        resp = _patch(
            _client(token), f"{_BASE}/{org.pk}/{tmpl.pk}", {"name": "Changed"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Changed"
        assert data["description"] == "Desc"
        assert data["custom_instructions"] == "Instr"
        assert data["icon"] == "star"


# =============================================================================
# DELETE TEMPLATE
# =============================================================================


class TestDeleteTemplate:
    def test_admin_can_delete(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="Bye", created_by=owner
        )
        tmpl_id = str(tmpl.pk)
        resp = _delete(_client(token), f"{_BASE}/{org.pk}/{tmpl.pk}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True
        assert not ProjectTemplate.objects.filter(pk=tmpl_id).exists()

    def test_member_cannot_delete(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="T", created_by=owner
        )
        resp = _delete(_client(token), f"{_BASE}/{org.pk}/{tmpl.pk}")
        assert resp.status_code == 401

    def test_delete_cascades_files(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org, name="T", created_by=owner
        )
        ProjectTemplateFile.objects.create(
            template=tmpl, file_name="f.txt", file_content="x"
        )
        _delete(_client(token), f"{_BASE}/{org.pk}/{tmpl.pk}")
        assert ProjectTemplateFile.objects.count() == 0


# =============================================================================
# CREATE TEMPLATE FROM PROJECT
# =============================================================================


class TestCreateTemplateFromProject:
    def test_snapshot_project(self):
        org, owner, token = _create_org()
        project = Project.objects.create(
            title="My Project",
            description="Desc",
            custom_instructions="Be nice",
            icon="brain",
            user=owner,
            organization=org,
        )
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/from-project/{project.pk}",
            {},
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()
        assert data["name"] == "My Project"
        assert data["description"] == "Desc"
        assert data["custom_instructions"] == "Be nice"
        assert data["icon"] == "brain"

    def test_project_not_found(self):
        org, owner, token = _create_org()
        fake_id = str(uuid.uuid4())
        resp = _post(_client(token), f"{_BASE}/{org.pk}/from-project/{fake_id}", {})
        assert resp.status_code == 404

    def test_member_cannot_snapshot(self):
        org, owner, _ = _create_org()
        member, token = _add_member(org, OrganizationRole.MEMBER)
        project = Project.objects.create(
            title="P",
            description="",
            user=owner,
            organization=org,
        )
        resp = _post(_client(token), f"{_BASE}/{org.pk}/from-project/{project.pk}", {})
        assert resp.status_code == 401


# =============================================================================
# CREATE PROJECT FROM TEMPLATE
# =============================================================================


class TestCreateProjectFromTemplate:
    def test_creates_with_template_defaults(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org,
            name="Starter",
            custom_instructions="Use pytest",
            icon="rocket",
            created_by=owner,
        )
        ProjectTemplateFile.objects.create(
            template=tmpl,
            file_name="setup.py",
            file_content="# setup",
            sort_order=0,
        )
        resp = _post(
            _client(token),
            f"{_SPACES}/projects",
            {
                "title": "New Project",
                "description": "From template",
                "template_id": str(tmpl.pk),
            },
        )
        assert resp.status_code == 200, resp.json()
        project_id = resp.json()["project_id"]
        project = Project.objects.get(pk=project_id)
        assert project.custom_instructions == "Use pytest"
        assert project.icon == "rocket"
        # Template file was copied
        assert project.files.count() == 1
        assert project.files.first().filename == "setup.py"

    def test_explicit_instructions_override_template(self):
        org, owner, token = _create_org()
        tmpl = ProjectTemplate.objects.create(
            organization=org,
            name="Starter",
            custom_instructions="Template says this",
            created_by=owner,
        )
        resp = _post(
            _client(token),
            f"{_SPACES}/projects",
            {
                "title": "Override",
                "description": "Custom",
                "custom_instructions": "User says this",
                "template_id": str(tmpl.pk),
            },
        )
        assert resp.status_code == 200
        project = Project.objects.get(pk=resp.json()["project_id"])
        assert project.custom_instructions == "User says this"

    def test_invalid_template_id(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_SPACES}/projects",
            {
                "title": "Bad Template",
                "description": "Fail",
                "template_id": str(uuid.uuid4()),
            },
        )
        assert resp.status_code in (400, 422)

    def test_without_template_works(self):
        org, owner, token = _create_org()
        resp = _post(
            _client(token),
            f"{_SPACES}/projects",
            {
                "title": "Plain",
                "description": "No template",
            },
        )
        assert resp.status_code == 200
