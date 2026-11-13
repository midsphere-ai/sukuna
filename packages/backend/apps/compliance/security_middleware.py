"""Security policy middleware for SOC2 controls.

Enforces three org-level security policies on every authenticated request:

1. **MFA enforcement** — if the user belongs to an org with ``mfa_required=True``
   and has not yet enabled MFA, reject the request with 403 (except for MFA-setup,
   auth, and logout endpoints).
2. **Session timeout** — per-org or global idle timeout. If the session's last
   activity exceeds the timeout, flush the session and return 401.
3. **Concurrent session limits** — per-org or global cap on active sessions.
   When a new session exceeds the limit, the oldest sessions are evicted.
"""

import logging
import time

from django.conf import settings
from django.contrib.sessions.models import Session
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

# Paths that are always exempt from security policy enforcement.
# MFA setup must remain accessible so users can actually enable MFA.
_EXEMPT_PATH_PREFIXES = (
    "/api/v1/compliance/security-policy",
    "/api/v1/workspace/auth/sso-bypass/",
    "/api/v1/workspace/auth/saml/verify-email",
    "/accounts/",
    "/authentication/",
    "/admin/",
    "/static/",
    "/media/",
    "/health/",
    "/live/",
    "/ready/",
)

# Additional path suffixes that are exempt (MFA setup via allauth)
_EXEMPT_PATH_CONTAINS = (
    "/2fa/",
    "/mfa/",
    "/logout",
    "/login",
)


def _is_exempt(path: str) -> bool:
    """Check if the request path is exempt from security policy enforcement."""
    for prefix in _EXEMPT_PATH_PREFIXES:
        if path.startswith(prefix):
            return True
    for fragment in _EXEMPT_PATH_CONTAINS:
        if fragment in path:
            return True
    return False


def get_effective_policy(user):
    """Compute the most restrictive security policy across all user's orgs.

    Returns (mfa_required, timeout_minutes, max_sessions, sso_enforced).
    Can be called from anywhere — does not require middleware instantiation.
    """
    from apps.workspace.models import OrganizationMembership

    memberships = (
        OrganizationMembership.objects.filter(user=user)
        .select_related("organization")
        .only(
            "organization__mfa_required",
            "organization__session_timeout_minutes",
            "organization__max_concurrent_sessions",
        )
    )

    global_timeout = getattr(settings, "SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES", 1440)
    global_max_sessions = getattr(
        settings, "SECURITY_DEFAULT_MAX_CONCURRENT_SESSIONS", 5
    )

    mfa_required = False
    min_timeout = global_timeout
    min_sessions = global_max_sessions
    sso_enforced = False

    org_ids = []
    for membership in memberships:
        org = membership.organization
        org_ids.append(org.pk)
        if org.mfa_required:
            mfa_required = True
        if org.session_timeout_minutes is not None:
            min_timeout = min(min_timeout, org.session_timeout_minutes)
        if org.max_concurrent_sessions is not None:
            min_sessions = min(min_sessions, org.max_concurrent_sessions)

    # Check if any org enforces SSO
    if org_ids:
        from apps.workspace.models import SSOConfiguration

        sso_enforced = SSOConfiguration.objects.filter(
            organization_id__in=org_ids,
            is_active=True,
            enforce_sso=True,
        ).exists()

    return mfa_required, min_timeout, min_sessions, sso_enforced


class SecurityPolicyMiddleware(MiddlewareMixin):
    """Enforces MFA requirement, session timeout, and concurrent session limits.

    Placement: AFTER AuthenticationMiddleware and AuditMiddleware so that
    ``request.user`` is available and audit records are written even for
    rejected requests.
    """

    def process_request(self, request):
        """Check security policies before the view runs."""
        try:
            return self._enforce(request)
        except Exception:
            # Never break the request cycle
            logger.exception("SecurityPolicyMiddleware error")
            return None

    def _enforce(self, request):
        """Run all security policy checks. Returns a response to short-circuit, or None to proceed."""
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return None

        path = request.path

        # Skip exempt paths
        if _is_exempt(path):
            return None

        # Only enforce on API paths
        if not path.startswith("/api/"):
            return None

        # Get the user's most restrictive org policies
        mfa_required, timeout_minutes, max_sessions, sso_enforced = (
            get_effective_policy(user)
        )

        # 1. SSO enforcement — if SSO is enforced and user didn't log in via SSO,
        # block the request (except for SSO setup and auth paths).
        if sso_enforced:
            response = self._check_sso_enforcement(user)
            if response is not None:
                return response

        # 2. MFA enforcement
        response = self._check_mfa(user, mfa_required)
        if response is not None:
            return response

        # 3. Session timeout
        response = self._check_session_timeout(request, timeout_minutes)
        if response is not None:
            return response

        # 4. Concurrent session tracking & limits
        self._track_session(request, user, max_sessions)

        return None

    def _check_sso_enforcement(self, user):
        """If SSO is enforced and user's session wasn't established via SSO, return 403."""
        session = getattr(user, "_wrapped", user)
        # Check if the user has any social accounts (indicating SSO login)
        try:
            from allauth.socialaccount.models import SocialAccount

            has_social = SocialAccount.objects.filter(user=user).exists()
            if has_social:
                return None
        except ImportError:
            return None

        return JsonResponse(
            {
                "detail": "SSO login is required by your organization. Please use your organization's SSO provider.",
                "code": "sso_required",
            },
            status=403,
        )

    def _check_mfa(self, user, mfa_required: bool):
        """If MFA is required but user hasn't set it up, return 403."""
        if not mfa_required:
            return None

        try:
            from allauth.mfa.utils import is_mfa_enabled

            if is_mfa_enabled(user):
                return None
        except ImportError:
            # allauth.mfa not available — skip check
            return None

        return JsonResponse(
            {
                "detail": "MFA is required by your organization. Please enable multi-factor authentication.",
                "code": "mfa_required",
            },
            status=403,
        )

    def _check_session_timeout(self, request, timeout_minutes: int):
        """If the session has been idle longer than the timeout, flush it and return 401."""
        session = getattr(request, "session", None)
        if session is None or session.is_empty():
            return None

        last_activity = session.get("_last_activity")
        now = time.time()

        if last_activity is not None:
            idle_seconds = now - last_activity
            if idle_seconds > timeout_minutes * 60:
                # Clean up session tracking record
                session_key = session.session_key
                if session_key:
                    from apps.compliance.models import UserSession

                    UserSession.objects.filter(session_key=session_key).delete()

                session.flush()
                return JsonResponse(
                    {
                        "detail": "Your session has expired due to inactivity.",
                        "code": "session_expired",
                    },
                    status=401,
                )

        # Update last activity timestamp
        session["_last_activity"] = now
        return None

    def _track_session(self, request, user, max_sessions: int):
        """Register this session and evict oldest if over the concurrent limit."""
        session = getattr(request, "session", None)
        if session is None or not session.session_key:
            return

        from apps.compliance.models import UserSession

        session_key = session.session_key
        ip = self._get_client_ip(request)
        user_agent = request.META.get("HTTP_USER_AGENT", "")[:500]

        # Upsert the current session record (updates last_activity via auto_now)
        updated = UserSession.objects.filter(session_key=session_key).update(
            ip_address=ip,
            user_agent=user_agent,
        )
        if not updated:
            UserSession.objects.update_or_create(
                session_key=session_key,
                defaults={
                    "user": user,
                    "ip_address": ip,
                    "user_agent": user_agent,
                },
            )

        # Enforce concurrent session limit
        user_sessions = UserSession.objects.filter(user=user).order_by("-last_activity")
        session_count = user_sessions.count()

        if session_count > max_sessions:
            # Evict oldest sessions beyond the limit
            sessions_to_evict = user_sessions[max_sessions:]
            keys_to_evict = list(
                sessions_to_evict.values_list("session_key", flat=True)
            )

            # Delete Django session records
            Session.objects.filter(session_key__in=keys_to_evict).delete()

            # Delete tracking records
            UserSession.objects.filter(session_key__in=keys_to_evict).delete()

            logger.info(
                "Evicted %d session(s) for user %s (limit: %d)",
                len(keys_to_evict),
                user.pk,
                max_sessions,
            )

    @staticmethod
    def _get_client_ip(request) -> str | None:
        """Extract client IP from X-Forwarded-For or REMOTE_ADDR."""
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
