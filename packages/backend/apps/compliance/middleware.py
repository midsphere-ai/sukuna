"""Audit middleware for request-level compliance logging.

Captures every mutating API request (POST, PUT, PATCH, DELETE) into the
immutable AuditLog, recording actor, IP, request ID, HTTP method, path,
and response status code.
"""

import logging
import time

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin

from .models import AuditLog

logger = logging.getLogger(__name__)

# HTTP methods that mutate state — only these are audit-logged
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths that should never generate audit entries (health checks, static, admin assets)
_EXEMPT_PATH_PREFIXES = (
    "/static/",
    "/media/",
    "/health/",
    "/live/",
    "/ready/",
    f"/{getattr(settings, 'ADMIN_URL', 'admin/')}".rstrip("/") + "/jsi18n/",
)


def get_client_ip(request) -> str | None:
    """Extract the real client IP, respecting X-Forwarded-For from reverse proxies."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditMiddleware(MiddlewareMixin):
    """Logs mutating API requests to the immutable AuditLog.

    Placement: AFTER AuthenticationMiddleware and RequestIdMiddleware so that
    ``request.user`` and ``request.request_id`` are both available.

    Only logs requests whose method is in ``_MUTATING_METHODS`` and whose
    path starts with ``/api/``. This keeps the audit log focused on actual
    business operations rather than static asset fetches or admin browsing.
    """

    def process_request(self, request):
        """Stamp the request start time for duration tracking."""
        request._audit_start = time.monotonic()

    def process_response(self, request, response):
        """Create an AuditLog entry for mutating API requests."""
        try:
            self._maybe_log(request, response)
        except Exception:
            logger.exception("AuditMiddleware failed to log request")
        return response

    def _maybe_log(self, request, response):
        """Conditionally log the request to AuditLog."""
        method = request.method

        # Only audit mutating methods
        if method not in _MUTATING_METHODS:
            return

        path = request.path

        # Only audit API endpoints
        if not path.startswith("/api/"):
            return

        # Skip exempt paths
        for prefix in _EXEMPT_PATH_PREFIXES:
            if path.startswith(prefix):
                return

        # Determine actor
        user = getattr(request, "user", None)
        is_authenticated = user is not None and getattr(user, "is_authenticated", False)

        actor_id = user.pk if is_authenticated else None
        actor_email = getattr(user, "email", "") if is_authenticated else ""

        # Build metadata
        duration_ms = None
        start = getattr(request, "_audit_start", None)
        if start is not None:
            duration_ms = round((time.monotonic() - start) * 1000)

        metadata = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "query_string": request.META.get("QUERY_STRING", ""),
        }
        if duration_ms is not None:
            metadata["duration_ms"] = duration_ms

        content_type = request.content_type or ""
        if content_type:
            metadata["content_type"] = content_type

        # Determine resource_type and resource_id from the URL path
        resource_type, resource_id = self._parse_resource(path)

        # Map HTTP method to audit action
        action = self._method_to_action(method, response.status_code)

        AuditLog.log(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            actor_id=actor_id,
            actor_email=actor_email,
            actor_ip=get_client_ip(request),
            request_id=getattr(request, "request_id", ""),
            metadata=metadata,
        )

    @staticmethod
    def _method_to_action(method: str, status_code: int) -> str:
        """Map an HTTP method + status to a semantic audit action."""
        if status_code >= 400:
            # Failed requests still get logged but with a descriptive action
            return f"{method.lower()}_failed"
        return {
            "POST": "create",
            "PUT": "update",
            "PATCH": "update",
            "DELETE": "delete",
        }.get(method, method.lower())

    @staticmethod
    def _parse_resource(path: str) -> tuple[str, str]:
        """Extract resource_type and resource_id from an API path.

        Examples:
            /api/v1/chat/completions/start → ("chat.completions.start", "")
            /api/v1/users/me              → ("users.me", "")
            /api/v1/spaces/abc-123/files  → ("spaces.files", "abc-123")

        Strategy: strip /api/v1/ prefix, then use the path segments.
        If a segment looks like an ID (UUID, numeric, or short-id), treat it as resource_id.
        """
        # Strip /api/ prefix and version segment
        stripped = path.strip("/")
        parts = stripped.split("/")

        # Remove "api" and version prefix (e.g., "v1")
        if len(parts) >= 2 and parts[0] == "api":
            parts = parts[1:]  # drop "api"
        if parts and parts[0].startswith("v"):
            parts = parts[1:]  # drop version

        if not parts:
            return ("unknown", "")

        # Separate path segments into "type" segments and potential ID
        type_parts = []
        resource_id = ""

        for part in parts:
            if _looks_like_id(part):
                resource_id = part
            else:
                type_parts.append(part)

        resource_type = ".".join(type_parts) if type_parts else "unknown"
        return (resource_type, resource_id)


def _looks_like_id(segment: str) -> bool:
    """Heuristic: is this path segment likely a resource ID?"""
    # Pure numeric
    if segment.isdigit():
        return True
    # UUID (with or without dashes)
    if len(segment) == 36 and segment.count("-") == 4:
        return True
    if len(segment) == 32 and segment.isalnum():
        return True
    # Short UUID / base64 IDs (8-22 chars, contains digits)
    if (
        8 <= len(segment) <= 22
        and any(c.isdigit() for c in segment)
        and not segment.startswith(
            ("me", "start", "stream", "export", "inject", "hitl", "cancel")
        )
    ):
        return True
    return False
