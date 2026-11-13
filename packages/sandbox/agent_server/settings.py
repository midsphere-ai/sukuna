"""Minimal Django settings — ORM + Django Ninja only, no middleware bloat."""

import os

_db_url = os.environ.get("DATABASE_URL") or os.environ.get("MIDSPHERE_DB_URL", "")
_db_conn_max_age = int(os.environ.get("DJANGO_DB_CONN_MAX_AGE", os.environ.get("SANDBOX_DB_CONN_MAX_AGE", "0")))
_db_conn_health_checks = os.environ.get("DJANGO_DB_CONN_HEALTH_CHECKS", "true").lower() in {
    "1",
    "true",
    "yes",
}


# Parse postgres URL manually (avoid dj-database-url dependency)
def _parse_db_url(url: str) -> dict:
    """Parse a postgresql:// URL into Django DATABASES dict format."""
    if not url:
        raise RuntimeError(
            "DATABASE_URL (or MIDSPHERE_DB_URL) is required. Set it in vault or in .env.local for local development."
        )
    # Strip asyncpg driver prefix if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    from urllib.parse import urlparse

    parsed = urlparse(url)
    # Strip sslmode from query params (Django handles SSL differently)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": max(_db_conn_max_age, 0),
        "CONN_HEALTH_CHECKS": _db_conn_health_checks,
    }


DATABASES = {"default": _parse_db_url(_db_url)}

INSTALLED_APPS = ["agent_server"]

# ── CORS ────────────────────────────────────────────────────────────────────
# Frontend connects directly to the sandbox for streaming, control ops, and
# file operations.  In production each E2B sandbox has a unique hostname
# (cross-origin from the frontend).  POST requests with JSON body trigger
# CORS preflight.  This is safe because: (1) each sandbox serves one
# conversation, (2) all endpoints require JWT validation, (3) no cookie auth.
INSTALLED_APPS = [*INSTALLED_APPS, "corsheaders"]
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware"]
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "sandbox-local-dev-key")

# Minimal middleware stack — keep CORS so direct frontend -> sandbox requests
# work for both successful responses and auth failures.
MIDDLEWARE = ["corsheaders.middleware.CorsMiddleware"]

# Minimal template engine — needed by Django Ninja's /docs page
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": False,
        "OPTIONS": {"context_processors": []},
    },
]

# Required for Django's URL routing with Django Ninja
ROOT_URLCONF = "agent_server.urls"

# ── File Storage (DigitalOcean Spaces / S3-compatible) ───────────────────────
# Same bucket as the backend — vault injects DO_SPACES_* env vars.
# When creds are missing (local dev), falls back to Django's default filesystem storage.

_do_access_key = os.environ.get("DO_SPACES_ACCESS_KEY", "")
_do_secret_key = os.environ.get("DO_SPACES_SECRET_KEY", "")
_do_region = os.environ.get("DO_SPACES_REGION", "")
_do_media_bucket = os.environ.get("DO_SPACES_MEDIA_BUCKET_NAME", "")

if _do_access_key and _do_secret_key and _do_region and _do_media_bucket:
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
            "OPTIONS": {
                "access_key": _do_access_key,
                "secret_key": _do_secret_key,
                "bucket_name": _do_media_bucket,
                "endpoint_url": f"https://{_do_region}.digitaloceanspaces.com",
                "region_name": _do_region,
                "location": "media",
                "file_overwrite": False,
                "default_acl": "public-read",
            },
        },
    }
    _do_custom_domain = os.environ.get("DO_SPACES_CUSTOM_DOMAIN", "")
    _do_media_domain = _do_custom_domain or f"{_do_media_bucket}.{_do_region}.digitaloceanspaces.com"
    MEDIA_URL = f"https://{_do_media_domain}/media/"
else:
    # Local dev fallback — filesystem storage
    MEDIA_URL = "/media/"
