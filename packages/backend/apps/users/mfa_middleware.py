"""Middleware that enforces MFA challenge completion for token-authenticated requests.

When a user has at least one MFA authenticator enrolled and their bearer token
has not yet passed an MFA challenge for the current session, all API endpoints
return 403 except for a small allowlist (the MFA verify endpoint itself, the
/users/me/ profile read so the SPA can route, logout, and developer docs).
"""

from __future__ import annotations

import logging

from dj_rest_auth.models import get_token_model
from django.http import JsonResponse

logger = logging.getLogger(__name__)


# Paths the MFA-pending session is allowed to call.
ALLOWED_PREFIXES = (
    "/api/v1/users/me/",  # profile read so SPA knows to render the challenge
    "/api/v1/users/me/mfa",  # MFA state + verify + enrollment
    "/health",
    "/live",
    "/ready",
    "/static",
    "/admin",
    "/authentication/",  # dj_rest_auth (logout)
    "/accounts/",  # allauth views
)


class MFAEnforcementMiddleware:
    """Block API access when the bearer token has not passed MFA.

    Only applies to requests under ``/api/`` that present a Bearer token.
    Other auth schemes (developer API keys, session cookies for admin) are
    untouched.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if not path.startswith("/api/"):
            return self.get_response(request)
        if any(path.startswith(prefix) for prefix in ALLOWED_PREFIXES):
            return self.get_response(request)

        auth_header = request.META.get("HTTP_AUTHORIZATION", "") or ""
        if not auth_header.lower().startswith("bearer "):
            return self.get_response(request)
        token_key = auth_header[7:].strip()
        if not token_key:
            return self.get_response(request)

        # Local imports keep app loading cheap and avoid circular imports.
        from allauth.mfa.models import Authenticator

        from apps.users.mfa_api import is_token_mfa_verified

        try:
            token_model = get_token_model()
            token_obj = token_model.objects.select_related("user").get(key=token_key)
        except token_model.DoesNotExist:
            return self.get_response(request)
        except Exception:
            logger.exception("MFAEnforcementMiddleware token lookup failed")
            return self.get_response(request)

        user = token_obj.user
        if not Authenticator.objects.filter(user=user).exists():
            return self.get_response(request)

        if is_token_mfa_verified(token_key):
            return self.get_response(request)

        return JsonResponse(
            {
                "error": "MFA verification required.",
                "error_code": "MFA_REQUIRED",
                "detail": "Complete the MFA challenge to access this resource.",
                "status": 403,
            },
            status=403,
        )
