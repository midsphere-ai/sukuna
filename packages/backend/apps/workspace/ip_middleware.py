"""IP allowlist and conditional access enforcement middleware.

Checks incoming requests against per-org IP allowlists and conditional access
policies. Only enforced on org-scoped API paths
(``/api/v1/workspace/organizations/{org_id}/...``).
Personal space and non-org API calls are never blocked.

Placement: AFTER AuthenticationMiddleware so ``request.user`` is available.
"""

import ipaddress
import logging
import re
from datetime import datetime

from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Matches /api/v1/workspace/organizations/{uuid}/... to extract org_id.
_ORG_PATH_RE = re.compile(
    r"^/api/v1/workspace/organizations/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
    r"(/|$)",
    re.IGNORECASE,
)

# Configurable trusted proxy depth (how many X-Forwarded-For entries to trust).
_TRUSTED_PROXY_DEPTH = 1


def get_client_ip(request) -> str | None:
    """Extract the client IP, respecting X-Forwarded-For with trusted proxy depth."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        parts = [p.strip() for p in xff.split(",")]
        # Trust the last N entries (where N = trusted proxy depth)
        idx = max(0, len(parts) - _TRUSTED_PROXY_DEPTH)
        return parts[idx]
    return request.META.get("REMOTE_ADDR")


def ip_in_cidrs(ip_str: str, cidrs: list[str]) -> bool:
    """Check whether *ip_str* falls within any of the given CIDR ranges."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


class IPAllowlistMiddleware(MiddlewareMixin):
    """Enforce per-org IP allowlists on org-scoped API requests.

    - If an org has zero active IP allowlist entries → no restriction.
    - If an org has ≥1 active entries → request IP must match at least one.
    - Non-org requests are always allowed.
    """

    def process_request(self, request):
        try:
            return self._enforce(request)
        except Exception:
            logger.exception("IPAllowlistMiddleware error")
            return None

    def _enforce(self, request):
        path = request.path

        # Only check org-scoped API paths
        match = _ORG_PATH_RE.match(path)
        if not match:
            return None

        org_id = match.group(1)

        # Lazy import to avoid circular dependencies at module load
        from apps.workspace.models import IPAllowlistEntry

        # Fetch active CIDR entries for this org
        active_cidrs = list(
            IPAllowlistEntry.objects.filter(
                organization_id=org_id,
                is_active=True,
            ).values_list("cidr_range", flat=True)
        )

        # No active entries → no restriction
        if not active_cidrs:
            return None

        client_ip = get_client_ip(request)
        if client_ip and ip_in_cidrs(client_ip, active_cidrs):
            return None

        # Blocked — log the attempt
        try:
            from apps.compliance.models import AuditLog

            user = getattr(request, "user", None)
            is_auth = user is not None and getattr(user, "is_authenticated", False)
            AuditLog.log(
                action="ip_access_blocked",
                resource_type="organization",
                resource_id=org_id,
                actor_id=user.pk if is_auth else None,
                actor_email=getattr(user, "email", "") if is_auth else "",
                actor_ip=client_ip,
                request_id=getattr(request, "request_id", ""),
                metadata={
                    "blocked_ip": client_ip,
                    "path": path,
                },
            )
        except Exception:
            logger.exception("Failed to log IP access blocked event")

        return JsonResponse(
            {
                "detail": "Access denied: your IP address is not in this organization's allowlist.",
                "code": "ip_not_allowed",
            },
            status=403,
        )


def _check_ip_range(cond: dict, client_ip: str | None) -> bool:
    """Check if client IP falls within the condition's CIDR range."""
    cidr = cond.get("cidr", "")
    if not client_ip or not cidr:
        return False
    return ip_in_cidrs(client_ip, [cidr])


def _check_time_of_day(cond: dict) -> bool:
    """Check if current time is within start_hour..end_hour in the given timezone."""
    import zoneinfo

    start = cond.get("start_hour", 0)
    end = cond.get("end_hour", 23)
    tz_name = cond.get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = zoneinfo.ZoneInfo("UTC")

    now = datetime.now(tz)
    hour = now.hour

    if start <= end:
        return start <= hour <= end
    else:
        # Wraps midnight, e.g., 22..6 means 22,23,0,1,2,3,4,5,6
        return hour >= start or hour <= end


def _check_day_of_week(cond: dict) -> bool:
    """Check if current day matches the condition's days list (0=Mon, 6=Sun)."""
    import zoneinfo

    days = cond.get("days", [])
    tz_name = cond.get("timezone", "UTC")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except (KeyError, Exception):
        tz = zoneinfo.ZoneInfo("UTC")

    now = datetime.now(tz)
    return now.weekday() in days


def _check_user_agent(cond: dict, user_agent: str) -> bool:
    """Check if user agent matches the condition's regex pattern."""
    pattern = cond.get("pattern", "")
    if not pattern:
        return False
    try:
        return bool(re.search(pattern, user_agent))
    except re.error:
        return False


def evaluate_conditions(
    conditions: list[dict], client_ip: str | None, user_agent: str
) -> bool:
    """Evaluate all conditions (AND logic). Returns True if all conditions match."""
    for cond in conditions:
        ctype = cond.get("type", "")
        if ctype == "ip_range":
            if not _check_ip_range(cond, client_ip):
                return False
        elif ctype == "time_of_day":
            if not _check_time_of_day(cond):
                return False
        elif ctype == "day_of_week":
            if not _check_day_of_week(cond):
                return False
        elif ctype == "user_agent_pattern":
            if not _check_user_agent(cond, user_agent):
                return False
    return True


class ConditionalAccessMiddleware(MiddlewareMixin):
    """Enforce conditional access policies on org-scoped API requests.

    - Active policies are evaluated in priority order (ascending).
    - First matching policy determines the action.
    - action=block → 403
    - action=require_mfa → 403 if MFA not verified (same as security middleware)
    - action=allow → pass through
    - No matching policy → pass through (default allow)
    """

    def process_request(self, request):
        try:
            return self._enforce(request)
        except Exception:
            logger.exception("ConditionalAccessMiddleware error")
            return None

    def _enforce(self, request):
        path = request.path
        match = _ORG_PATH_RE.match(path)
        if not match:
            return None

        org_id = match.group(1)

        from apps.workspace.models import ConditionalAccessPolicy

        policies = list(
            ConditionalAccessPolicy.objects.filter(
                organization_id=org_id,
                is_active=True,
            ).order_by("priority", "created_at")
        )

        if not policies:
            return None

        client_ip = get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")

        for policy in policies:
            if evaluate_conditions(policy.conditions, client_ip, user_agent):
                if policy.action == "allow":
                    return None
                elif policy.action == "block":
                    self._log_block(request, org_id, client_ip, policy)
                    return JsonResponse(
                        {
                            "detail": f"Access blocked by conditional access policy: {policy.name}",
                            "code": "access_policy_blocked",
                        },
                        status=403,
                    )
                elif policy.action == "require_mfa":
                    session = getattr(request, "session", None)
                    if not session or not session.get("mfa_verified"):
                        return JsonResponse(
                            {
                                "detail": f"MFA required by conditional access policy: {policy.name}",
                                "code": "mfa_required",
                            },
                            status=403,
                        )
                    return None

        # No matching policy — default allow
        return None

    def _log_block(self, request, org_id, client_ip, policy):
        try:
            from apps.compliance.models import AuditLog

            user = getattr(request, "user", None)
            is_auth = user is not None and getattr(user, "is_authenticated", False)
            AuditLog.log(
                action="access_policy_blocked",
                resource_type="access_policy",
                resource_id=str(policy.pk),
                actor_id=user.pk if is_auth else None,
                actor_email=getattr(user, "email", "") if is_auth else "",
                actor_ip=client_ip,
                request_id=getattr(request, "request_id", ""),
                metadata={
                    "organization_id": org_id,
                    "policy_name": policy.name,
                    "path": request.path,
                    "blocked_ip": client_ip,
                },
            )
        except Exception:
            logger.exception("Failed to log access policy block event")
