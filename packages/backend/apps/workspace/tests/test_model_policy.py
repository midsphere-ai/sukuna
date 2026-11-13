"""Tests for Org Model Policy API and enforcement.

Covers:
- GET /{org_id}/model-policy — read model restrictions (admin+)
- PATCH /{org_id}/model-policy — update model restrictions (admin+)
- Model enforcement via check_org_model_policy
- Provider enforcement via check_org_model_policy
- BYOM blocking via should_block_byom
- Empty policy (allow all)
- Policy change mid-run (active runs unaffected)
- RBAC: viewers/members denied, admins+ allowed
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.model_policy import check_org_model_policy, should_block_byom
from apps.workspace.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgModelPolicy,
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
# GET MODEL POLICY
# =============================================================================


class TestGetModelPolicy:
    def test_owner_can_read_default(self):
        org, owner, token = _create_org()
        resp = _get(_client(token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed_models"] == []
        assert data["allowed_providers"] == []
        assert data["block_byom"] is False

    def test_admin_can_read(self):
        org, owner, owner_token = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _get(_client(admin_token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 200

    def test_member_denied(self):
        org, owner, owner_token = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _get(_client(member_token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 401

    def test_viewer_denied(self):
        org, owner, owner_token = _create_org()
        _, viewer_token = _add_member(org, OrganizationRole.VIEWER)
        resp = _get(_client(viewer_token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 401

    def test_nonmember_denied(self):
        org, owner, owner_token = _create_org()
        _, outsider_token = _make_user()
        resp = _get(_client(outsider_token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 401

    def test_read_with_policy_set(self):
        org, owner, token = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4", "gpt-4o"],
            allowed_providers=["anthropic", "openai"],
            block_byom=True,
        )
        resp = _get(_client(token), f"{_BASE}/{org.pk}/model-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed_models"] == ["claude-sonnet-4", "gpt-4o"]
        assert data["allowed_providers"] == ["anthropic", "openai"]
        assert data["block_byom"] is True

    def test_not_found_org(self):
        _, _, token = _create_org()
        resp = _get(
            _client(token),
            f"{_BASE}/00000000-0000-0000-0000-000000000000/model-policy",
        )
        assert resp.status_code == 404


# =============================================================================
# PATCH MODEL POLICY
# =============================================================================


class TestUpdateModelPolicy:
    def test_owner_can_set_models(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {"allowed_models": ["claude-sonnet-4"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed_models"] == ["claude-sonnet-4"]
        assert data["allowed_providers"] == []
        assert data["block_byom"] is False

    def test_admin_can_set_providers(self):
        org, owner, owner_token = _create_org()
        _, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/model-policy",
            {"allowed_providers": ["anthropic"]},
        )
        assert resp.status_code == 200
        assert resp.json()["allowed_providers"] == ["anthropic"]

    def test_member_denied(self):
        org, owner, owner_token = _create_org()
        _, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/model-policy",
            {"block_byom": True},
        )
        assert resp.status_code == 401

    def test_set_block_byom(self):
        org, owner, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {"block_byom": True},
        )
        assert resp.status_code == 200
        assert resp.json()["block_byom"] is True

    def test_partial_update_preserves_fields(self):
        org, owner, token = _create_org()
        # First set all fields
        _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {
                "allowed_models": ["gpt-4o"],
                "allowed_providers": ["openai"],
                "block_byom": True,
            },
        )
        # Then update only block_byom
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {"block_byom": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["allowed_models"] == ["gpt-4o"]
        assert data["allowed_providers"] == ["openai"]
        assert data["block_byom"] is False

    def test_clear_models_allows_all(self):
        org, owner, token = _create_org()
        _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {"allowed_models": ["gpt-4o"]},
        )
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/model-policy",
            {"allowed_models": []},
        )
        assert resp.status_code == 200
        assert resp.json()["allowed_models"] == []


# =============================================================================
# MODEL ENFORCEMENT — check_org_model_policy
# =============================================================================


class _FakeConv:
    """Minimal conversation stub for policy checks."""

    def __init__(self, project=None):
        self.project = project


class _FakeProject:
    """Minimal project stub for policy checks."""

    def __init__(self, organization=None):
        self.organization = organization


class TestModelEnforcement:
    def test_no_project_always_allowed(self):
        conv = _FakeConv(project=None)
        result = check_org_model_policy(conv, None, "gpt-4o")
        assert result is None

    def test_no_org_always_allowed(self):
        conv = _FakeConv(project=_FakeProject(organization=None))
        result = check_org_model_policy(conv, None, "gpt-4o")
        assert result is None

    def test_no_policy_always_allowed(self):
        org, _, _ = _create_org()
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "gpt-4o")
        assert result is None

    def test_empty_policy_allows_all(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=[],
            allowed_providers=[],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "openai:gpt-4o")
        assert result is None

    def test_allowed_model_passes(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4", "gpt-4o"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "claude-sonnet-4")
        assert result is None

    def test_blocked_model_returns_error(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "gpt-4o")
        assert result is not None
        assert "not permitted" in result["detail"]
        assert result["allowed_models"] == ["claude-sonnet-4"]

    def test_model_with_provider_prefix_allowed(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["gpt-4o"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        # "openai:gpt-4o" — the model name part "gpt-4o" should match
        result = check_org_model_policy(conv, None, "openai:gpt-4o")
        assert result is None

    def test_provider_enforcement_blocked(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_providers=["anthropic"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "openai:gpt-4o")
        assert result is not None
        assert "Provider" in result["detail"]
        assert "openai" in result["detail"]

    def test_provider_enforcement_allowed(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_providers=["anthropic", "openai"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "openai:gpt-4o")
        assert result is None

    def test_no_model_requested_always_allowed(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, None)
        assert result is None

    def test_full_model_string_in_allowed_list(self):
        """If allowed_models contains 'openai:gpt-4o', it should match that exact string."""
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["openai:gpt-4o"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        result = check_org_model_policy(conv, None, "openai:gpt-4o")
        assert result is None


# =============================================================================
# BYOM BLOCKING — should_block_byom
# =============================================================================


class TestByomBlocking:
    def test_no_project_no_block(self):
        conv = _FakeConv(project=None)
        assert should_block_byom(conv) is False

    def test_no_org_no_block(self):
        conv = _FakeConv(project=_FakeProject(organization=None))
        assert should_block_byom(conv) is False

    def test_no_policy_no_block(self):
        org, _, _ = _create_org()
        conv = _FakeConv(project=_FakeProject(organization=org))
        assert should_block_byom(conv) is False

    def test_block_byom_false_no_block(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            block_byom=False,
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        assert should_block_byom(conv) is False

    def test_block_byom_true_blocks(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            block_byom=True,
        )
        conv = _FakeConv(project=_FakeProject(organization=org))
        assert should_block_byom(conv) is True


# =============================================================================
# EDGE CASE: policy change mid-run
# =============================================================================


class TestPolicyChangeMidRun:
    """Policy changes should not affect already-evaluated runs.

    The enforcement happens at run-start time (in do_atomic_reservation),
    so once a run passes the check, it continues even if policy changes.
    We verify that the check function is purely a point-in-time evaluation.
    """

    def test_policy_change_after_check_doesnt_retroact(self):
        org, _, _ = _create_org()
        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4", "gpt-4o"],
        )
        conv = _FakeConv(project=_FakeProject(organization=org))

        # First check passes
        result = check_org_model_policy(conv, None, "gpt-4o")
        assert result is None

        # Admin removes gpt-4o from allowed list
        policy = OrgModelPolicy.objects.get(organization=org)
        policy.allowed_models = ["claude-sonnet-4"]
        policy.save()

        # Re-fetch org to clear Django's cached reverse relation
        org_fresh = Organization.objects.get(pk=org.pk)
        conv2 = _FakeConv(project=_FakeProject(organization=org_fresh))

        # Next check would block
        result = check_org_model_policy(conv2, None, "gpt-4o")
        assert result is not None
        assert "not permitted" in result["detail"]

        # But the original run is already in progress — enforcement is at start time only
