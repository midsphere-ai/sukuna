"""DLP (Data Loss Prevention) scan for outgoing agent messages.

Ported from ``backend/apps/workspace/dlp_policy.py``. Scans the user's task
against organization-level DLP patterns before the agent kicks off. Each
pattern can block the run (HTTP 400) or redact the matched substring.

Only applies to org-scoped conversations (conversation linked to a project
whose ``organization_id`` is set, and the org has an active DLPPolicy).
Personal conversations bypass DLP entirely.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid

logger = logging.getLogger("agent_server.dlp")


# Mirrors of ``apps.compliance.models.AuditAction`` choices used by DLP.
DLP_BLOCK = "dlp_block"
DLP_REDACT = "dlp_redact"


class DLPBlockError(Exception):
    """Raised when a DLP pattern with action=block matches."""

    def __init__(self, pattern_name: str):
        self.pattern_name = pattern_name
        super().__init__(f"Message blocked by DLP policy: {pattern_name}")


class DLPScanResult:
    __slots__ = ("blocked", "block_pattern_name", "redacted_text", "redactions")

    def __init__(self):
        self.blocked: bool = False
        self.block_pattern_name: str = ""
        self.redacted_text: str = ""
        self.redactions: list[dict] = []


def scan_text(text: str, patterns: list[dict]) -> DLPScanResult:
    """Scan text against a list of ``{name, regex, action}`` dicts."""
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
        result.redacted_text = compiled.sub("[REDACTED]", result.redacted_text)
        result.redactions.append({"name": name, "action": "redact"})

    return result


def _get_dlp_policy_for_conversation(conversation_id: str):
    """Return ``(policy, organization_id)`` or ``(None, None)``.

    Walks ``Conversation → Project → Organization → DLPPolicy`` via shadow
    ORMs. Returns ``(None, None)`` for personal conversations, missing
    projects/orgs, or inactive policies.
    """
    from agent_server.models import (
        DjangoConversation,
        DjangoDLPPolicy,
        DjangoProject,
    )

    conv = DjangoConversation.objects.filter(id=conversation_id).first()
    if conv is None or not getattr(conv, "project_id", None):
        return None, None

    project = DjangoProject.objects.filter(id=conv.project_id).first()
    if project is None or not project.organization_id:
        return None, None

    policy = DjangoDLPPolicy.objects.filter(
        organization_id=project.organization_id,
        is_active=True,
    ).first()
    if policy is None:
        return None, None
    return policy, project.organization_id


def apply_dlp_scan(
    text: str,
    *,
    conversation_id: str,
    actor_id=None,
    actor_email: str = "",
    actor_ip: str | None = None,
    request_id: str = "",
) -> str:
    """Apply DLP scan to a message.

    Returns the (possibly redacted) text. Raises ``DLPBlockError`` when a
    block-action pattern matches.
    """
    policy, organization_id = _get_dlp_policy_for_conversation(conversation_id)
    if policy is None:
        return text

    result = scan_text(text, policy.scan_patterns or [])
    if not result.redactions:
        return text

    _log_dlp_actions(
        result=result,
        text=text,
        conversation_id=conversation_id,
        organization_id=organization_id,
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
    conversation_id: str,
    organization_id,
    actor_id,
    actor_email: str,
    actor_ip: str | None,
    request_id: str,
) -> None:
    """Write an AuditLog row per DLP match.

    Logs the pattern name and a truncated hash of the message — never the
    sensitive content itself. Exceptions are swallowed so a logging failure
    cannot abort the run.
    """
    from agent_server.models import DjangoAuditLog

    message_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

    for redaction in result.redactions:
        action = DLP_BLOCK if redaction["action"] == "block" else DLP_REDACT
        try:
            DjangoAuditLog.objects.create(
                id=uuid.uuid4(),
                action=action,
                resource_type="conversation",
                resource_id=str(conversation_id),
                actor_id=actor_id,
                actor_email=actor_email or "",
                actor_ip=actor_ip,
                request_id=request_id or "",
                changes={},
                metadata={
                    "organization_id": str(organization_id),
                    "pattern_name": redaction["name"],
                    "message_hash": message_hash,
                },
            )
        except Exception:
            logger.exception("Failed to log DLP action for pattern %s", redaction["name"])
