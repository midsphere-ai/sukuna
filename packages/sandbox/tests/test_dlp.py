"""Unit tests for the sandbox-side DLP scan (packages/sandbox/agent_server/infra/dlp.py).

Covers only the pure-Python ``scan_text`` function; the policy lookup + audit
log writes hit the shared Postgres and are covered by integration tests on
the backend side.
"""

from __future__ import annotations

import pytest

from agent_server.infra.dlp import DLPBlockError, scan_text


def test_scan_text_empty_inputs_return_unchanged() -> None:
    assert scan_text("", [{"name": "X", "regex": r".+", "action": "block"}]).redacted_text == ""
    result = scan_text("hello", [])
    assert result.redacted_text == "hello"
    assert result.redactions == []
    assert result.blocked is False


def test_scan_text_block_action_halts_and_reports() -> None:
    patterns = [
        {"name": "SSN", "regex": r"\b\d{3}-\d{2}-\d{4}\b", "action": "block"},
    ]
    result = scan_text("my ssn is 123-45-6789", patterns)
    assert result.blocked is True
    assert result.block_pattern_name == "SSN"
    assert result.redactions == [{"name": "SSN", "action": "block"}]


def test_scan_text_redact_substitutes_and_continues() -> None:
    patterns = [
        {"name": "API", "regex": r"\bsk_[a-zA-Z0-9]{20,}\b", "action": "redact"},
        {"name": "SSN", "regex": r"\b\d{3}-\d{2}-\d{4}\b", "action": "redact"},
    ]
    result = scan_text("token=sk_1234567890abcdef12345678 id=111-22-3333", patterns)  # gitleaks:allow
    assert result.blocked is False
    assert "[REDACTED]" in result.redacted_text
    assert "sk_" not in result.redacted_text
    assert "111-22-3333" not in result.redacted_text
    names = {r["name"] for r in result.redactions}
    assert names == {"API", "SSN"}


def test_scan_text_block_after_redact_short_circuits() -> None:
    patterns = [
        {"name": "redact_me", "regex": r"alpha", "action": "redact"},
        {"name": "block_me", "regex": r"beta", "action": "block"},
        {"name": "never_reached", "regex": r"gamma", "action": "redact"},
    ]
    result = scan_text("alpha beta gamma", patterns)
    assert result.blocked is True
    assert result.block_pattern_name == "block_me"
    # The redact for alpha ran first, block short-circuits after
    assert result.redacted_text.startswith("[REDACTED]")
    # gamma never reached
    names = [r["name"] for r in result.redactions]
    assert "never_reached" not in names


def test_scan_text_invalid_regex_is_skipped() -> None:
    patterns = [
        {"name": "bad", "regex": r"[unclosed", "action": "block"},
        {"name": "good", "regex": r"secret", "action": "redact"},
    ]
    result = scan_text("the secret value", patterns)
    assert result.blocked is False
    assert "secret" not in result.redacted_text
    assert [r["name"] for r in result.redactions] == ["good"]


def test_dlp_block_error_carries_pattern_name() -> None:
    with pytest.raises(DLPBlockError) as excinfo:
        raise DLPBlockError("SSN")
    assert excinfo.value.pattern_name == "SSN"
    assert "SSN" in str(excinfo.value)
