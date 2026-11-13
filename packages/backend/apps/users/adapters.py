"""Authentication adapters for django-allauth and Django Ninja token-based auth."""

from __future__ import annotations

import hashlib
import logging
import time
import typing

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from asgiref.sync import sync_to_async
from dj_rest_auth.models import get_token_model
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from ninja.security import APIKeyHeader, HttpBearer

if typing.TYPE_CHECKING:
    from allauth.socialaccount.models import SocialLogin
    from django.http import HttpRequest

    from apps.users.models import User

logger = logging.getLogger(__name__)


class AccountAdapter(DefaultAccountAdapter):
    """Adapter controlling account signup behavior for standard email/password accounts."""

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        """Check whether account registration is open.

        Args:
            request: The current HTTP request.

        Returns:
            True if registration is allowed, False otherwise.
        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def get_login_redirect_url(self, request: HttpRequest) -> str:
        """After social OAuth login, redirect to the SPA callback with an auth token."""
        user = request.user
        if user and user.is_authenticated:
            token_model = get_token_model()
            token, _ = token_model.objects.get_or_create(user=user)
            return f"/auth/callback?token={token.key}"
        return super().get_login_redirect_url(request)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    """Adapter controlling signup and user population for social (OAuth) accounts."""

    def is_open_for_signup(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
    ) -> bool:
        """Check whether social account registration is open.

        Args:
            request: The current HTTP request.
            sociallogin: The social login instance being attempted.

        Returns:
            True if registration is allowed, False otherwise.
        """
        return getattr(settings, "ACCOUNT_ALLOW_REGISTRATION", True)

    def populate_user(
        self,
        request: HttpRequest,
        sociallogin: SocialLogin,
        data: dict[str, typing.Any],
    ) -> User:
        """
        Populates user information from social provider info.

        See: https://docs.allauth.org/en/latest/socialaccount/advanced.html#creating-and-populating-user-instances
        """
        user = super().populate_user(request, sociallogin, data)
        if not user.name:
            if name := data.get("name"):
                user.name = name
            elif first_name := data.get("first_name"):
                user.name = first_name
                if last_name := data.get("last_name"):
                    user.name += f" {last_name}"
        return user


class NinjaAuthAdapter(HttpBearer):
    """Synchronous token authentication backend for Django Ninja endpoints."""

    def authenticate(self, request, token):
        """Validate a bearer token and return the associated user.

        Args:
            request: The current HTTP request.
            token: The bearer token string from the Authorization header.

        Returns:
            The authenticated User instance, or None if the token is invalid.
        """
        try:
            token_model = get_token_model()
            token_obj = token_model.objects.get(key=token)
            return token_obj.user
        except token_model.DoesNotExist:
            return None
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "Unexpected error in NinjaAuthAdapter"
            )
            return None


class AsyncTokenAuthentication(HttpBearer):
    """Asynchronous token authentication backend for async Django Ninja endpoints."""

    async def authenticate(self, request, token):
        """Validate a bearer token asynchronously and return the associated user.

        Args:
            request: The current HTTP request.
            token: The bearer token string from the Authorization header.

        Returns:
            The authenticated User instance, or None if the token is invalid.
        """
        try:
            # Use sync_to_async for database operations
            token_model = get_token_model()
            token_obj = await sync_to_async(token_model.objects.get)(key=token)
            user = await sync_to_async(getattr)(token_obj, "user")
            return user
        except token_model.DoesNotExist:
            return None
        except Exception:
            logger.exception("Unexpected error in AsyncTokenAuthentication")
            return None


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

# Default limits (requests per minute)
AUTHENTICATED_RATE_LIMIT = 600
UNAUTHENTICATED_RATE_LIMIT = 30
RATE_LIMIT_WINDOW = 60  # seconds

# Per-endpoint overrides: {(method, path_prefix): limit_per_minute}
# Only these endpoints are rate-limited for authenticated users.
ENDPOINT_RATE_LIMITS: dict[tuple[str, str], int] = {
    # Agent starts are expensive (sandbox provisioning + LLM calls)
    ("POST", "/api/v1/chat/completions/start"): 10,
    # Password reset OTPs — prevent brute-force enumeration
    ("POST", "/api/v1/workspace/password/request-otp"): 5,
}

# Keep backwards-compatible aliases
API_KEY_RATE_LIMIT = AUTHENTICATED_RATE_LIMIT
API_KEY_RATE_WINDOW = RATE_LIMIT_WINDOW


def _check_rate_limit(
    identifier: str,
    limit: int = AUTHENTICATED_RATE_LIMIT,
    window: int = RATE_LIMIT_WINDOW,
) -> tuple[bool, dict[str, str]]:
    """Check and increment the sliding-window rate limit for a given identifier.

    Args:
        identifier: Unique key for rate limiting (e.g. user id, IP, API key id).
        limit: Maximum number of requests allowed in the window.
        window: Window duration in seconds.

    Returns:
        (allowed, headers) where *allowed* is False when the limit is exceeded
        and *headers* contains X-RateLimit-* values.
    """
    now = time.time()

    count_key = f"rl_count:{identifier}"
    reset_key = f"rl_reset:{identifier}"

    current_count = cache.get(count_key)
    if current_count is None:
        cache.set(count_key, 1, timeout=window)
        cache.set(reset_key, int(now + window), timeout=window)
        current_count = 1
    else:
        try:
            current_count = cache.incr(count_key)
        except ValueError:
            cache.set(count_key, 1, timeout=window)
            cache.set(reset_key, int(now + window), timeout=window)
            current_count = 1

    reset_at = cache.get(reset_key) or int(now + window)
    remaining = max(0, limit - current_count)

    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(reset_at),
    }

    return current_count <= limit, headers


def _check_api_key_rate_limit(key_id: str) -> tuple[bool, dict[str, str]]:
    """Check rate limit for an API key (convenience wrapper)."""
    return _check_rate_limit(
        f"apikey:{key_id}", API_KEY_RATE_LIMIT, API_KEY_RATE_WINDOW
    )


def _get_client_ip(request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


class APIKeyAuthAdapter(APIKeyHeader):
    """API key authentication for the developer API.

    Supports two header formats:
    - ``X-API-Key: msk_...``
    - ``Authorization: ApiKey msk_...``

    On successful authentication, ``request.auth`` is set to the ``User`` and
    ``request.api_key`` is set to the ``DeveloperAPIKey`` instance.
    """

    param_name = "X-API-Key"

    def authenticate(self, request, key):
        """Validate an API key and return the associated user.

        Also checks expiry, active status, scopes, and rate limits.
        Stores the API key object on the request for downstream scope checks.
        """
        if not key:
            # Try Authorization: ApiKey <key> header as fallback
            key = self._extract_from_authorization(request)
        if not key:
            return None

        from apps.users.models import DeveloperAPIKey

        key_hash = hashlib.sha256(key.encode()).hexdigest()

        try:
            api_key = DeveloperAPIKey.objects.select_related("user").get(
                key_hash=key_hash
            )
        except DeveloperAPIKey.DoesNotExist:
            return None

        # Check active
        if not api_key.is_active:
            return None

        # Check expiry
        if api_key.expires_at and api_key.expires_at <= timezone.now():
            return None

        # Rate limit check
        allowed, rl_headers = _check_api_key_rate_limit(str(api_key.id))
        # Store headers on request so middleware/response can add them
        request._api_key_rate_limit_headers = rl_headers
        if not allowed:
            request._api_key_rate_limited = True
            return None

        # Update last_used_at (fire-and-forget, don't block auth)
        DeveloperAPIKey.objects.filter(id=api_key.id).update(
            last_used_at=timezone.now()
        )

        # Attach API key to request for scope enforcement
        request.api_key = api_key
        return api_key.user

    @staticmethod
    def _extract_from_authorization(request) -> str | None:
        """Extract API key from ``Authorization: ApiKey <key>`` header."""
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("ApiKey "):
            return auth_header[7:].strip()
        return None


class APIKeyRateLimitMiddleware:
    """Middleware that enforces rate limits and adds rate-limit headers.

    Rate limiting strategy:
    - API key requests: handled by APIKeyAuthAdapter (60/min per key)
    - Authenticated GET requests: exempt (users browsing their own data)
    - Authenticated mutating requests: per-endpoint overrides only
      (e.g. 10/min for agent starts)
    - Unauthenticated requests: 10 requests/min (by IP)
    """

    # Paths that should never be rate limited regardless of method/auth
    EXEMPT_PREFIXES = ("/health", "/live", "/ready", "/static", "/admin")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if API key auth adapter already flagged as rate limited
        if getattr(request, "_api_key_rate_limited", False):
            return self._make_429_response(
                getattr(request, "_api_key_rate_limit_headers", {})
            )

        response = self.get_response(request)

        # After the view runs, we know if the user is authenticated.
        # Apply general rate limiting (skip if API key already handled it).
        if not getattr(request, "_api_key_rate_limit_headers", None):
            if not self._is_exempt(request):
                allowed, rl_headers = self._check_general_rate_limit(request)
                if not allowed:
                    return self._make_429_response(rl_headers)
                for header, value in rl_headers.items():
                    response[header] = value

        # Add API key rate limit headers to successful responses
        rl_headers = getattr(request, "_api_key_rate_limit_headers", None)
        if rl_headers:
            for header, value in rl_headers.items():
                response[header] = value

        return response

    def _is_exempt(self, request) -> bool:
        """Check if a request is exempt from general rate limiting."""
        path = request.path

        if any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES):
            return True

        user = getattr(request, "user", None)
        is_authenticated = user and getattr(user, "is_authenticated", False)

        if is_authenticated:
            # Authenticated GET requests are never rate-limited — it's a user
            # browsing their own data. Mutating requests are only limited when
            # they have an explicit per-endpoint override (e.g. agent starts).
            if request.method == "GET":
                return True
            if self._get_endpoint_limit(request) is None:
                return True

        return False

    def _check_general_rate_limit(self, request) -> tuple[bool, dict[str, str]]:
        """Apply general rate limiting based on auth status and endpoint."""
        user = getattr(request, "user", None)
        is_authenticated = user and getattr(user, "is_authenticated", False)

        # Per-endpoint override (authenticated users only reach here when one exists)
        endpoint_limit = self._get_endpoint_limit(request)
        if is_authenticated and endpoint_limit is not None:
            identifier = f"ep:user:{user.pk}:{request.method}:{request.path}"
            return _check_rate_limit(identifier, endpoint_limit, RATE_LIMIT_WINDOW)

        # Unauthenticated — IP-based limit
        identifier = f"ip:{_get_client_ip(request)}"
        return _check_rate_limit(
            identifier, UNAUTHENTICATED_RATE_LIMIT, RATE_LIMIT_WINDOW
        )

    @staticmethod
    def _get_endpoint_limit(request) -> int | None:
        """Check per-endpoint rate limit override, or decorator-set limit."""
        # Check decorator-set override first
        view_limit = getattr(request, "_rate_limit_override", None)
        if view_limit is not None:
            return view_limit

        # Check ENDPOINT_RATE_LIMITS table
        for (method, prefix), limit in ENDPOINT_RATE_LIMITS.items():
            if request.method == method and request.path.startswith(prefix):
                return limit
        return None

    @staticmethod
    def _make_429_response(rl_headers: dict[str, str]) -> JsonResponse:
        """Build a 429 Too Many Requests response."""
        reset_at = rl_headers.get("X-RateLimit-Reset", "")
        retry_after = "60"
        if reset_at:
            retry_after = str(max(1, int(reset_at) - int(time.time())))
        response = JsonResponse(
            {
                "error": "Rate limit exceeded",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "detail": None,
                "status": 429,
            },
            status=429,
        )
        response["Retry-After"] = retry_after
        for header, value in rl_headers.items():
            response[header] = value
        return response


def rate_limit(requests_per_minute: int):
    """Decorator to set a per-endpoint rate limit override.

    Usage::

        @api.post("/expensive")
        @rate_limit(10)
        def expensive_operation(request):
            ...
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            request._rate_limit_override = requests_per_minute
            return func(request, *args, **kwargs)

        return wrapper

    return decorator


def require_scopes(*scopes: str):
    """Decorator for Django Ninja endpoints that enforces API key scopes.

    Usage::

        @api.get("/conversations")
        @require_scopes("conversations:read")
        def list_conversations(request):
            ...

    If the request was authenticated with a bearer token (not an API key),
    all scopes are implicitly granted.
    """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(request, *args, **kwargs):
            api_key = getattr(request, "api_key", None)
            if api_key is not None:
                # API key auth — check scopes
                key_scopes = set(api_key.scopes or [])
                required = set(scopes)
                if not required.issubset(key_scopes):
                    missing = required - key_scopes
                    return JsonResponse(
                        {
                            "error": f"API key missing required scopes: {', '.join(sorted(missing))}",
                            "error_code": "INSUFFICIENT_SCOPE",
                            "detail": {
                                "required": sorted(required),
                                "missing": sorted(missing),
                            },
                            "status": 403,
                        },
                        status=403,
                    )
            # Bearer token auth or scopes satisfied — proceed
            return func(request, *args, **kwargs)

        return wrapper

    return decorator
