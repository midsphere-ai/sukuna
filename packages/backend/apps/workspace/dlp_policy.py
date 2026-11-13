"""DLP (Data Loss Prevention) policy enforcement.

Scans outgoing message content against organization-level DLP patterns
before proxying to the sandbox. Supports two actions:
- block: reject the message entirely (HTTP 400)
- redact: replace matched text with [REDACTED]

Only applies to org project conversations, not personal ones.
Binary files (images, PDFs) are NOT scanned — only text content.
"""

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

# Default patterns seeded when an org creates a DLP policy.
DEFAULT_SCAN_PATTERNS = [
    {
        "name": "Credit Card Number",
        "regex": r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b",
        "action": "redact",
    },
    {
        "name": "SSN / Tax ID",
        "regex": r"\b\d{3}-\d{2}-\d{4}\b",
        "action": "block",
    },
    {
        "name": "AWS Access Key",
        "regex": r"\bAKIA[0-9A-Z]{16}\b",
        "action": "block",
    },
    {
        "name": "Private Key",
        "regex": r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
        "action": "block",
    },
    {
        "name": "Common API Key Pattern",
        "regex": r"\b(?:sk|pk|api|key|token|secret|password)[-_][a-zA-Z0-9]{20,}\b",
        "action": "redact",
    },
]


class DLPBlockError(Exception):
    """Raised when a DLP pattern with action=block matches."""

    def __init__(self, pattern_name: str):
        self.pattern_name = pattern_name
        super().__init__(f"Message blocked by DLP policy: {pattern_name}")


class DLPScanResult:
    """Result of scanning text against DLP patterns."""

    __slots__ = ("blocked", "block_pattern_name", "redacted_text", "redactions")

    def __init__(self):
        self.blocked: bool = False
        self.block_pattern_name: str = ""
        self.redacted_text: str = ""
        self.redactions: list[dict] = []  # [{name, action}]


def scan_text(text: str, patterns: list[dict]) -> DLPScanResult:
    """Scan text against a list of DLP patterns.

    Args:
        text: The message content to scan.
        patterns: List of {name, regex, action} dicts.

    Returns:
        DLPScanResult with blocked flag, redacted text, and match details.
    """
    result = DLPScanResult()
    result.redacted_text = text

    if not text or not patterns:
        return result

    for pattern in patterns:
        name = pattern.get("name", "Unknown")
        regex = pattern.get("regex", "")
        action = pattern.get("action", "redact")

        if not regex:
            continue

        try:
            compiled = re.compile(regex)
        except re.error:
            logger.warning("DLP: invalid regex for pattern %r, skipping", name)
            continue

        if not compiled.search(result.redacted_text):
            continue

        if action == "block":
            result.blocked = True
            result.block_pattern_name = name
            result.redactions.append({"name": name, "action": "block"})
            return result

        # redact
        result.redacted_text = compiled.sub("[REDACTED]", result.redacted_text)
        result.redactions.append({"name": name, "action": "redact"})

    return result


def get_dlp_policy_for_conversation(conv):
    """Return the DLPPolicy for a conversation's org, or None.

    Personal projects (no project or no org) return None.
    Inactive policies return None.
    """
    project = getattr(conv, "project", None)
    if project is None:
        return None

    org = getattr(project, "organization", None)
    if org is None:
        return None

    from apps.workspace.models import DLPPolicy

    try:
        policy = org.dlp_policy
    except DLPPolicy.DoesNotExist:
        return None

    if not policy.is_active:
        return None

    return policy


def apply_dlp_scan(
    text: str,
    conv,
    *,
    actor_id=None,
    actor_email: str = "",
    actor_ip: str | None = None,
    request_id: str = "",
) -> str:
    """Apply DLP scan to message text for a conversation.

    Returns:
        The (possibly redacted) text.

    Raises:
        DLPBlockError: If a block-action pattern matches.
    """
    policy = get_dlp_policy_for_conversation(conv)
    if policy is None:
        return text

    result = scan_text(text, policy.scan_patterns or [])

    if not result.redactions:
        return text

    # Log each DLP action to audit log
    _log_dlp_actions(
        result=result,
        text=text,
        conv=conv,
        policy=policy,
        actor_id=actor_id,
        actor_email=actor_email,
        actor_ip=actor_ip,
        request_id=request_id,
    )

    if result.blocked:
        raise DLPBlockError(result.block_pattern_name)

    return result.redacted_text


def _log_dlp_actions(
    *,
    result: DLPScanResult,
    text: str,
    conv,
    policy,
    actor_id,
    actor_email: str,
    actor_ip: str | None,
    request_id: str,
):
    """Create audit log entries for DLP matches.

    Logs the pattern name and a hash of the message — NOT the sensitive content.
    """
    from apps.compliance.models import AuditAction, AuditLog

    message_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    for redaction in result.redactions:
        action = (
            AuditAction.DLP_BLOCK
            if redaction["action"] == "block"
            else AuditAction.DLP_REDACT
        )
        try:
            AuditLog.log(
                action=action,
                resource_type="conversation",
                resource_id=str(conv.id),
                actor_id=actor_id,
                actor_email=actor_email,
                actor_ip=actor_ip,
                request_id=request_id,
                metadata={
                    "organization_id": str(policy.organization_id),
                    "pattern_name": redaction["name"],
                    "message_hash": message_hash,
                },
            )
        except Exception:
            logger.exception(
                "Failed to log DLP action for pattern %s", redaction["name"]
            )
