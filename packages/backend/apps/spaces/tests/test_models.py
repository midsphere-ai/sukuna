"""Unit tests for spaces app models — Project, ProjectFile, and ProjectManager."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.spaces.models import Project, ProjectFile
from apps.users.tests.factories import UserFactory


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestProject:
    def test_str(self):
        user = UserFactory(name="Alice")
        project = Project.objects.create(title="My Project", user=user)
        assert "Alice" in str(project)
        assert "My Project" in str(project)

    def test_is_owned_by_true(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        assert project.is_owned_by(user) is True

    def test_is_owned_by_false(self):
        user = UserFactory()
        other = UserFactory()
        project = Project.objects.create(title="P", user=user)
        assert project.is_owned_by(other) is False

    def test_update_details(self):
        user = UserFactory()
        project = Project.objects.create(title="Old", description="Old desc", user=user)
        project.update_details(
            "New", "New desc", icon="rocket", custom_instructions="Do X"
        )
        project.refresh_from_db()
        assert project.title == "New"
        assert project.description == "New desc"
        assert project.icon == "rocket"
        assert project.custom_instructions == "Do X"

    def test_update_details_partial_kwargs(self):
        user = UserFactory()
        project = Project.objects.create(
            title="T", description="D", icon="star", user=user
        )
        project.update_details("T2", "D2")
        project.refresh_from_db()
        assert project.title == "T2"
        assert project.icon == "star"  # unchanged

    def test_defaults(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        assert project.description == ""
        assert project.icon == ""
        assert project.custom_instructions == ""
        assert project.sandbox is None

    def test_cascade_delete(self):
        user = UserFactory()
        Project.objects.create(title="P", user=user)
        user.delete()
        assert Project.objects.count() == 0

    def test_has_uuid_pk(self):
        import uuid

        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        assert isinstance(project.id, uuid.UUID)

    def test_short_id(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        short = project.short_id
        assert isinstance(short, str)
        assert len(short) > 0

    def test_get_by_short_id(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        found = Project.get_by_short_id(project.short_id)
        assert found.id == project.id


# ---------------------------------------------------------------------------
# ProjectManager
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestProjectManager:
    def test_for_user(self):
        user = UserFactory()
        other = UserFactory()
        Project.objects.create(title="A", user=user)
        Project.objects.create(title="B", user=user)
        Project.objects.create(title="C", user=other)
        projects = Project.objects.for_user(user)
        assert projects.count() == 2

    def test_for_user_ordering(self):
        user = UserFactory()
        p1 = Project.objects.create(title="First", user=user)
        p2 = Project.objects.create(title="Second", user=user)
        projects = list(Project.objects.for_user(user))
        assert projects[0] == p2  # newest first

    def test_get_by_uuid(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        found = Project.objects.get_by_uuid(project.id)
        assert found == project

    def test_get_by_uuid_not_found(self):
        import uuid

        found = Project.objects.get_by_uuid(uuid.uuid4())
        assert found is None

    def test_create_project(self):
        user = UserFactory()
        project = Project.objects.create_project(
            title="New",
            description="Desc",
            user=user,
            icon="code",
        )
        assert project.title == "New"
        assert project.description == "Desc"
        assert project.icon == "code"
        assert project.user == user
        assert project.pk is not None


# ---------------------------------------------------------------------------
# ProjectFile
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestProjectFile:
    def test_str(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        pf = ProjectFile.objects.create(
            project=project,
            filename="readme.md",
            file_path="/home/user/workspace/readme.md",
        )
        assert "readme.md" in str(pf)

    def test_defaults(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        pf = ProjectFile.objects.create(
            project=project,
            filename="test.txt",
            file_path="/home/user/workspace/test.txt",
        )
        assert pf.mime_type == ""
        assert pf.size_bytes == 0

    def test_ordering(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        f1 = ProjectFile.objects.create(
            project=project, filename="b.txt", file_path="/b"
        )
        f2 = ProjectFile.objects.create(
            project=project, filename="a.txt", file_path="/a"
        )
        files = list(ProjectFile.objects.all())
        assert files[0] == f2  # alphabetical by filename

    def test_cascade_delete_project(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        ProjectFile.objects.create(project=project, filename="f.txt", file_path="/f")
        project.delete()
        assert ProjectFile.objects.count() == 0

    def test_has_uuid_pk(self):
        import uuid

        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        pf = ProjectFile.objects.create(
            project=project, filename="x.py", file_path="/x"
        )
        assert isinstance(pf.id, uuid.UUID)

    def test_file_upload(self):
        user = UserFactory()
        project = Project.objects.create(title="P", user=user)
        uploaded = SimpleUploadedFile(
            "hello.txt", b"Hello World", content_type="text/plain"
        )
        pf = ProjectFile.objects.create(
            project=project,
            filename="hello.txt",
            file_path="/home/user/workspace/hello.txt",
            file=uploaded,
            mime_type="text/plain",
            size_bytes=11,
        )
        assert pf.file.name != ""
        assert pf.size_bytes == 11
