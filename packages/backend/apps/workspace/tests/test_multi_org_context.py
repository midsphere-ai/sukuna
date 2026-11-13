"""Tests for US-037: Multi-org context — org switcher, scoped queries, default org."""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.models import UserSettings
from apps.users.tests.factories import UserFactory
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_WS = "/api/v1/workspace"


# ── Fixtures & Helpers ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user():
    """Create a user with token."""
    user = UserFactory()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _create_org(name, slug, owner):
    org = Organization.objects.create(name=name, slug=slug)
    OrganizationMembership.objects.create(
        organization=org, user=owner, role=OrganizationRole.OWNER
    )
    return org


# ── Switch Org Tests ────────────────────────────────────────────────────────


class TestSwitchOrg:
    """Tests for POST /api/v1/workspace/switch-org"""

    def test_switch_to_org(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        resp = _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})
        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_id"] == str(org.pk)
        assert data["organization_name"] == "Acme"
        assert data["organization_slug"] == "acme"
        assert data["your_role"] == OrganizationRole.OWNER

        # Verify persisted
        settings = UserSettings.objects.get(user=user)
        assert settings.last_active_org_id == org.pk

    def test_switch_to_personal(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        # First switch to org
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        # Switch to personal
        resp = _post(c, f"{_WS}/switch-org", {"organization_id": None})
        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_id"] is None
        assert data["organization_name"] is None

        settings = UserSettings.objects.get(user=user)
        assert settings.last_active_org is None

    def test_switch_to_nonexistent_org(self):
        user, token = _make_user()
        c = _client(token)

        resp = _post(
            c,
            f"{_WS}/switch-org",
            {"organization_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert resp.status_code == 404

    def test_switch_to_org_not_a_member(self):
        user, token = _make_user()
        other_user, _ = _make_user()
        org = _create_org("Other Org", "other-org", other_user)
        c = _client(token)

        resp = _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})
        assert resp.status_code == 403


# ── Active Org Tests ────────────────────────────────────────────────────────


class TestActiveOrg:
    """Tests for GET /api/v1/workspace/active-org"""

    def test_default_is_personal(self):
        user, token = _make_user()
        c = _client(token)

        resp = c.get(f"{_WS}/active-org")
        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_id"] is None

    def test_returns_active_org_after_switch(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        resp = c.get(f"{_WS}/active-org")
        assert resp.status_code == 200
        data = resp.json()
        assert data["organization_id"] == str(org.pk)
        assert data["organization_name"] == "Acme"

    def test_resets_if_removed_from_org(self):
        user, token = _make_user()
        org_owner, _ = _make_user()
        org = _create_org("Acme", "acme", org_owner)
        membership = OrganizationMembership.objects.create(
            organization=org, user=user, role=OrganizationRole.MEMBER
        )
        c = _client(token)

        # Switch to org
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        # Remove user from org
        membership.delete()

        # Active org should reset to personal
        resp = c.get(f"{_WS}/active-org")
        data = resp.json()
        assert data["organization_id"] is None

    def test_persists_across_sessions(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        # New client with same token — simulates new session
        c2 = _client(token)
        resp = c2.get(f"{_WS}/active-org")
        data = resp.json()
        assert data["organization_id"] == str(org.pk)


# ── Scoped Project Listing Tests ────────────────────────────────────────────


class TestScopedProjectListing:
    """Tests for org-scoped GET /api/v1/spaces/projects"""

    def test_personal_space_shows_personal_projects(self):
        user, token = _make_user()
        c = _client(token)

        from apps.spaces.models import Project

        Project.objects.create(title="Personal Project", description="desc", user=user)

        resp = c.get("/api/v1/spaces/projects")
        assert resp.status_code == 200
        data = resp.json()
        titles = [p["title"] for p in data["items"]]
        assert "Personal Project" in titles

    def test_org_context_shows_org_projects_only(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        from apps.spaces.models import Project

        Project.objects.create(title="Personal Project", description="desc", user=user)
        Project.objects.create(
            title="Org Project", description="desc", user=user, organization=org
        )

        # Switch to org context
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        resp = c.get("/api/v1/spaces/projects")
        data = resp.json()
        titles = [p["title"] for p in data["items"]]
        assert "Org Project" in titles
        assert "Personal Project" not in titles

    def test_switching_back_to_personal_hides_org_projects(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        from apps.spaces.models import Project

        Project.objects.create(title="Personal Project", description="desc", user=user)
        Project.objects.create(
            title="Org Project", description="desc", user=user, organization=org
        )

        # Switch to org then back to personal
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})
        _post(c, f"{_WS}/switch-org", {"organization_id": None})

        resp = c.get("/api/v1/spaces/projects")
        data = resp.json()
        titles = [p["title"] for p in data["items"]]
        assert "Personal Project" in titles
        assert "Org Project" not in titles

    def test_cross_org_isolation(self):
        user, token = _make_user()
        org_a = _create_org("Org A", "org-a", user)
        org_b = _create_org("Org B", "org-b", user)
        c = _client(token)

        from apps.spaces.models import Project

        Project.objects.create(
            title="Org A Project", description="desc", user=user, organization=org_a
        )
        Project.objects.create(
            title="Org B Project", description="desc", user=user, organization=org_b
        )

        # Switch to Org A
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org_a.pk)})
        resp = c.get("/api/v1/spaces/projects")
        data = resp.json()
        titles = [p["title"] for p in data["items"]]
        assert "Org A Project" in titles
        assert "Org B Project" not in titles


# ── Scoped Conversation Listing Tests ───────────────────────────────────────


class TestScopedConversationListing:
    """Tests for org-scoped conversation listing."""

    def test_personal_space_shows_personal_conversations(self):
        user, token = _make_user()
        c = _client(token)

        from apps.spaces.models import Project
        from apps.storage.models import Conversation

        personal_project = Project.objects.create(
            title="Personal", description="desc", user=user
        )
        Conversation.objects.create(
            user=user, project=personal_project, title="Personal Conv"
        )
        Conversation.objects.create(user=user, title="No-project Conv")

        resp = c.get("/api/v1/memory/conversations")
        data = resp.json()
        titles = [conv["title"] for conv in data["items"]]
        assert "Personal Conv" in titles
        assert "No-project Conv" in titles

    def test_org_context_shows_org_conversations_only(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        from apps.spaces.models import Project
        from apps.storage.models import Conversation

        personal_project = Project.objects.create(
            title="Personal", description="desc", user=user
        )
        org_project = Project.objects.create(
            title="Org", description="desc", user=user, organization=org
        )
        Conversation.objects.create(
            user=user, project=personal_project, title="Personal Conv"
        )
        Conversation.objects.create(user=user, project=org_project, title="Org Conv")
        Conversation.objects.create(user=user, title="No-project Conv")

        # Switch to org context
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        resp = c.get("/api/v1/memory/conversations")
        data = resp.json()
        titles = [conv["title"] for conv in data["items"]]
        assert "Org Conv" in titles
        assert "Personal Conv" not in titles
        assert "No-project Conv" not in titles


# ── Auto-Assign Org on Project Creation ─────────────────────────────────────


class TestAutoAssignOrg:
    """Tests for auto-assigning active org when creating projects."""

    def test_creates_personal_project_in_personal_space(self):
        user, token = _make_user()
        c = _client(token)

        resp = _post(
            c,
            "/api/v1/spaces/projects",
            {"title": "New Project", "description": "Test"},
        )
        assert resp.status_code == 200
        from apps.spaces.models import Project

        project = Project.objects.get(pk=resp.json()["project_id"])
        assert project.organization is None

    def test_auto_assigns_org_in_org_context(self):
        user, token = _make_user()
        org = _create_org("Acme", "acme", user)
        c = _client(token)

        # Switch to org context
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org.pk)})

        resp = _post(
            c,
            "/api/v1/spaces/projects",
            {"title": "Org Project", "description": "Test"},
        )
        assert resp.status_code == 200
        from apps.spaces.models import Project

        project = Project.objects.get(pk=resp.json()["project_id"])
        assert project.organization_id == org.pk

    def test_explicit_org_id_overrides_active_org(self):
        user, token = _make_user()
        org_a = _create_org("Org A", "org-a", user)
        org_b = _create_org("Org B", "org-b", user)
        c = _client(token)

        # Switch to Org A
        _post(c, f"{_WS}/switch-org", {"organization_id": str(org_a.pk)})

        # Create project with explicit Org B
        resp = _post(
            c,
            "/api/v1/spaces/projects",
            {
                "title": "Explicit Org Project",
                "description": "Test",
                "organization_id": str(org_b.pk),
            },
        )
        assert resp.status_code == 200
        from apps.spaces.models import Project

        project = Project.objects.get(pk=resp.json()["project_id"])
        assert project.organization_id == org_b.pk


# ── SecurityPolicyMiddleware: still global ──────────────────────────────────


class TestSecurityPolicyStillGlobal:
    """Verify SecurityPolicyMiddleware uses most-restrictive across ALL orgs."""

    def test_security_policy_not_scoped_to_active_org(self):
        """get_effective_policy should query all user orgs, not just the active one."""
        user, _ = _make_user()
        org_strict = _create_org("Strict", "strict", user)
        org_lax = _create_org("Lax", "lax", user)

        # Strict org: short timeout + mfa required
        org_strict.session_timeout_minutes = 15
        org_strict.mfa_required = True
        org_strict.save()

        # Lax org: long timeout
        org_lax.session_timeout_minutes = 1440
        org_lax.mfa_required = False
        org_lax.save()

        # Switch to lax org
        settings, _ = UserSettings.objects.get_or_create(user=user)
        settings.last_active_org = org_lax
        settings.save()

        from apps.compliance.security_middleware import get_effective_policy

        mfa_required, timeout, max_sessions, sso_enforced = get_effective_policy(user)
        # Should be most restrictive ACROSS ALL orgs
        assert mfa_required is True  # from strict org
        assert timeout == 15  # from strict org
