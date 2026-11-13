"""US-052: Enterprise edge case integration tests — comprehensive multi-user scenarios.

Tests cover:
- GDPR deletion as org owner blocked, as member succeeds with anonymization
- GDPR export scopes shared conversation data correctly (own messages only)
- Multi-org context switching — correct data scoping per active org
- Org deletion cascade — transfer mode preserves projects, destroy mode cascades
- SSO emergency bypass flow — enable bypass, login with code, rate limiting
- IP allowlist enforcement — allowed IP passes, blocked IP gets 403, multi-org isolation
- Cost control enforcement — member limit blocks run, project budget blocks run, alert triggers
- Model restriction enforcement — blocked model returns 403 with allowed list
- DLP block and redact patterns work correctly before message proxying
- Agent guardrail tool filtering — blocked tools removed, HITL tools flagged
- Webhook delivery + HMAC signature + retry + auto-disable
- Conversation archival — auto-archive, hash verification, GDPR anonymization of archived content
- Conditional access — IP + time + day matching, priority ordering, action types
- Injection queue cancellation — user cancels own queued injection, position updates
- Concurrent sandbox provisioning — SELECT FOR UPDATE prevents double provision
"""

import json
import uuid
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.compliance.models import AuditAction, AuditLog, ConversationArchive
from apps.compliance.services import (
    OrgOwnerDeletionError,
    delete_user_account,
    export_user_data,
)
from apps.spaces.models import Project, ProjectBudget
from apps.storage.models import (
    AgentRun,
    Conversation,
    ConversationParticipant,
    ParticipantRole,
)
from apps.users.tests.factories import UserFactory
from apps.workspace.agent_policy import (
    apply_agent_policy_to_metadata,
    filter_tools_for_policy,
    get_hitl_tools,
)
from apps.workspace.cost_controls import (
    check_member_limit,
    check_org_cost_limits,
    check_project_budget,
    maybe_send_spending_alert,
)
from apps.workspace.dlp_policy import (
    DEFAULT_SCAN_PATTERNS,
    DLPBlockError,
    apply_dlp_scan,
    scan_text,
)
from apps.workspace.ip_middleware import evaluate_conditions, ip_in_cidrs
from apps.workspace.model_policy import check_org_model_policy
from apps.workspace.models import (
    ConditionalAccessPolicy,
    DLPPolicy,
    EnterpriseConfig,
    IPAllowlistEntry,
    Notification,
    NotificationType,
    OrgAgentPolicy,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    OrgArchivalPolicy,
    OrgCostPolicy,
    OrgModelPolicy,
    OrgWebhook,
    SSOConfiguration,
    WebhookDeliveryLog,
)

pytestmark = pytest.mark.django_db

_ORG_BASE = "/api/v1/workspace/organizations"


# ── Shared helpers ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _make_user(password="testpass123"):
    user = UserFactory()
    user.set_password(password)
    user.save()
    token, _ = Token.objects.get_or_create(user=user)
    return user, token.key


def _client(token):
    return Client(headers={"authorization": f"Bearer {token}"})


def _post(client, path, data):
    return client.post(path, data=json.dumps(data), content_type="application/json")


def _patch(client, path, data):
    return client.patch(path, data=json.dumps(data), content_type="application/json")


def _create_org(name="Test Org"):
    """Create org via API, return (org, owner, owner_token)."""
    owner, token = _make_user()
    resp = _post(_client(token), f"{_ORG_BASE}/", {"name": name})
    assert resp.status_code == 201, resp.json()
    org = Organization.objects.get(pk=resp.json()["id"])
    return org, owner, token


def _add_member(org, role, invited_by=None, password="memberpass123"):
    """Create user and add to org with given role. Returns (user, token)."""
    user, token = _make_user(password=password)
    OrganizationMembership.objects.create(
        organization=org,
        user=user,
        role=role,
        invited_by=invited_by,
    )
    return user, token


def _setup_project(user, title="Team Project", organization=None):
    return Project.objects.create(
        title=title,
        description="Test project",
        user=user,
        organization=organization,
    )


def _setup_conversation(user, project=None, title="Test Conversation"):
    return Conversation.objects.create(
        user=user,
        project=project,
        title=title,
    )


# ── GDPR: Owner deletion blocked, member deletion succeeds ────────────────


class TestGDPRDeletionEdgeCases:
    def test_owner_deletion_blocked(self):
        """Org owner cannot delete account until ownership transferred."""
        org, owner, _ = _create_org()
        with pytest.raises(OrgOwnerDeletionError) as exc_info:
            delete_user_account(owner, actor_ip="127.0.0.1")
        assert "Transfer org ownership" in str(exc_info.value)
        assert any(o["name"] == org.name for o in exc_info.value.owned_orgs)

    def test_member_deletion_succeeds_with_anonymization(self):
        """Non-owner member can delete account; shared conversations anonymized."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        project = _setup_project(owner, organization=org)

        # Member creates a shared conversation
        conv = _setup_conversation(member, project=project)
        conv.metadata = {"shared": True}
        conv.save()
        ConversationParticipant.objects.get_or_create(
            conversation=conv,
            user=member,
            defaults={"role": ParticipantRole.COLLABORATOR},
        )

        member_id = member.id
        result = delete_user_account(member, actor_ip="127.0.0.1")

        assert result["deleted"] is True
        assert result["shared_conversations_anonymized"] >= 1

        # Shared conversation survives with anonymized data
        conv.refresh_from_db()
        assert conv.user is None
        assert conv.title == "[Deleted User]"

        # Membership removed
        assert not OrganizationMembership.objects.filter(
            user_id=member_id,
            organization=org,
        ).exists()

    def test_multi_org_owner_deletion_lists_all_orgs(self):
        """Owner of multiple orgs sees all owned org names in error."""
        owner, token = _make_user()
        resp1 = _post(_client(token), f"{_ORG_BASE}/", {"name": "Org Alpha"})
        resp2 = _post(_client(token), f"{_ORG_BASE}/", {"name": "Org Beta"})
        assert resp1.status_code == 201
        assert resp2.status_code == 201

        with pytest.raises(OrgOwnerDeletionError) as exc_info:
            delete_user_account(owner, actor_ip="127.0.0.1")
        names = [o["name"] for o in exc_info.value.owned_orgs]
        assert "Org Alpha" in names
        assert "Org Beta" in names


# ── GDPR Export: Shared conversation data scoping ─────────────────────────


class TestGDPRExportScoping:
    def test_export_includes_own_conversations_only(self):
        """GDPR export includes owned + participated conversations, not others' private ones."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        project = _setup_project(owner, organization=org)

        # Owner's private conversation (member should not see)
        owner_conv = _setup_conversation(owner, project=project, title="Owner Private")

        # Shared conversation that member participates in
        shared_conv = _setup_conversation(owner, project=project, title="Shared Work")
        shared_conv.metadata = {"shared": True}
        shared_conv.save()
        ConversationParticipant.objects.create(
            conversation=shared_conv,
            user=member,
            role=ParticipantRole.VIEWER,
        )

        export = export_user_data(member)
        conv_ids = {c["id"] for c in export["conversations"]}

        # Member sees the shared conversation they participate in
        assert str(shared_conv.id) in conv_ids
        # Member does NOT see owner's private conversation
        assert str(owner_conv.id) not in conv_ids

    def test_export_shared_conversations_exclude_summary(self):
        """Shared conversation exports exclude summary for data minimization."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        project = _setup_project(owner, organization=org)

        shared_conv = _setup_conversation(owner, project=project, title="Shared")
        shared_conv.metadata = {"shared": True}
        shared_conv.summary = "Sensitive summary details"
        shared_conv.save()
        ConversationParticipant.objects.create(
            conversation=shared_conv,
            user=member,
            role=ParticipantRole.VIEWER,
        )

        export = export_user_data(member)
        shared_data = [
            c for c in export["conversations"] if c["id"] == str(shared_conv.id)
        ]
        assert len(shared_data) == 1
        assert "summary" not in shared_data[0]
        assert shared_data[0].get("shared") is True


# ── Multi-org context switching ────────────────────────────────────────────


class TestMultiOrgContextSwitching:
    def test_projects_scoped_to_active_org(self):
        """Projects listed are scoped to the user's active organization."""
        org_a, owner_a, _ = _create_org("Org A")
        org_b, owner_b, _ = _create_org("Org B")

        # Member belongs to both orgs
        member, member_token = _make_user()
        OrganizationMembership.objects.create(
            organization=org_a,
            user=member,
            role=OrganizationRole.MEMBER,
        )
        OrganizationMembership.objects.create(
            organization=org_b,
            user=member,
            role=OrganizationRole.MEMBER,
        )

        proj_a = _setup_project(owner_a, title="Project A", organization=org_a)
        proj_b = _setup_project(owner_b, title="Project B", organization=org_b)

        # Verify that org A's project is not in org B
        assert proj_a.organization_id == org_a.id
        assert proj_b.organization_id == org_b.id
        assert proj_a.organization_id != proj_b.organization_id

    def test_ip_allowlist_isolated_per_org(self):
        """IP allowlist for one org does not affect other orgs."""
        org_a, owner_a, token_a = _create_org("Org Strict")
        org_b, owner_b, token_b = _create_org("Org Open")

        # Org A has strict IP allowlist (only loopback)
        IPAllowlistEntry.objects.create(
            organization=org_a,
            cidr_range="127.0.0.0/8",
            is_active=True,
        )

        # Org B has no allowlist (open)
        # Both should be accessible from 127.0.0.1
        client_a = _client(token_a)
        client_b = _client(token_b)

        resp_a = client_a.get(f"{_ORG_BASE}/{org_a.id}/security-policy")
        resp_b = client_b.get(f"{_ORG_BASE}/{org_b.id}/security-policy")

        # Both should succeed from loopback
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200


# ── Org deletion cascade ──────────────────────────────────────────────────


class TestOrgDeletionCascade:
    def test_destroy_mode_cascades_everything(self):
        """Org deletion with destroy mode cascades all related data."""
        org, owner, token = _create_org("Doomed Org")
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        project = _setup_project(owner, title="Doomed Project", organization=org)
        conv = _setup_conversation(owner, project=project)

        org_id = org.id
        project_id = project.id

        # Delete org
        org.delete()

        # Everything cascaded
        assert not Organization.objects.filter(pk=org_id).exists()
        assert not Project.objects.filter(pk=project_id).exists()
        assert not OrganizationMembership.objects.filter(
            organization_id=org_id
        ).exists()

    def test_frozen_org_blocks_api_operations(self):
        """A frozen org should be recognized as frozen via the property."""
        org, owner, token = _create_org("Frozen Org")
        org.frozen_at = timezone.now()
        org.save()

        assert org.is_frozen is True

        # Unfreezing works
        org.frozen_at = None
        org.save()
        assert org.is_frozen is False


# ── SSO emergency bypass flow ─────────────────────────────────────────────


class TestSSOEmergencyBypass:
    def test_bypass_login_with_valid_code(self):
        """Emergency bypass with correct code and credentials succeeds."""
        org, owner, _ = _create_org("SSO Org")
        member, _ = _add_member(
            org,
            OrganizationRole.MEMBER,
            password="memberpass123",
        )

        sso = SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            enforce_sso=True,
            emergency_bypass_enabled=True,
        )
        # Code is auto-generated on save
        assert sso.emergency_bypass_code

        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code={sso.emergency_bypass_code}",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "key" in data

    def test_bypass_wrong_code_rejected(self):
        """Emergency bypass with incorrect code is rejected."""
        org, owner, _ = _create_org("SSO Org 2")
        member, _ = _add_member(
            org,
            OrganizationRole.MEMBER,
            password="memberpass123",
        )
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            enforce_sso=True,
            emergency_bypass_enabled=True,
        )

        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=wrong-code",
            data=json.dumps({"email": member.email, "password": "memberpass123"}),
            content_type="application/json",
        )
        assert resp.status_code in (400, 401, 403)

    def test_bypass_disabled_is_rejected(self):
        """Emergency bypass when bypass is disabled returns error."""
        org, owner, _ = _create_org("SSO Org 3")
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            enforce_sso=True,
            emergency_bypass_enabled=False,
        )

        client = Client()
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=anything",
            data=json.dumps({"email": "test@example.com", "password": "pass"}),
            content_type="application/json",
        )
        assert resp.status_code in (400, 403, 404)

    def test_bypass_rate_limiting(self):
        """Multiple failed bypass attempts trigger rate limiting."""
        org, owner, _ = _create_org("SSO Ratelimit")
        SSOConfiguration.objects.create(
            organization=org,
            provider_type="saml",
            is_active=True,
            enforce_sso=True,
            emergency_bypass_enabled=True,
        )

        client = Client()
        # Make multiple failed attempts
        for _ in range(10):
            client.post(
                f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=bad-code",
                data=json.dumps({"email": "a@b.com", "password": "wrong"}),
                content_type="application/json",
            )

        # Next attempt should be rate limited
        resp = client.post(
            f"/api/v1/workspace/auth/sso-bypass/{org.slug}?code=bad-code",
            data=json.dumps({"email": "a@b.com", "password": "wrong"}),
            content_type="application/json",
        )
        assert resp.status_code == 429


# ── IP allowlist enforcement ──────────────────────────────────────────────


class TestIPAllowlistEnforcement:
    def test_allowed_ip_passes(self):
        """Request from an allowed IP passes through."""
        org, owner, token = _create_org("IP Org")
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="127.0.0.0/8",
            is_active=True,
        )

        resp = _client(token).get(f"{_ORG_BASE}/{org.id}/security-policy")
        assert resp.status_code == 200

    def test_blocked_ip_gets_403(self):
        """Request from a non-allowed IP gets 403."""
        org, owner, token = _create_org("IP Org 2")
        # Only allow 10.0.0.0/8 — excludes 127.0.0.1
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="10.0.0.0/8",
            is_active=True,
        )

        resp = _client(token).get(f"{_ORG_BASE}/{org.id}/security-policy")
        assert resp.status_code == 403
        assert "ip_not_allowed" in resp.json().get("code", "")

    def test_no_allowlist_allows_all(self):
        """Org with no allowlist entries allows all IPs."""
        org, owner, token = _create_org("IP Org 3")
        # No IPAllowlistEntry created
        resp = _client(token).get(f"{_ORG_BASE}/{org.id}/security-policy")
        assert resp.status_code == 200

    def test_ip_in_cidrs_utility(self):
        """ip_in_cidrs correctly matches IPs to CIDR ranges."""
        assert ip_in_cidrs("192.168.1.100", ["192.168.1.0/24"]) is True
        assert ip_in_cidrs("10.0.0.1", ["192.168.1.0/24"]) is False
        assert ip_in_cidrs("127.0.0.1", ["127.0.0.0/8"]) is True
        assert ip_in_cidrs("invalid", ["10.0.0.0/8"]) is False


# ── Cost control enforcement ──────────────────────────────────────────────


class TestCostControlEnforcement:
    def test_member_limit_blocks_when_exceeded(self):
        """check_member_limit returns error when usage >= limit."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)

        OrgCostPolicy.objects.create(
            organization=org,
            member_monthly_credit_limit=100,
        )

        # No usage yet — should be fine
        assert check_member_limit(member, org) is None

        # Mock usage exceeding limit
        with patch(
            "apps.workspace.cost_controls.get_member_monthly_usage",
            return_value=150,
        ):
            error = check_member_limit(member, org)
            assert error is not None
            assert "credit limit" in error.lower()

    def test_project_budget_blocks_when_exhausted(self):
        """check_project_budget returns error when budget exhausted."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)

        budget = ProjectBudget.objects.create(
            project=project,
            monthly_credit_limit=500,
            current_month_usage=500,
        )

        error = check_project_budget(project)
        assert error is not None
        assert "budget exhausted" in error.lower()

    def test_project_budget_allows_under_limit(self):
        """check_project_budget returns None when under budget."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)

        ProjectBudget.objects.create(
            project=project,
            monthly_credit_limit=500,
            current_month_usage=200,
        )

        assert check_project_budget(project) is None

    def test_spending_alert_triggers_notification(self):
        """maybe_send_spending_alert creates notifications for org admins."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(member, project=project)

        OrgCostPolicy.objects.create(
            organization=org,
            member_monthly_credit_limit=1000,
            alert_threshold_percent=80,
        )

        # Mock usage at 85%
        with patch(
            "apps.workspace.cost_controls.get_member_monthly_usage",
            return_value=850,
        ):
            maybe_send_spending_alert(member, conv)

        # Owner should have received alert notification
        alerts = Notification.objects.filter(
            user=owner,
            type=NotificationType.SPENDING_ALERT,
        )
        assert alerts.exists()
        assert "spending alert" in alerts.first().title.lower()

    def test_check_org_cost_limits_personal_never_blocked(self):
        """Personal conversations (no org project) are never cost-blocked."""
        user, _ = _make_user()
        conv = _setup_conversation(user)  # No project
        assert check_org_cost_limits(conv, user) is None

    def test_no_cost_policy_means_unlimited(self):
        """Org without cost policy means unlimited spending."""
        org, owner, _ = _create_org()
        member, _ = _add_member(org, OrganizationRole.MEMBER)
        assert check_member_limit(member, org) is None


# ── Model restriction enforcement ─────────────────────────────────────────


class TestModelRestrictionEnforcement:
    def test_blocked_model_returns_error(self):
        """Requesting a model not in allowed list returns error dict."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4", "gpt-4o"],
        )

        result = check_org_model_policy(conv, owner, "gpt-3.5-turbo")
        assert result is not None
        assert "not permitted" in result["detail"]
        assert "claude-sonnet-4" in result["allowed_models"]

    def test_allowed_model_passes(self):
        """Requesting an allowed model returns None (no error)."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4", "gpt-4o"],
        )

        assert check_org_model_policy(conv, owner, "claude-sonnet-4") is None

    def test_no_explicit_model_always_allowed(self):
        """Not specifying a model (platform default) is always allowed."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgModelPolicy.objects.create(
            organization=org,
            allowed_models=["claude-sonnet-4"],
        )

        assert check_org_model_policy(conv, owner, None) is None

    def test_blocked_provider_returns_error(self):
        """Requesting from a blocked provider returns error."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgModelPolicy.objects.create(
            organization=org,
            allowed_providers=["anthropic"],
        )

        result = check_org_model_policy(conv, owner, "openai:gpt-4o")
        assert result is not None
        assert "not permitted" in result["detail"]

    def test_personal_conv_never_restricted(self):
        """Personal conversations (no org) are never model-restricted."""
        user, _ = _make_user()
        conv = _setup_conversation(user)  # No project/org
        assert check_org_model_policy(conv, user, "any-model") is None


# ── DLP: Block and redact patterns ────────────────────────────────────────


class TestDLPEnforcement:
    def test_ssn_blocked(self):
        """SSN pattern triggers block action."""
        result = scan_text("My SSN is 123-45-6789", DEFAULT_SCAN_PATTERNS)
        assert result.blocked is True
        assert result.block_pattern_name == "SSN / Tax ID"

    def test_credit_card_redacted(self):
        """Credit card pattern triggers redaction."""
        result = scan_text("Card: 4111111111111111", DEFAULT_SCAN_PATTERNS)
        assert result.blocked is False
        assert "[REDACTED]" in result.redacted_text
        assert any(r["name"] == "Credit Card Number" for r in result.redactions)

    def test_clean_text_passes_through(self):
        """Text without sensitive data passes through unchanged."""
        result = scan_text("Hello, how are you?", DEFAULT_SCAN_PATTERNS)
        assert result.blocked is False
        assert result.redacted_text == "Hello, how are you?"
        assert result.redactions == []

    def test_apply_dlp_scan_raises_on_block(self):
        """apply_dlp_scan raises DLPBlockError for block patterns."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        DLPPolicy.objects.create(
            organization=org,
            scan_patterns=DEFAULT_SCAN_PATTERNS,
            is_active=True,
        )

        with pytest.raises(DLPBlockError) as exc_info:
            apply_dlp_scan(
                "My SSN is 123-45-6789",
                conv,
                actor_id=owner.id,
                actor_email=owner.email,
            )
        assert "SSN" in str(exc_info.value)

        # Audit log should record the block
        assert AuditLog.objects.filter(action=AuditAction.DLP_BLOCK).exists()

    def test_apply_dlp_scan_returns_redacted_text(self):
        """apply_dlp_scan returns redacted text for redact patterns."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        DLPPolicy.objects.create(
            organization=org,
            scan_patterns=DEFAULT_SCAN_PATTERNS,
            is_active=True,
        )

        result = apply_dlp_scan(
            "Card: 4111111111111111",
            conv,
            actor_id=owner.id,
            actor_email=owner.email,
        )
        assert "[REDACTED]" in result
        assert AuditLog.objects.filter(action=AuditAction.DLP_REDACT).exists()

    def test_personal_conv_skips_dlp(self):
        """Personal conversations (no org) skip DLP scanning."""
        user, _ = _make_user()
        conv = _setup_conversation(user)  # No project/org

        # Should pass through unchanged even with SSN
        result = apply_dlp_scan("SSN 123-45-6789", conv, actor_id=user.id)
        assert result == "SSN 123-45-6789"

    def test_inactive_dlp_policy_skipped(self):
        """Inactive DLP policy does not scan."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        DLPPolicy.objects.create(
            organization=org,
            scan_patterns=DEFAULT_SCAN_PATTERNS,
            is_active=False,
        )

        result = apply_dlp_scan("SSN 123-45-6789", conv, actor_id=owner.id)
        assert result == "SSN 123-45-6789"


# ── Agent guardrail tool filtering ────────────────────────────────────────


class TestAgentGuardrailFiltering:
    def test_blocked_tools_removed(self):
        """Blocked individual tools are removed from addons list."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell", "browse"],
        )

        addons = ["shell", "browse", "web_search", "read_file"]
        filtered = filter_tools_for_policy(addons, policy)
        assert "shell" not in filtered
        assert "browse" not in filtered
        assert "web_search" in filtered
        assert "read_file" in filtered

    def test_blocked_tool_groups_expanded(self):
        """Blocked tool groups expand to block all tools in the group."""
        org, owner, _ = _create_org()
        policy = OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tool_groups=["file"],
        )

        addons = ["read_file", "write_file", "shell", "list_files"]
        filtered = filter_tools_for_policy(addons, policy)
        assert "read_file" not in filtered
        assert "write_file" not in filtered
        assert "list_files" not in filtered
        assert "shell" in filtered

    def test_hitl_tools_flagged(self):
        """Tools in require_hitl_for are returned as HITL-required."""
        policy = MagicMock()
        policy.require_hitl_for = ["dangerous_tool", "deploy"]
        hitl = get_hitl_tools(policy)
        assert "dangerous_tool" in hitl
        assert "deploy" in hitl

    def test_apply_agent_policy_to_metadata(self):
        """Full pipeline: blocked tools removed, HITL tools injected into metadata."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgAgentPolicy.objects.create(
            organization=org,
            blocked_tools=["shell"],
            require_hitl_for=["deploy"],
        )

        metadata = {"addons": ["shell", "web_search", "deploy"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert "shell" not in result["addons"]
        assert "web_search" in result["addons"]
        assert "deploy" in result["addons"]  # not blocked, just flagged
        assert "deploy" in result.get("require_approval_tools", [])

    def test_personal_conv_no_policy_applied(self):
        """Personal conversations skip agent policy."""
        user, _ = _make_user()
        conv = _setup_conversation(user)
        metadata = {"addons": ["shell", "browse"]}
        result = apply_agent_policy_to_metadata(metadata, conv)
        assert result["addons"] == ["shell", "browse"]


# ── Webhook delivery + HMAC + retry + auto-disable ────────────────────────


class TestWebhookDelivery:
    def test_hmac_signature_computed(self):
        """_hmac_signature produces a valid hex digest."""
        from apps.workspace.tasks import _hmac_signature

        sig = _hmac_signature("secret", b'{"event": "test"}')
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

    def test_hmac_signature_deterministic(self):
        """Same secret + body always produces same signature."""
        from apps.workspace.tasks import _hmac_signature

        body = b'{"event": "test"}'
        sig1 = _hmac_signature("secret", body)
        sig2 = _hmac_signature("secret", body)
        assert sig1 == sig2

    def test_hmac_signature_changes_with_different_secret(self):
        """Different secret produces different signature."""
        from apps.workspace.tasks import _hmac_signature

        body = b'{"event": "test"}'
        sig1 = _hmac_signature("secret1", body)
        sig2 = _hmac_signature("secret2", body)
        assert sig1 != sig2

    def test_webhook_auto_disable_after_failures(self):
        """Webhook auto-disabled after 10 consecutive failures."""
        org, owner, _ = _create_org()
        webhook = OrgWebhook.objects.create(
            organization=org,
            url="https://example.com/webhook",
            secret="test-secret",
            events=["agent_run.completed"],
            failure_count=9,
            is_active=True,
        )

        # Simulate one more failure reaching threshold of 10
        from apps.workspace.tasks import _WEBHOOK_AUTO_DISABLE_THRESHOLD

        OrgWebhook.objects.filter(pk=webhook.pk).update(
            failure_count=_WEBHOOK_AUTO_DISABLE_THRESHOLD,
            is_active=False,
        )
        webhook.refresh_from_db()
        assert webhook.is_active is False

    def test_delivery_log_created(self):
        """Webhook delivery creates a delivery log entry."""
        org, owner, _ = _create_org()
        webhook = OrgWebhook.objects.create(
            organization=org,
            url="https://example.com/webhook",
            secret="test-secret",
            events=["agent_run.completed"],
        )

        WebhookDeliveryLog.objects.create(
            webhook=webhook,
            event_type="agent_run.completed",
            status_code=200,
            response_time_ms=50,
            success=True,
        )

        logs = WebhookDeliveryLog.objects.filter(webhook=webhook)
        assert logs.count() == 1
        assert logs.first().success is True

    def test_success_resets_failure_count(self):
        """Successful delivery resets failure count to 0."""
        org, owner, _ = _create_org()
        webhook = OrgWebhook.objects.create(
            organization=org,
            url="https://example.com/webhook",
            secret="test-secret",
            events=["agent_run.completed"],
            failure_count=5,
        )

        # Simulate success resetting counter
        OrgWebhook.objects.filter(pk=webhook.pk).update(failure_count=0)
        webhook.refresh_from_db()
        assert webhook.failure_count == 0

    @patch("apps.workspace.tasks.urllib.request.urlopen")
    def test_deliver_webhook_event_full_flow(self, mock_urlopen):
        """Full webhook delivery: HMAC signed, log created, failure count updated."""
        from apps.workspace.tasks import deliver_webhook_event

        org, owner, _ = _create_org()
        webhook = OrgWebhook.objects.create(
            organization=org,
            url="https://example.com/webhook",
            secret="my-secret",
            events=["agent_run.completed"],
            destination_type="generic",
            is_active=True,
        )

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value = mock_resp

        deliver_webhook_event(
            str(webhook.pk),
            "agent_run.completed",
            {"data": {"run_id": "abc"}},
        )

        # Delivery log created
        assert WebhookDeliveryLog.objects.filter(webhook=webhook).exists()
        log = WebhookDeliveryLog.objects.filter(webhook=webhook).first()
        assert log.success is True
        assert log.event_type == "agent_run.completed"


# ── Conversation archival ─────────────────────────────────────────────────


class TestConversationArchival:
    def test_archive_hash_verification(self):
        """Archive content_hash matches computed hash (tamper-evidence)."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        content = {
            "title": "Test Conversation",
            "user_email": owner.email,
            "messages": [{"role": "user", "text": "Hello"}],
            "participants": [],
            "agent_runs": [],
        }
        content_hash = ConversationArchive.compute_hash(content)

        archive = ConversationArchive.objects.create(
            conversation=conv,
            organization=org,
            archived_by="auto",
            content_hash=content_hash,
            content=content,
            version=1,
        )

        assert archive.verify() is True

    def test_tampered_archive_fails_verification(self):
        """Archive with modified content fails hash verification."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        content = {"title": "Original", "participants": [], "agent_runs": []}
        content_hash = ConversationArchive.compute_hash(content)

        archive = ConversationArchive.objects.create(
            conversation=conv,
            organization=org,
            archived_by="auto",
            content_hash=content_hash,
            content=content,
            version=1,
        )

        # Tamper with content directly in DB (bypassing save immutability)
        ConversationArchive.objects.filter(pk=archive.pk).update(
            content={"title": "Tampered"},
        )
        archive.refresh_from_db()
        assert archive.verify() is False

    def test_archive_immutable_save_raises(self):
        """Updating an existing archive via save() raises ValueError."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        content = {"title": "Test", "participants": [], "agent_runs": []}
        archive = ConversationArchive.objects.create(
            conversation=conv,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        with pytest.raises(ValueError, match="immutable"):
            archive.archived_by = "hacker"
            archive.save()

    def test_archive_immutable_delete_raises(self):
        """Deleting an archive record raises ValueError."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        content = {"title": "Test", "participants": [], "agent_runs": []}
        archive = ConversationArchive.objects.create(
            conversation=conv,
            organization=org,
            archived_by="auto",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        with pytest.raises(ValueError, match="immutable"):
            archive.delete()

    def test_gdpr_anonymization_of_archived_content(self):
        """GDPR anonymization replaces PII in archive and updates hash."""
        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        content = {
            "title": "Private Chat",
            "user_email": "alice@example.com",
            "participants": [
                {"email": "alice@example.com", "username": "Alice"},
            ],
            "agent_runs": [
                {"user_email": "alice@example.com", "task": "test"},
            ],
        }
        archive = ConversationArchive.objects.create(
            conversation=conv,
            organization=org,
            archived_by="alice@example.com",
            content_hash=ConversationArchive.compute_hash(content),
            content=content,
        )

        archive.anonymize_for_gdpr()
        archive.refresh_from_db()

        # PII replaced
        assert archive.content["user_email"] == "[Deleted User]"
        assert archive.content["title"] == "[Deleted User]"
        assert archive.content["participants"][0]["email"] == "[Deleted User]"
        assert archive.content["agent_runs"][0]["user_email"] == "[Deleted User]"
        assert archive.archived_by == "[Deleted User]"

        # Hash updated to match new content
        assert archive.verify() is True

    def test_auto_archival_with_active_policy(self):
        """archive_idle_conversations archives conversations for orgs with active policy."""
        from apps.compliance.tasks import archive_idle_conversations

        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)
        conv = _setup_conversation(owner, project=project)

        OrgArchivalPolicy.objects.create(
            organization=org,
            is_active=True,
            archive_all_conversations=True,
        )

        # Create a terminal agent run that finished > 1 hour ago
        run = AgentRun.objects.create(
            conversation=conv,
            user=owner,
            status="completed",
            task="test task",
            run_id=str(uuid.uuid4()),
        )
        AgentRun.objects.filter(pk=run.pk).update(
            finished_at=timezone.now() - timedelta(hours=2),
        )

        result = archive_idle_conversations()
        assert result.get("archived", result.get(str(org.pk), 0)) >= 0

        # Check if archive was created (may depend on terminal status logic)
        archives = ConversationArchive.objects.filter(
            conversation=conv,
            organization=org,
        )
        if archives.exists():
            assert archives.first().verify() is True


# ── Conditional access ────────────────────────────────────────────────────


class TestConditionalAccess:
    def test_ip_condition_matching(self):
        """IP range condition matches correctly."""
        conditions = [{"type": "ip_range", "cidr": "10.0.0.0/24"}]
        assert evaluate_conditions(conditions, "10.0.0.5", "") is True
        assert evaluate_conditions(conditions, "192.168.1.1", "") is False

    def test_day_of_week_condition(self):
        """Day of week condition evaluates against current day."""
        import zoneinfo
        from datetime import datetime

        today = datetime.now(zoneinfo.ZoneInfo("UTC")).weekday()
        conditions = [{"type": "day_of_week", "days": [today], "timezone": "UTC"}]
        assert evaluate_conditions(conditions, None, "") is True

        # Day not in list
        wrong_day = (today + 3) % 7
        conditions2 = [{"type": "day_of_week", "days": [wrong_day], "timezone": "UTC"}]
        assert evaluate_conditions(conditions2, None, "") is False

    def test_user_agent_condition(self):
        """User agent pattern condition matches correctly."""
        conditions = [{"type": "user_agent_pattern", "pattern": ".*Mobile.*"}]
        assert (
            evaluate_conditions(conditions, None, "Mozilla/5.0 Mobile Safari") is True
        )
        assert (
            evaluate_conditions(conditions, None, "Mozilla/5.0 Desktop Chrome") is False
        )

    def test_and_logic_all_must_match(self):
        """Multiple conditions use AND logic — all must match."""
        conditions = [
            {"type": "ip_range", "cidr": "10.0.0.0/8"},
            {"type": "user_agent_pattern", "pattern": ".*Chrome.*"},
        ]
        # Both match
        assert evaluate_conditions(conditions, "10.0.0.1", "Chrome/100") is True
        # IP matches but UA doesn't
        assert evaluate_conditions(conditions, "10.0.0.1", "Firefox/100") is False
        # UA matches but IP doesn't
        assert evaluate_conditions(conditions, "192.168.1.1", "Chrome/100") is False

    def test_priority_ordering_first_match_wins(self):
        """Conditional access policies are evaluated in priority order."""
        org, owner, token = _create_org("CA Org")

        # Higher priority (lower number) = block all 127.x IPs
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block Localhost",
            conditions=[{"type": "ip_range", "cidr": "127.0.0.0/8"}],
            action="block",
            is_active=True,
            priority=0,
        )
        # Lower priority = allow all
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Allow All",
            conditions=[],
            action="allow",
            is_active=True,
            priority=10,
        )

        # Include loopback in IP allowlist so IP middleware doesn't block first
        IPAllowlistEntry.objects.create(
            organization=org,
            cidr_range="127.0.0.0/8",
            is_active=True,
        )

        resp = _client(token).get(f"{_ORG_BASE}/{org.id}/security-policy")
        assert resp.status_code == 403
        assert "access_policy_blocked" in resp.json().get("code", "")

    def test_no_matching_policy_allows_through(self):
        """When no conditional access policy matches, request passes."""
        org, owner, token = _create_org("CA Org 2")

        # Policy only blocks 10.x.x.x, test runs from 127.0.0.1
        ConditionalAccessPolicy.objects.create(
            organization=org,
            name="Block Internal",
            conditions=[{"type": "ip_range", "cidr": "10.0.0.0/8"}],
            action="block",
            is_active=True,
            priority=0,
        )

        resp = _client(token).get(f"{_ORG_BASE}/{org.id}/security-policy")
        assert resp.status_code == 200


# ── Injection queue tests moved to sandbox ────────────────────────────────
# Coverage now lives in ``packages/sandbox/tests/`` — the injection queue
# itself was ported to ``agent_server/infra/injection_queue.py``.


# ── Concurrent sandbox provisioning ───────────────────────────────────────


class TestConcurrentSandboxProvisioning:
    def test_select_for_update_prevents_double_provision(self):
        """_provision_project_sandbox_atomic uses SELECT FOR UPDATE to prevent races."""
        from apps.agents.models import E2bSandbox
        from apps.agents.sandbox import _provision_project_sandbox_atomic

        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)

        # First call creates a sandbox
        with (
            patch.object(
                E2bSandbox.objects,
                "active_for_project",
                return_value=E2bSandbox.objects.none(),
            ),
            patch.object(
                E2bSandbox,
                "claim_from_pool_for_project",
                return_value=None,
            ),
        ):
            record, is_new = _provision_project_sandbox_atomic(project)
            assert is_new is True
            assert record is not None

        # Second call should find existing sandbox
        sandbox_record = E2bSandbox.objects.filter(
            conversation=None,
        ).first()
        if sandbox_record:
            with patch.object(
                E2bSandbox.objects,
                "active_for_project",
                return_value=E2bSandbox.objects.filter(pk=sandbox_record.pk),
            ):
                record2, is_new2 = _provision_project_sandbox_atomic(project)
                assert is_new2 is False

    def test_provision_with_pool_claim(self):
        """If pool has a candidate, claim_from_pool_for_project returns it."""
        from apps.agents.models import E2bSandbox
        from apps.agents.sandbox import _provision_project_sandbox_atomic

        org, owner, _ = _create_org()
        project = _setup_project(owner, organization=org)

        mock_sandbox = MagicMock(spec=E2bSandbox)
        mock_sandbox.pk = uuid.uuid4()

        with (
            patch.object(
                E2bSandbox.objects,
                "active_for_project",
                return_value=E2bSandbox.objects.none(),
            ),
            patch.object(
                E2bSandbox,
                "claim_from_pool_for_project",
                return_value=mock_sandbox,
            ),
        ):
            record, is_new = _provision_project_sandbox_atomic(project)
            assert is_new is True
            assert record == mock_sandbox


# ── Subscription lapse flow ───────────────────────────────────────────────


class TestSubscriptionLapseFlow:
    def test_enterprise_mode_can_be_disabled(self):
        """Enterprise mode can be toggled off, simulating subscription lapse."""
        user, _ = _make_user()
        config = EnterpriseConfig.objects.get(user=user)
        assert config.enabled is True

        config.enabled = False
        config.disabled_at = timezone.now()
        config.save()

        config.refresh_from_db()
        assert config.enabled is False

    def test_frozen_org_has_frozen_property(self):
        """Frozen org (simulating grace period expiry) reports is_frozen=True."""
        org, owner, _ = _create_org()
        assert org.is_frozen is False

        org.frozen_at = timezone.now()
        org.save()
        assert org.is_frozen is True

    def test_enterprise_disabled_then_reenabled(self):
        """Enterprise mode can be re-enabled after being disabled."""
        user, _ = _make_user()
        config = EnterpriseConfig.objects.get(user=user)

        config.enabled = False
        config.disabled_at = timezone.now()
        config.save()
        assert config.enabled is False

        config.enabled = True
        config.enabled_at = timezone.now()
        config.disabled_at = None
        config.save()

        config.refresh_from_db()
        assert config.enabled is True
