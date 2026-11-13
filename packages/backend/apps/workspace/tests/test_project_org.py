"""Tests for the Project ↔ Organization relationship."""

import pytest

from apps.spaces.models import Project
from apps.users.tests.factories import UserFactory
from apps.workspace.models import Organization


@pytest.mark.django_db
class TestProjectOrganizationFK:
    def test_project_without_org(self):
        user = UserFactory()
        project = Project.objects.create(title="Personal", user=user)
        assert project.organization is None

    def test_project_with_org(self):
        user = UserFactory()
        org = Organization.objects.create(name="Acme")
        project = Project.objects.create(
            title="Team Project", user=user, organization=org
        )
        assert project.organization == org

    def test_org_projects_reverse_relation(self):
        user = UserFactory()
        org = Organization.objects.create(name="Acme")
        p1 = Project.objects.create(title="P1", user=user, organization=org)
        p2 = Project.objects.create(title="P2", user=user, organization=org)
        Project.objects.create(title="Personal", user=user)
        assert set(org.projects.all()) == {p1, p2}

    def test_cascade_on_org_delete(self):
        user = UserFactory()
        org = Organization.objects.create(name="Acme")
        org_pk = org.pk
        Project.objects.create(title="Team", user=user, organization=org)
        org.delete()
        assert Project.objects.filter(organization_id=org_pk).count() == 0

    def test_project_survives_when_no_org(self):
        user = UserFactory()
        project = Project.objects.create(title="Personal", user=user)
        assert Project.objects.filter(pk=project.pk).exists()
