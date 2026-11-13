"""Tests for DLP (Data Loss Prevention) policy.

Covers:
- DLPPolicy model creation and defaults
- Pattern matching: credit cards, SSNs, AWS keys, private keys, API keys
- Block vs redact actions
- False positive handling
- Org scoping (personal conversations not scanned)
- Audit logging for DLP events
- API endpoints: GET/PATCH dlp-policy, POST test
- RBAC: admin+ can manage DLP
"""

import json

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.authtoken.models import Token

from apps.users.tests.factories import UserFactory
from apps.workspace.dlp_policy import (
    DEFAULT_SCAN_PATTERNS,
    DLPBlockError,
    apply_dlp_scan,
    get_dlp_policy_for_conversation,
    scan_text,
)
from apps.workspace.models import (
    DLPPolicy,
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


def _create_org(name="DLP Test Org"):
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


def _create_dlp_policy(org, patterns=None, is_active=True):
    return DLPPolicy.objects.create(
        organization=org,
        scan_patterns=patterns if patterns is not None else DEFAULT_SCAN_PATTERNS,
        is_active=is_active,
    )


# =============================================================================
# SCAN_TEXT — pattern matching unit tests
# =============================================================================


class TestScanText:
    """Unit tests for the scan_text function."""

    def test_credit_card_visa_redacted(self):
        text = "My card is 4111111111111111 please charge it"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert "[REDACTED]" in result.redacted_text
        assert "4111111111111111" not in result.redacted_text
        assert any(r["name"] == "Credit Card Number" for r in result.redactions)

    def test_credit_card_mastercard_redacted(self):
        text = "Card: 5500000000000004"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert "[REDACTED]" in result.redacted_text

    def test_credit_card_amex_redacted(self):
        text = "AMEX 378282246310005"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert "[REDACTED]" in result.redacted_text

    def test_ssn_blocked(self):
        text = "My SSN is 123-45-6789"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert result.blocked
        assert result.block_pattern_name == "SSN / Tax ID"

    def test_aws_access_key_blocked(self):
        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert result.blocked
        assert result.block_pattern_name == "AWS Access Key"

    def test_private_key_blocked(self):
        text = "Here is my key:\n-----BEGIN PRIVATE KEY-----\nMIIEvQI..."  # gitleaks:allow
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert result.blocked
        assert result.block_pattern_name == "Private Key"

    def test_rsa_private_key_blocked(self):
        text = "-----BEGIN RSA PRIVATE KEY-----"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert result.blocked

    def test_api_key_pattern_redacted(self):
        text = "Use this key: sk-abc123defghijklmnopqrst"  # gitleaks:allow
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert "[REDACTED]" in result.redacted_text

    def test_no_match_passes_through(self):
        text = "Hello, how are you doing today?"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert result.redacted_text == text
        assert len(result.redactions) == 0

    def test_empty_text(self):
        result = scan_text("", DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert result.redacted_text == ""

    def test_empty_patterns(self):
        result = scan_text("My SSN is 123-45-6789", [])
        assert not result.blocked
        assert result.redacted_text == "My SSN is 123-45-6789"

    def test_block_takes_priority_over_redact(self):
        """When both block and redact patterns match, block wins."""
        text = "SSN: 123-45-6789 card: 4111111111111111"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        # SSN check comes before credit card in DEFAULT_SCAN_PATTERNS
        # but credit card is listed first (redact). SSN (block) is second.
        # The credit card gets redacted first, then SSN blocks.
        assert result.blocked
        assert result.block_pattern_name == "SSN / Tax ID"

    def test_invalid_regex_skipped(self):
        patterns = [{"name": "Bad Pattern", "regex": "[invalid(", "action": "block"}]
        result = scan_text("some text", patterns)
        assert not result.blocked
        assert result.redacted_text == "some text"

    def test_custom_block_pattern(self):
        patterns = [
            {"name": "Custom Secret", "regex": r"SUPERSECRET-\w+", "action": "block"}
        ]
        result = scan_text("Found SUPERSECRET-abc123 here", patterns)
        assert result.blocked
        assert result.block_pattern_name == "Custom Secret"

    def test_custom_redact_pattern(self):
        patterns = [
            {
                "name": "Phone Number",
                "regex": r"\b\d{3}-\d{3}-\d{4}\b",
                "action": "redact",
            }
        ]
        result = scan_text("Call me at 555-123-4567", patterns)
        assert not result.blocked
        assert result.redacted_text == "Call me at [REDACTED]"

    def test_multiple_redactions(self):
        patterns = [
            {"name": "Phone", "regex": r"\b\d{3}-\d{3}-\d{4}\b", "action": "redact"},
            {
                "name": "Email",
                "regex": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
                "action": "redact",
            },
        ]
        text = "Call 555-123-4567 or email test@example.com"
        result = scan_text(text, patterns)
        assert not result.blocked
        assert "555-123-4567" not in result.redacted_text
        assert "test@example.com" not in result.redacted_text
        assert result.redacted_text.count("[REDACTED]") == 2

    def test_false_positive_short_numbers(self):
        """Short number sequences that look like but aren't credit cards should not match."""
        text = "Order #12345 has 3 items"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        assert result.redacted_text == text

    def test_false_positive_date_not_ssn(self):
        """Dates like 2024-01-15 should not match SSN pattern."""
        text = "The date is 2024-01-15"
        result = scan_text(text, DEFAULT_SCAN_PATTERNS)
        assert not result.blocked
        # Date format is different from SSN format (XXX-XX-XXXX)
        assert result.redacted_text == text


# =============================================================================
# GET_DLP_POLICY_FOR_CONVERSATION — org scoping
# =============================================================================


class TestDLPOrgScoping:
    """Test that DLP only applies to org project conversations."""

    def test_personal_conversation_returns_none(self):
        """Personal conversations (no project) should not be DLP-scanned."""
        from unittest.mock import Mock

        conv = Mock(spec=["project", "id"])
        conv.project = None
        assert get_dlp_policy_for_conversation(conv) is None

    def test_non_org_project_returns_none(self):
        """Projects without an org should not be DLP-scanned."""
        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = None
        conv = Mock(spec=["project", "id"])
        conv.project = project
        assert get_dlp_policy_for_conversation(conv) is None

    def test_org_without_policy_returns_none(self):
        """Org without DLP policy returns None."""
        org, _, _ = _create_org()

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        assert get_dlp_policy_for_conversation(conv) is None

    def test_inactive_policy_returns_none(self):
        """Inactive DLP policies return None."""
        org, _, _ = _create_org()
        _create_dlp_policy(org, is_active=False)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        assert get_dlp_policy_for_conversation(conv) is None

    def test_active_policy_returned(self):
        """Active DLP policy for org project is returned."""
        org, _, _ = _create_org()
        policy = _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        result = get_dlp_policy_for_conversation(conv)
        assert result is not None
        assert result.pk == policy.pk


# =============================================================================
# APPLY_DLP_SCAN — integration with audit logging
# =============================================================================


class TestApplyDLPScan:
    """Test the apply_dlp_scan function with audit logging."""

    def test_no_policy_passes_through(self):
        from unittest.mock import Mock

        conv = Mock(spec=["project", "id"])
        conv.project = None
        result = apply_dlp_scan("My SSN is 123-45-6789", conv)
        assert result == "My SSN is 123-45-6789"

    def test_block_raises_error(self):
        org, owner, _ = _create_org()
        _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        conv.id = "test-conv-id"

        with pytest.raises(DLPBlockError, match="SSN / Tax ID"):
            apply_dlp_scan(
                "My SSN is 123-45-6789",
                conv,
                actor_id=owner.pk,
                actor_email=owner.email,
            )

    def test_redact_returns_cleaned_text(self):
        org, owner, _ = _create_org()
        _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        conv.id = "test-conv-id"

        result = apply_dlp_scan(
            "My card is 4111111111111111",
            conv,
            actor_id=owner.pk,
            actor_email=owner.email,
        )
        assert "4111111111111111" not in result
        assert "[REDACTED]" in result

    def test_block_creates_audit_log(self):
        from apps.compliance.models import AuditAction, AuditLog

        org, owner, _ = _create_org()
        _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        conv.id = "test-conv-id"

        with pytest.raises(DLPBlockError):
            apply_dlp_scan(
                "My SSN is 123-45-6789",
                conv,
                actor_id=owner.pk,
                actor_email=owner.email,
            )

        logs = AuditLog.objects.filter(action=AuditAction.DLP_BLOCK)
        assert logs.count() == 1
        log = logs.first()
        assert log.metadata["pattern_name"] == "SSN / Tax ID"
        assert "message_hash" in log.metadata
        assert log.resource_id == "test-conv-id"

    def test_redact_creates_audit_log(self):
        from apps.compliance.models import AuditAction, AuditLog

        org, owner, _ = _create_org()
        _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        conv.id = "test-conv-id"

        apply_dlp_scan(
            "My card is 4111111111111111",
            conv,
            actor_id=owner.pk,
            actor_email=owner.email,
        )

        logs = AuditLog.objects.filter(action=AuditAction.DLP_REDACT)
        assert logs.count() == 1
        log = logs.first()
        assert log.metadata["pattern_name"] == "Credit Card Number"

    def test_no_match_no_audit_log(self):
        from apps.compliance.models import AuditAction, AuditLog

        org, owner, _ = _create_org()
        _create_dlp_policy(org)

        from unittest.mock import Mock

        project = Mock(spec=["organization"])
        project.organization = org
        conv = Mock(spec=["project", "id"])
        conv.project = project
        conv.id = "test-conv-id"

        result = apply_dlp_scan(
            "Hello world",
            conv,
            actor_id=owner.pk,
            actor_email=owner.email,
        )
        assert result == "Hello world"

        dlp_logs = AuditLog.objects.filter(
            action__in=[AuditAction.DLP_BLOCK, AuditAction.DLP_REDACT]
        )
        assert dlp_logs.count() == 0


# =============================================================================
# DLP MODEL
# =============================================================================


class TestDLPPolicyModel:
    def test_create_with_defaults(self):
        org, _, _ = _create_org()
        policy = _create_dlp_policy(org)
        assert policy.is_active is True
        assert len(policy.scan_patterns) == len(DEFAULT_SCAN_PATTERNS)

    def test_str_representation(self):
        org, _, _ = _create_org()
        policy = _create_dlp_policy(org)
        assert "DLP policy" in str(policy)
        assert str(len(DEFAULT_SCAN_PATTERNS)) in str(policy)

    def test_cascade_delete(self):
        org, _, _ = _create_org()
        _create_dlp_policy(org)
        org.delete()
        assert DLPPolicy.objects.count() == 0


# =============================================================================
# API — GET DLP POLICY
# =============================================================================


class TestGetDLPPolicyAPI:
    def test_owner_can_read(self):
        org, _, token = _create_org()
        resp = _client(token).get(f"{_BASE}/{org.pk}/dlp-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scan_patterns"] == []
        assert data["is_active"] is True

    def test_owner_can_read_with_policy(self):
        org, _, token = _create_org()
        _create_dlp_policy(org)
        resp = _client(token).get(f"{_BASE}/{org.pk}/dlp-policy")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scan_patterns"]) == len(DEFAULT_SCAN_PATTERNS)

    def test_admin_can_read(self):
        org, owner, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _client(admin_token).get(f"{_BASE}/{org.pk}/dlp-policy")
        assert resp.status_code == 200

    def test_member_rejected(self):
        org, owner, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _client(member_token).get(f"{_BASE}/{org.pk}/dlp-policy")
        assert resp.status_code == 401  # UnauthorizedAccessError

    def test_non_member_rejected(self):
        org, _, _ = _create_org()
        outsider, outsider_token = _make_user()
        resp = _client(outsider_token).get(f"{_BASE}/{org.pk}/dlp-policy")
        assert resp.status_code == 401

    def test_not_found_org(self):
        _, _, token = _create_org()
        resp = _client(token).get(
            f"{_BASE}/00000000-0000-0000-0000-000000000000/dlp-policy"
        )
        assert resp.status_code == 404


# =============================================================================
# API — PATCH DLP POLICY
# =============================================================================


class TestUpdateDLPPolicyAPI:
    def test_owner_can_update_patterns(self):
        org, _, token = _create_org()
        new_patterns = [
            {"name": "Test Pattern", "regex": r"\bTEST\b", "action": "redact"},
        ]
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"scan_patterns": new_patterns},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["scan_patterns"]) == 1
        assert data["scan_patterns"][0]["name"] == "Test Pattern"

    def test_update_creates_policy_with_defaults_if_none(self):
        org, _, token = _create_org()
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"is_active": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_active"] is False
        # Should have been created with default patterns
        assert len(data["scan_patterns"]) == len(DEFAULT_SCAN_PATTERNS)

    def test_toggle_active(self):
        org, _, token = _create_org()
        _create_dlp_policy(org)
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_invalid_regex_returns_400(self):
        org, _, token = _create_org()
        bad_patterns = [
            {"name": "Bad", "regex": "[invalid(", "action": "block"},
        ]
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"scan_patterns": bad_patterns},
        )
        assert resp.status_code == 400
        assert "Invalid regex" in resp.json()["detail"]

    def test_invalid_action_returns_400(self):
        org, _, token = _create_org()
        bad_patterns = [
            {"name": "Bad", "regex": r"\btest\b", "action": "warn"},
        ]
        resp = _patch(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"scan_patterns": bad_patterns},
        )
        assert resp.status_code == 400
        assert "Invalid action" in resp.json()["detail"]

    def test_member_rejected(self):
        org, owner, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _patch(
            _client(member_token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"is_active": False},
        )
        assert resp.status_code == 401

    def test_admin_can_update(self):
        org, owner, _ = _create_org()
        admin, admin_token = _add_member(org, OrganizationRole.ADMIN)
        resp = _patch(
            _client(admin_token),
            f"{_BASE}/{org.pk}/dlp-policy",
            {"is_active": False},
        )
        assert resp.status_code == 200


# =============================================================================
# API — TEST DLP POLICY
# =============================================================================


class TestDLPTestAPI:
    def test_no_policy_no_matches(self):
        org, _, token = _create_org()
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy/test",
            {"text": "My SSN is 123-45-6789"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matches"] == []
        assert data["would_block"] is False
        assert data["redacted_text"] == "My SSN is 123-45-6789"

    def test_block_pattern_detected(self):
        org, _, token = _create_org()
        _create_dlp_policy(org)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy/test",
            {"text": "My SSN is 123-45-6789"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["would_block"] is True
        assert data["block_pattern"] == "SSN / Tax ID"

    def test_redact_pattern_detected(self):
        org, _, token = _create_org()
        _create_dlp_policy(org)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy/test",
            {"text": "My card is 4111111111111111"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["would_block"] is False
        assert "[REDACTED]" in data["redacted_text"]
        cc_match = next(
            m for m in data["matches"] if m["pattern_name"] == "Credit Card Number"
        )
        assert cc_match["matched"] is True

    def test_clean_text_no_matches(self):
        org, _, token = _create_org()
        _create_dlp_policy(org)
        resp = _post(
            _client(token),
            f"{_BASE}/{org.pk}/dlp-policy/test",
            {"text": "Hello world, how are you?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["would_block"] is False
        assert data["redacted_text"] == "Hello world, how are you?"
        assert all(not m["matched"] for m in data["matches"])

    def test_member_rejected(self):
        org, owner, _ = _create_org()
        member, member_token = _add_member(org, OrganizationRole.MEMBER)
        resp = _post(
            _client(member_token),
            f"{_BASE}/{org.pk}/dlp-policy/test",
            {"text": "test"},
        )
        assert resp.status_code == 401
