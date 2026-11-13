"""Authentication backends for the agent server API."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import inspect
import logging
import os
import time
from typing import Any, Callable

from django.http import HttpRequest, JsonResponse
from ninja.security import APIKeyHeader, APIKeyQuery, HttpBearer

from agent_server.models import DjangoAuthToken

log = logging.getLogger("agent_server")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  AUTHENTICATION                                                            ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


def _get_api_key() -> str | None:
    """Return the configured static API key, or None if unset."""
    return os.environ.get("SUKUNA_AGENT_SERVER_API_KEY") or os.environ.get("API_KEY") or None


# ---------------------------------------------------------------------------
# Bearer token auth (shared DRF authtoken table)
# ---------------------------------------------------------------------------


class BearerTokenAuth(HttpBearer):
    """Authenticate via ``Authorization: Bearer <token>`` using the shared DRF token table."""

    def authenticate(self, request, token: str):
        """Look up the DRF auth token and return the associated DjangoUser."""
        try:
            token_obj = DjangoAuthToken.objects.select_related("user").get(key=token)
            if not token_obj.user.is_active:
                return None
            return token_obj.user
        except DjangoAuthToken.DoesNotExist:
            return None
        except Exception:
            log.exception("Unexpected error in BearerTokenAuth")
            return None


# ---------------------------------------------------------------------------
# Static API key auth (X-API-Key header)
# ---------------------------------------------------------------------------


class StaticAPIKeyAuth(APIKeyHeader):
    """Authenticate via ``X-API-Key`` header against the static server API key."""

    param_name = "X-API-Key"

    def authenticate(self, request, key: str | None):
        expected = _get_api_key()
        if not expected:
            return None
        if key and hmac.compare_digest(key, expected):
            return "api_key_user"
        return None


# ---------------------------------------------------------------------------
# Query-param API key auth (for browser EventSource which cannot set headers)
# ---------------------------------------------------------------------------


class QueryParamAPIKeyAuth(APIKeyQuery):
    """Authenticate via ``?api_key=<key>`` query parameter.

    Uses APIKeyQuery (not HttpBearer) so that Django Ninja reads the key
    directly from the query string — no Authorization header required.
    This is essential for browser EventSource clients which cannot set
    custom headers.
    """

    param_name = "api_key"

    def authenticate(self, request, key: str | None):
        expected = _get_api_key()
        if not expected:
            return None
        if key and hmac.compare_digest(key, expected):
            return "api_key_user"
        return None


# ---------------------------------------------------------------------------
# JWT stream auth (direct streaming from frontend -> sandbox)
# ---------------------------------------------------------------------------


class JWTStreamAuth(HttpBearer):
    """Authenticate direct stream requests via JWT minted by the Django backend."""

    def authenticate(self, request, token: str):
        secret = os.environ.get("SUKUNA_STREAM_JWT_SECRET", "")
        if not secret:
            return None

        try:
            import jwt

            claims = jwt.decode(
                token,
                secret,
                algorithms=["HS256"],
                issuer="sukuna-backend",
                audience="sukuna-sandbox-stream",
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
            scope = claims.get("scope") or []
            if not isinstance(scope, list):
                scope = []
            return {
                "type": "jwt_stream",
                "user_id": claims.get("user_id"),
                "run_id": claims.get("sub"),
                "conversation_id": claims.get("conversation_id"),
                "scope": scope,
            }
        except Exception:
            return None


class QueryParamJWTAuth(APIKeyQuery):
    """Accept JWT via ``?token=<jwt>`` query parameter for browser EventSource."""

    param_name = "token"

    def authenticate(self, request, key: str | None):
        jwt_token = request.GET.get("token") or key
        if not jwt_token:
            return None
        return JWTStreamAuth().authenticate(request, jwt_token)


# ---------------------------------------------------------------------------
# Webhook signature auth (Telegram + Slack — no user principal, signature only)
# ---------------------------------------------------------------------------


class TelegramSignatureAuth(APIKeyHeader):
    """Validate Telegram webhooks via ``X-Telegram-Bot-Api-Secret-Token``.

    Telegram signs the header value with the shared secret configured when the
    webhook was registered.  We compare it in constant time against the
    ``TELEGRAM_WEBHOOK_SECRET`` env var.  Returns the string ``"telegram"``
    when valid so callers can distinguish this principal from a user.
    """

    param_name = "X-Telegram-Bot-Api-Secret-Token"

    def authenticate(self, request: HttpRequest, key: str | None):
        expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        if not expected:
            # No secret configured — refuse every request rather than silently
            # admitting them.  Production webhooks MUST configure this.
            return None
        if key and hmac.compare_digest(str(expected), str(key)):
            return "telegram_webhook"
        return None


class SlackSignatureAuth(HttpBearer):
    """Validate Slack webhooks via HMAC-SHA256 over ``v0:{timestamp}:{body}``.

    Slack's signing scheme passes the signature in ``X-Slack-Signature`` and a
    unix timestamp in ``X-Slack-Request-Timestamp``.  Requests older than 5
    minutes are rejected to prevent replay attacks.  Returns the string
    ``"slack"`` when valid.

    Note: We subclass HttpBearer only to fit Ninja's auth protocol.  The
    bearer header is ignored; ``authenticate`` re-reads the Slack headers.
    """

    def __call__(self, request: HttpRequest):
        return self.authenticate(request, "")

    def authenticate(self, request: HttpRequest, token: str):
        signing_secret = os.environ.get("SLACK_SIGNING_SECRET", "")
        if not signing_secret:
            return None

        headers = getattr(request, "headers", None) or {}
        timestamp = headers.get("X-Slack-Request-Timestamp", "")
        signature = headers.get("X-Slack-Signature", "")
        if not timestamp or not signature:
            return None

        try:
            if abs(time.time() - float(timestamp)) > 300:
                return None
        except (ValueError, TypeError):
            return None

        try:
            body_bytes = request.body or b""
        except Exception:
            return None
        body_str = body_bytes.decode("utf-8", errors="replace")

        sig_basestring = f"v0:{timestamp}:{body_str}"
        computed = (
            "v0="
            + hmac.new(
                signing_secret.encode("utf-8"),
                sig_basestring.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
        )
        if hmac.compare_digest(computed, str(signature)):
            return "slack_webhook"
        return None


# ---------------------------------------------------------------------------
# Combined authenticators for use in NinjaAPI / Router auth= parameters
# ---------------------------------------------------------------------------

default_auth = [BearerTokenAuth(), StaticAPIKeyAuth()]
stream_auth = [JWTStreamAuth(), QueryParamJWTAuth(), BearerTokenAuth(), StaticAPIKeyAuth(), QueryParamAPIKeyAuth()]


# ---------------------------------------------------------------------------
# Scope enforcement (for JWT stream auth). Bearer/APIKey principals bypass.
# ---------------------------------------------------------------------------


def require_scope(scopes: list[str]) -> Callable:
    """Require that the authenticated principal has at least one of ``scopes``.

    Only enforced when the principal is a JWT stream dict (``type == "jwt_stream"``).
    Bearer-token users (Django users) and static API-key principals bypass the check —
    backend-to-sandbox RPCs authenticate with the shared API key and should not be
    constrained by frontend-facing scope gates.
    """

    required = set(scopes)

    def _deny(request: HttpRequest) -> JsonResponse:
        return JsonResponse(
            {"detail": f"Missing required scope; need one of {sorted(required)}"},
            status=403,
        )

    def _principal_missing_scope(request: HttpRequest) -> bool:
        principal = getattr(request, "auth", None)
        if isinstance(principal, dict) and principal.get("type") == "jwt_stream":
            granted = set(principal.get("scope") or [])
            return not (required & granted)
        return False

    def decorator(func: Callable) -> Callable:
        func_signature = inspect.signature(func)

        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(request: HttpRequest, *args: Any, **kwargs: Any):
                if _principal_missing_scope(request):
                    return _deny(request)
                return await func(request, *args, **kwargs)

            async_wrapper.__signature__ = func_signature
            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(request: HttpRequest, *args: Any, **kwargs: Any):
            if _principal_missing_scope(request):
                return _deny(request)
            return func(request, *args, **kwargs)

        sync_wrapper.__signature__ = func_signature
        return sync_wrapper

    return decorator
