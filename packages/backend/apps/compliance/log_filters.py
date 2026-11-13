"""PII redaction filter for Python logging.

Scans log messages, extra fields, and exception tracebacks for personally
identifiable information (PII) and replaces matches with masked placeholders.

Detected patterns:
- Email addresses  → [EMAIL REDACTED]
- IPv4 / IPv6      → [IP REDACTED]
- API keys / tokens → [API_KEY REDACTED]
- Credit card nums  → [CARD REDACTED]

The filter operates as a standard ``logging.Filter`` so it can be attached
to any handler in the Django LOGGING configuration.
"""

import logging
import re

# ---------------------------------------------------------------------------
# Compiled patterns — order matters (more specific first)
# ---------------------------------------------------------------------------

# Email: standard addr-spec (simplified RFC 5321)
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
)

# IPv4 — four dotted octets (avoid matching version numbers like "5.1.0")
# Require at least one octet > 255-range check OR contextual hints.
# We accept any four-octet pattern and rely on placement in log messages.
_IPV4_RE = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
)

# IPv6 — full and common compressed forms
_IPV6_RE = re.compile(
    r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"  # full
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b"  # trailing ::
    r"|(?:^|(?<=\s))::(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}\b"  # leading :: (incl ::1)
    r"|\b(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b",  # middle ::
)

# API keys / bearer tokens — long hex, base64-ish, or sk-/pk- prefixed strings
_API_KEY_RE = re.compile(
    r"\b(?:sk|pk|api|key|token|bearer)[_\-]?[a-zA-Z0-9\-_]{20,}\b",
    re.IGNORECASE,
)

# Credit-card-shaped numbers (13-19 digits, optional separators)
_CARD_RE = re.compile(
    r"\b(?:\d[ \-]?){13,19}\b",
)

# Mapping: (compiled pattern, replacement placeholder)
_PII_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_EMAIL_RE, "[EMAIL REDACTED]"),
    (_IPV6_RE, "[IP REDACTED]"),
    (_IPV4_RE, "[IP REDACTED]"),
    (_API_KEY_RE, "[API_KEY REDACTED]"),
    (_CARD_RE, "[CARD REDACTED]"),
]

# Fields in LogRecord.extra / __dict__ that commonly carry PII and should
# be redacted when found as string values.
_SENSITIVE_FIELD_NAMES = frozenset(
    {
        "email",
        "user_email",
        "actor_email",
        "ip",
        "ip_address",
        "actor_ip",
        "client_ip",
        "remote_addr",
        "api_key",
        "token",
        "password",
        "secret",
        "authorization",
    }
)


def redact(text: str) -> str:
    """Apply all PII redaction patterns to *text* and return the result."""
    for pattern, placeholder in _PII_PATTERNS:
        text = pattern.sub(placeholder, text)
    return text


def redact_value(value: object) -> object:
    """Recursively redact PII from strings, dicts, and lists."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(item) for item in value)
    return value


def redact_by_field_name(key: str, value: object) -> object:
    """If *key* is a known-sensitive field name, fully mask the value."""
    if key.lower() in _SENSITIVE_FIELD_NAMES and isinstance(value, str) and value:
        return f"[{key.upper()} REDACTED]"
    return value


class PIIRedactionFilter(logging.Filter):
    """Logging filter that scrubs PII from messages and record attributes.

    Attach to handlers via the Django LOGGING config::

        "filters": {
            "pii_redaction": {
                "()": "apps.compliance.log_filters.PIIRedactionFilter",
            },
        }

    The filter mutates the LogRecord in place so *all* downstream handlers
    and formatters see the redacted version.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # 1. Redact the formatted message
        if record.args:
            # Format the message first, then redact the result.
            record.msg = redact(record.getMessage())
            record.args = None
        elif isinstance(record.msg, str):
            record.msg = redact(record.msg)

        # 2. Redact exception info
        if record.exc_text:
            record.exc_text = redact(record.exc_text)

        # 3. Redact known-sensitive attributes on the record
        for attr in list(record.__dict__):
            if attr.startswith("_"):
                continue
            val = getattr(record, attr, None)
            if isinstance(val, str) and attr in _SENSITIVE_FIELD_NAMES:
                setattr(record, attr, f"[{attr.upper()} REDACTED]")
            elif isinstance(val, str) and val:
                setattr(record, attr, redact(val))
            elif isinstance(val, dict):
                setattr(record, attr, _redact_dict(val))

        return True


def _redact_dict(d: dict) -> dict:
    """Redact PII in a dictionary — both by value patterns and field names."""
    result = {}
    for k, v in d.items():
        v = redact_by_field_name(k, v)
        v = redact_value(v)
        result[k] = v
    return result
