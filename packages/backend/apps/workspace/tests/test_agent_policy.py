"""Tests for Org Agent Policy API and enforcement.

Covers:
- GET /{org_id}/agent-policy — read agent guardrails (admin+)
- PATCH /{org_id}/agent-policy — update agent guardrails (admin+)
- Tool filtering via filter_tools_for_policy
- Tool group expansion via _get_blocked_tool_names
- HITL flag injection via apply_agent_policy_to_metadata
- Personal project exemption (no org → no filtering)
- Policy change mid-run (applies on next run, not active)
- RBAC: viewers/members denied, admins+ allowed
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.agent_policy import (
    TOOL_GROUPS,
    apply_agent_policy_to_metadata,
    filter_tools_for_policy,
    get_hitl_tools,
    get_org_agent_policy,
)
from apps.workspace.models import (
    OrgAgentPolicy,
    Organization,
    OrganizationMembership,
    OrganizationRole,
)

pytestmark = pytest.mark.django_db

_BASE = "/api/v1/workspace/organizations"


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


def _get(client, path):
    return client.get(path)


def _create_org(name="Test Org"):
    owner, token = _make_user()
    resp = _post(_client(token), f"{_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
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
# GET AGENT POLICY
# =============================================================================


class TestGetAgentPolicy:
    def test_owner_can_read_default(self):
        org, owner, token = _create_org()
        resp = _get(_client(token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked_tools"] == []
        assert data["blocked_tool_groups"] == []
        assert data["require_hitl_for"] == []

    def test_admin_can_read(self):
        org, owner, owner_token = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _get(_client(admin_token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 200

    def test_member_denied(self):
        org, owner, owner_token = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _get(_client(member_token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 401

    def test_viewer_denied(self):
        org, owner, owner_token = _create_org()
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        resp = _get(_client(viewer_token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 401

    def test_nonmember_denied(self):
        org, owner, owner_token = _create_org()
        _, outsider_token = _make_user()
        resp = _get(_client(outsider_token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 401

    def test_read_with_policy_set(self):
        org, owner, token = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell", "browse"],
            blocked_tool_groups=["media_gen"],
            require_hitl_for=["web_search"],
        )
        resp = _get(_client(token), f"{_BASE}/{org.pk}/agent-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked_tools"] == ["shell", "browse"]
        assert data["blocked_tool_groups"] == ["media_gen"]
        assert data["require_hitl_for"] == ["web_search"]

    def test_not_found_org(self):
        _, _, token = _create_org()
        resp = _get(
            _client(token),
            f"{_BASE}/00000000-0000-0000-0000-000000000000/agent-policy",
        )
        assert resp.status_code == 404


# =============================================================================
# PATCH AGENT POLICY
# =============================================================================


class TestUpdateAgentPolicy:
    def test_owner_can_set_blocked_tools(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tools": ["shell", "browse"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked_tools"] == ["shell", "browse"]
        assert data["blocked_tool_groups"] == []
        assert data["require_hitl_for"] == []

    def test_admin_can_set_tool_groups(self):
        org, owner, owner_token = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tool_groups": ["file", "shell"]},
        )
        assert resp.status_code == 200
        assert resp.json()["blocked_tool_groups"] == ["file", "shell"]

    def test_member_denied(self):
        org, owner, owner_token = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tools": ["shell"]},
        )
        assert resp.status_code == 401

    def test_set_hitl_tools(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"require_hitl_for": ["shell", "web_search"]},
        )
        assert resp.status_code == 200
        assert resp.json()["require_hitl_for"] == ["shell", "web_search"]

    def test_partial_update_preserves_fields(self):
        org, owner, token = _create_org()
        # Set all fields
        _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {
                "blocked_tools": ["shell"],
                "blocked_tool_groups": ["media_gen"],
                "require_hitl_for": ["browse"],
            },
        )
        # Update only blocked_tools
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tools": ["shell", "web_search"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["blocked_tools"] == ["shell", "web_search"]
        assert data["blocked_tool_groups"] == ["media_gen"]
        assert data["require_hitl_for"] == ["browse"]

    def test_clear_blocked_tools(self):
        org, owner, token = _create_org()
        _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tools": ["shell"]},
        )
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/agent-policy",
            {"blocked_tools": []},
        )
        assert resp.status_code == 200
        assert resp.json()["blocked_tools"] == []


# =============================================================================
# TOOL FILTERING — filter_tools_for_policy
# =============================================================================


class _FakeConv:
    """Minimal conversation stub for policy checks."""

    def __init__(self, project=None):
        self.project = project


class _FakeProject:
    """Minimal project stub for policy checks."""

    def __init__(self, organization=None):
        self.organization = organization


class TestToolFiltering:
    def test_no_blocked_tools_passes_all(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(organization=org)
        addons = ["shell", "browse", "web_search"]
        result = filter_tools_for_policy(addons, policy)
        assert result == ["shell", "browse", "web_search"]

    def test_blocked_tools_removed(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell", "browse"],
        )
        addons = ["shell", "browse", "web_search", "read_file"]
        result = filter_tools_for_policy(addons, policy)
        assert result == ["web_search", "read_file"]

    def test_blocked_tool_group_expands(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tool_groups=["shell"],
        )
        shell_tools = TOOL_GROUPS["shell"]
        addons = shell_tools + ["web_search"]
        result = filter_tools_for_policy(addons, policy)
        assert result == ["web_search"]

    def test_mixed_individual_and_group_blocking(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["web_search"],
            blocked_tool_groups=["shell"],
        )
        addons = ["shell", "run_command", "web_search", "read_file"]
        result = filter_tools_for_policy(addons, policy)
        assert result == ["read_file"]

    def test_none_addons_returns_empty(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
        )
        assert filter_tools_for_policy(None, policy) == []

    def test_empty_addons_returns_empty(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(organization=org)
        assert filter_tools_for_policy([], policy) == []


# =============================================================================
# HITL FLAG INJECTION
# =============================================================================


class TestHitlInjection:
    def test_hitl_tools_returned(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            require_hitl_for=["shell", "web_search"],
        )
        assert get_hitl_tools(policy) == ["shell", "web_search"]

    def test_no_hitl_returns_empty(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(organization=org)
        assert get_hitl_tools(policy) == []


# =============================================================================
# apply_agent_policy_to_metadata
# =============================================================================


class TestApplyPolicyToMetadata:
    def test_personal_project_not_filtered(self):
        """No project → personal → no filtering."""
        conv = _FakeConv(project=None)
        metadata = {"addons": ["shell", "browse", "web_search"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["shell", "browse", "web_search"]
        assert "require_approval_tools" not in result

    def test_no_org_not_filtered(self):
        """Project without org → personal → no filtering."""
        conv = _FakeConv(project=_FakeProject(organization=None))
        metadata = {"addons": ["shell", "browse"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["shell", "browse"]

    def test_no_policy_not_filtered(self):
        """Org without agent policy → no filtering."""
        org, _, _ = _create_org()
        conv = _FakeConv(project=_FakeProject(organization=org))
        metadata = {"addons": ["shell", "browse"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["shell", "browse"]

    def test_blocked_tools_removed_from_metadata(self):
        org, _, _ = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        metadata = {"addons": ["shell", "browse", "web_search"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["browse", "web_search"]

    def test_hitl_flags_injected(self):
        org, _, _ = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            require_hitl_for=["shell", "web_search"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        metadata = {"addons": ["shell", "browse", "web_search"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["require_approval_tools"] == ["shell", "web_search"]

    def test_blocked_and_hitl_combined(self):
        org, _, _ = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["browse"],
            require_hitl_for=["shell"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        metadata = {"addons": ["shell", "browse", "web_search"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["shell", "web_search"]
        assert result["require_approval_tools"] == ["shell"]

    def test_blocked_group_removes_all_group_tools(self):
        org, _, _ = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tool_groups=["file"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        file_tools = TOOL_GROUPS["file"]
        metadata = {"addons": file_tools + ["web_search"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["web_search"]

    def test_metadata_without_addons_key(self):
        org, _, _ = _create_org()
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        metadata = {"files": []}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert "addons" not in result


# =============================================================================
# get_org_agent_policy
# =============================================================================


class TestGetOrgAgentPolicy:
    def test_no_project(self):
        conv = _FakeConv(project=None)
        assert get_org_agent_policy(conv) is None

    def test_no_org(self):
        conv = _FakeConv(project=_FakeProject(organization=None))
        assert get_org_agent_policy(conv) is None

    def test_no_policy_returns_none(self):
        org, _, _ = _create_org()
        conv = _FakeConv(project=_FakeProject(organization=org))
        assert get_org_agent_policy(conv) is None

    def test_returns_existing_policy(self):
        org, _, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = get_org_agent_policy(conv)
        assert result is not None
        assert result.pk == policy.pk


# =============================================================================
# POLICY CHANGE — applies on next run, not active
# =============================================================================


class TestPolicyChangeEdge:
    def test_policy_change_does_not_affect_cached_metadata(self):
        """Simulate: metadata built with no policy, then policy added.
        The already-built metadata is not retroactively changed."""
        org, _, _ = _create_org()
        conv = _FakeConv(project=_FakeProject(organization=org))

        # Build metadata before policy exists
        metadata = {"addons": ["shell", "browse"]}
        result1 = apply_agent_policy_to_metadata(dict(metadata), conv)
        assert result1["addons"] == ["shell", "browse"]

        # Now create policy
        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
        )
        # Re-fetch org to clear cache
        org = Organization.objects.get(pk=org.pk)
        conv2 = _FakeConv(project=_FakeProject(organization=org))

        # Next call reflects the new policy
        result2 = apply_agent_policy_to_metadata(dict(metadata), conv2)
        assert result2["addons"] == ["browse"]
