"""Security hardening utilities for enterprise workspace features.

Provides:
- Display name sanitization (LLM injection prevention)
- API key scope enforcement for org endpoints
- SCIM 404 rate limiting for org enumeration prevention
"""

import re

from django.core.cache import cache
from ninja.errors import HttpError

# ── Display Name Sanitization ─────────────────────────────────────────────

# Characters stripped: brackets, angle brackets, curly braces, pipes,
# backslashes, backticks, and markdown formatting characters.
_DISPLAY_NAME_UNSAFE_RE = re.compile(r"[\[\]<>{}|\\`*_~#]")


def sanitize_display_name(name: str | None) -> str:
    """Strip characters that could confuse LLM context injection or render
    as markdown/HTML in downstream consumers.

    Returns the sanitized string, or empty string if input was None/empty.
    """
    if not name:
        return ""
    return _DISPLAY_NAME_UNSAFE_RE.sub("", name).strip()


# ── API Key Scope Enforcement ─────────────────────────────────────────────

# Standard enterprise scopes for org endpoints
ORG_SCOPE_READ = "org:read"
ORG_SCOPE_WRITE = "org:write"
ORG_SCOPE_ADMIN = "org:admin"

# Scope hierarchy: admin implies write implies read
_SCOPE_HIERARCHY = {
    ORG_SCOPE_READ: {ORG_SCOPE_READ, ORG_SCOPE_WRITE, ORG_SCOPE_ADMIN},
    ORG_SCOPE_WRITE: {ORG_SCOPE_WRITE, ORG_SCOPE_ADMIN},
    ORG_SCOPE_ADMIN: {ORG_SCOPE_ADMIN},
}


def check_api_key_org_scope(request, required_scope: str) -> None:
    """Check that an API key (if present) has the required org scope.

    Bearer token requests pass through unconditionally.
    API key requests must have the required scope (or a higher-privilege scope
    that implies it).

    Raises HttpError(403) if the API key lacks the required scope.
    """
    api_key = getattr(request, "api_key", None)
    if api_key is None:
        # Bearer token auth — all scopes implicitly granted
        return

    key_scopes = set(api_key.scopes or [])
    # Check if the key has the required scope or any scope that implies it
    allowed_scopes = _SCOPE_HIERARCHY.get(required_scope, {required_scope})
    if not key_scopes & allowed_scopes:
        raise HttpError(
            403,
            f"API key missing required scope: {required_scope}",
        )


# ── SCIM 404 Rate Limiting ───────────────────────────────────────────────

# Max 404 responses per IP before throttling
SCIM_404_MAX_PER_WINDOW = 5
SCIM_404_WINDOW_SECONDS = 60


def check_scim_404_rate(request) -> bool:
    """Track and rate-limit SCIM 404 responses to prevent org enumeration.

    Call this BEFORE returning a 404 from a SCIM endpoint.

    Returns True if the request should be rate-limited (return 429 instead of 404).
    """
    client_ip = _get_client_ip(request) or "unknown"
    cache_key = f"scim_404:{client_ip}"
    count = cache.get(cache_key, 0)
    if count >= SCIM_404_MAX_PER_WINDOW:
        return True  # Rate limited
    cache.set(cache_key, count + 1, timeout=SCIM_404_WINDOW_SECONDS)
    return False


def _get_client_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")
