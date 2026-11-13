"""Tests for PII log redaction filter and StructuredJsonFormatter integration."""

import json
import logging

import pytest

from apps.compliance.log_filters import (
    PIIRedactionFilter,
    _redact_dict,
    redact,
    redact_by_field_name,
    redact_value,
)
from config.logging import StructuredJsonFormatter

# ===========================================================================
# redact() — pattern-based text redaction
# ===========================================================================


class TestRedactFunction:
    """Tests for the standalone ``redact()`` function."""

    # --- Emails ---

    def test_email_simple(self):
        assert redact("user@example.com") == "[EMAIL REDACTED]"

    def test_email_in_sentence(self):
        result = redact("Contact alice.bob+tag@sub.example.co.uk for info.")
        assert "[EMAIL REDACTED]" in result
        assert "alice" not in result

    def test_multiple_emails(self):
        text = "From a@x.com to b@y.org cc c@z.io"
        result = redact(text)
        assert result.count("[EMAIL REDACTED]") == 3

    def test_email_with_plus_and_dots(self):
        assert "[EMAIL REDACTED]" in redact("test.user+alias@gmail.com")

    # --- IPv4 ---

    def test_ipv4_simple(self):
        assert redact("192.168.1.100") == "[IP REDACTED]"

    def test_ipv4_in_log_message(self):
        msg = "Client connected from 10.0.0.1 on port 443"
        result = redact(msg)
        assert "10.0.0.1" not in result
        assert "[IP REDACTED]" in result

    def test_multiple_ipv4(self):
        text = "Forwarded: 1.2.3.4, 10.0.0.1, 172.16.0.1"
        result = redact(text)
        assert result.count("[IP REDACTED]") == 3

    # --- IPv6 ---

    def test_ipv6_full(self):
        result = redact("addr=2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        assert "2001" not in result
        assert "[IP REDACTED]" in result

    def test_ipv6_loopback(self):
        result = redact("from ::1 connected")
        assert "[IP REDACTED]" in result

    # --- API keys ---

    def test_api_key_sk_prefix(self):
        result = redact("key=sk-abcdef1234567890abcdef1234567890")  # gitleaks:allow
        assert "abcdef" not in result
        assert "[API_KEY REDACTED]" in result

    def test_api_key_bearer(self):
        result = redact("Authorization: bearer_abc123def456ghi789jkl012mno")
        assert "[API_KEY REDACTED]" in result

    def test_api_key_token_prefix(self):
        result = redact("using token_abcdefghijklmnopqrstuvwxyz")
        assert "[API_KEY REDACTED]" in result

    # --- Credit cards ---

    def test_credit_card_no_separator(self):
        result = redact("card: 4111111111111111")
        assert "4111" not in result
        assert "[CARD REDACTED]" in result

    def test_credit_card_with_dashes(self):
        result = redact("card 4111-1111-1111-1111 charged")
        assert "[CARD REDACTED]" in result

    # --- No false positives on innocent text ---

    def test_no_redaction_plain_text(self):
        text = "This is a normal log message with no PII."
        assert redact(text) == text

    def test_no_redaction_short_numbers(self):
        text = "Processed 42 items in 3.14 seconds."
        assert redact(text) == text

    # --- Multiple pattern types in one string ---

    def test_mixed_pii(self):
        text = "User admin@corp.com from 10.0.0.1 with key sk-aaaa1111bbbb2222cccc3333dddd4444"
        result = redact(text)
        assert "admin@corp.com" not in result
        assert "10.0.0.1" not in result
        assert "sk-aaaa" not in result
        assert "[EMAIL REDACTED]" in result
        assert "[IP REDACTED]" in result
        assert "[API_KEY REDACTED]" in result


# ===========================================================================
# redact_value() — recursive redaction
# ===========================================================================


class TestRedactValue:
    def test_string(self):
        assert redact_value("user@test.com") == "[EMAIL REDACTED]"

    def test_dict(self):
        result = redact_value({"msg": "ip is 10.0.0.1"})
        assert result == {"msg": "ip is [IP REDACTED]"}

    def test_nested_dict(self):
        data = {"outer": {"inner": "contact admin@x.com"}}
        result = redact_value(data)
        assert "admin@x.com" not in str(result)

    def test_list(self):
        result = redact_value(["a@b.com", "clean"])
        assert result == ["[EMAIL REDACTED]", "clean"]

    def test_tuple(self):
        result = redact_value(("a@b.com", "clean"))
        assert isinstance(result, tuple)
        assert result[0] == "[EMAIL REDACTED]"

    def test_int_passthrough(self):
        assert redact_value(42) == 42

    def test_none_passthrough(self):
        assert redact_value(None) is None


# ===========================================================================
# redact_by_field_name() — field-name-based masking
# ===========================================================================


class TestRedactByFieldName:
    def test_known_field_masked(self):
        assert redact_by_field_name("email", "user@test.com") == "[EMAIL REDACTED]"

    def test_known_field_case_insensitive(self):
        assert redact_by_field_name("Email", "user@test.com") == "[EMAIL REDACTED]"

    def test_known_field_actor_ip(self):
        assert redact_by_field_name("actor_ip", "10.0.0.1") == "[ACTOR_IP REDACTED]"

    def test_known_field_password(self):
        assert redact_by_field_name("password", "s3cret!") == "[PASSWORD REDACTED]"

    def test_known_field_api_key(self):
        assert redact_by_field_name("api_key", "sk-abc123") == "[API_KEY REDACTED]"

    def test_unknown_field_passthrough(self):
        assert redact_by_field_name("status", "active") == "active"

    def test_empty_value_passthrough(self):
        assert redact_by_field_name("email", "") == ""

    def test_non_string_passthrough(self):
        assert redact_by_field_name("email", 42) == 42


# ===========================================================================
# _redact_dict() — combined field-name + pattern redaction
# ===========================================================================


class TestRedactDict:
    def test_sensitive_field_name(self):
        result = _redact_dict({"email": "user@x.com", "status": "ok"})
        assert result["email"] == "[EMAIL REDACTED]"
        assert result["status"] == "ok"

    def test_pattern_in_value(self):
        result = _redact_dict({"message": "logged in from 10.0.0.1"})
        assert "10.0.0.1" not in result["message"]

    def test_nested_dict_in_value(self):
        result = _redact_dict({"data": {"user": "a@b.com"}})
        assert "a@b.com" not in str(result)

    def test_password_field(self):
        result = _redact_dict({"password": "hunter2", "name": "test"})
        assert result["password"] == "[PASSWORD REDACTED]"


# ===========================================================================
# PIIRedactionFilter — logging.Filter integration
# ===========================================================================


class TestPIIRedactionFilter:
    @pytest.fixture
    def pii_filter(self):
        return PIIRedactionFilter()

    @pytest.fixture
    def make_record(self):
        logger = logging.getLogger("test.pii")

        def _make(msg, *args, **kwargs):
            record = logger.makeRecord(
                "test.pii",
                logging.INFO,
                "test.py",
                1,
                msg,
                args,
                None,
                **kwargs,
            )
            return record

        return _make

    def test_redacts_email_in_message(self, pii_filter, make_record):
        record = make_record("User %s logged in", "admin@corp.com")
        pii_filter.filter(record)
        assert "admin@corp.com" not in record.getMessage()
        assert "[EMAIL REDACTED]" in record.getMessage()

    def test_redacts_ip_in_message(self, pii_filter, make_record):
        record = make_record("Request from 192.168.0.1")
        pii_filter.filter(record)
        assert "192.168.0.1" not in record.getMessage()

    def test_redacts_plain_string_msg(self, pii_filter, make_record):
        record = make_record("Error for user@test.com at 10.0.0.1")
        pii_filter.filter(record)
        msg = record.getMessage()
        assert "user@test.com" not in msg
        assert "10.0.0.1" not in msg

    def test_redacts_exc_text(self, pii_filter, make_record):
        record = make_record("error")
        record.exc_text = "Traceback: user@evil.com leaked"
        pii_filter.filter(record)
        assert "user@evil.com" not in record.exc_text
        assert "[EMAIL REDACTED]" in record.exc_text

    def test_redacts_sensitive_attribute(self, pii_filter, make_record):
        record = make_record("login event")
        record.email = "user@test.com"
        pii_filter.filter(record)
        assert record.email == "[EMAIL REDACTED]"

    def test_redacts_actor_ip_attribute(self, pii_filter, make_record):
        record = make_record("audit event")
        record.actor_ip = "203.0.113.5"
        pii_filter.filter(record)
        assert record.actor_ip == "[ACTOR_IP REDACTED]"

    def test_redacts_dict_attribute(self, pii_filter, make_record):
        record = make_record("event")
        record.context = {"email": "a@b.com", "status": "ok"}
        pii_filter.filter(record)
        assert "a@b.com" not in str(record.context)

    def test_always_returns_true(self, pii_filter, make_record):
        record = make_record("test")
        assert pii_filter.filter(record) is True

    def test_no_mutation_on_clean_message(self, pii_filter, make_record):
        record = make_record("Clean log with no PII at all")
        pii_filter.filter(record)
        assert record.getMessage() == "Clean log with no PII at all"

    def test_args_cleared_after_redaction(self, pii_filter, make_record):
        record = make_record("User %s from %s", "a@b.com", "10.0.0.1")
        pii_filter.filter(record)
        assert record.args is None
        assert "[EMAIL REDACTED]" in record.msg
        assert "[IP REDACTED]" in record.msg


# ===========================================================================
# StructuredJsonFormatter — PII redaction in JSON output
# ===========================================================================


class TestStructuredJsonFormatterRedaction:
    @pytest.fixture
    def formatter(self):
        return StructuredJsonFormatter()

    @pytest.fixture
    def make_record(self):
        logger = logging.getLogger("test.json")

        def _make(msg, *args, exc_info=None, **extra):
            record = logger.makeRecord(
                "test.json",
                logging.INFO,
                "test.py",
                1,
                msg,
                args,
                exc_info,
            )
            for k, v in extra.items():
                setattr(record, k, v)
            return record

        return _make

    def test_message_redacted(self, formatter, make_record):
        record = make_record("Login by admin@corp.com")
        output = json.loads(formatter.format(record))
        assert "admin@corp.com" not in output["message"]
        assert "[EMAIL REDACTED]" in output["message"]

    def test_extra_fields_redacted(self, formatter, make_record):
        record = make_record("event", client_ip="10.0.0.1")
        output = json.loads(formatter.format(record))
        extra = output.get("extra", {})
        assert "10.0.0.1" not in json.dumps(extra)

    def test_extra_dict_email_redacted(self, formatter, make_record):
        record = make_record("event", payload={"email": "a@b.com"})
        output = json.loads(formatter.format(record))
        assert "a@b.com" not in json.dumps(output)

    def test_exception_traceback_redacted(self, formatter, make_record):
        try:
            raise ValueError("Secret data user@evil.com exposed")
        except ValueError:
            import sys

            record = make_record("error", exc_info=sys.exc_info())

        output = json.loads(formatter.format(record))
        exc_lines = output.get("exception", [])
        combined = "".join(exc_lines)
        assert "user@evil.com" not in combined
        assert "[EMAIL REDACTED]" in combined

    def test_clean_message_unchanged(self, formatter, make_record):
        record = make_record("Normal operation completed")
        output = json.loads(formatter.format(record))
        assert output["message"] == "Normal operation completed"


# ===========================================================================
# Integration: filter in a real logging pipeline
# ===========================================================================


class TestLoggingPipelineIntegration:
    def test_filter_in_handler(self):
        """Attach PIIRedactionFilter to a handler and verify redacted output."""
        handler = logging.StreamHandler()
        handler.addFilter(PIIRedactionFilter())

        captured = []
        original_emit = handler.emit

        def capture_emit(record):
            captured.append(record)
            # Don't actually write to stderr

        handler.emit = capture_emit

        logger = logging.getLogger("test.integration.pii")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            logger.info("User admin@corp.com connected from 192.168.0.1")

            assert len(captured) == 1
            msg = captured[0].getMessage()
            assert "admin@corp.com" not in msg
            assert "192.168.0.1" not in msg
            assert "[EMAIL REDACTED]" in msg
            assert "[IP REDACTED]" in msg
        finally:
            logger.removeHandler(handler)

    def test_json_formatter_with_filter(self):
        """Full pipeline: filter + JSON formatter produces clean JSON."""
        handler = logging.StreamHandler()
        handler.addFilter(PIIRedactionFilter())
        handler.setFormatter(StructuredJsonFormatter())

        captured_output = []
        original_emit = handler.emit

        def capture_emit(record):
            captured_output.append(handler.format(record))

        handler.emit = capture_emit

        logger = logging.getLogger("test.integration.json")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        try:
            logger.info(
                "Failed auth for user@example.com from 10.0.0.1",
                extra={"actor_email": "user@example.com"},
            )

            assert len(captured_output) == 1
            output = json.loads(captured_output[0])
            full_json = json.dumps(output)

            # No PII should survive anywhere in the JSON output
            assert "user@example.com" not in full_json
            assert "10.0.0.1" not in full_json
        finally:
            logger.removeHandler(handler)
