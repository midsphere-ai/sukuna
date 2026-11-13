# ruff: noqa: E501
"""Django settings for production deployment.

Extends base settings with hardened security (HSTS, secure cookies),
DigitalOcean Spaces for static/media storage, Mailgun email via Anymail,
Redis caching, and Sentry error tracking.
"""

import logging

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.redis import RedisIntegration

from .base import *  # noqa: F403
from .base import INSTALLED_APPS, REDIS_URL, env

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secret-key
SECRET_KEY = env("DJANGO_SECRET_KEY")
# https://docs.djangoproject.com/en/dev/ref/settings/#allowed-hosts
ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=[
        "midsphere.ai",
        "localhost",
        "127.0.0.1",
        "api.midsphere.ai",
        "platform.midsphere.ai",
        "cloud.digitalocean.com",
        "channels.digitalocean.com",
        "flower.example.com",
    ],
)

# CACHES
# ------------------------------------------------------------------------------
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            # Mimicking memcache behavior.
            # https://github.com/jazzband/django-redis#memcached-exceptions-behavior
            "IGNORE_EXCEPTIONS": True,
        },
    },
}

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-proxy-ssl-header
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-ssl-redirect
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-secure
SESSION_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-name
SESSION_COOKIE_NAME = "__Secure-sessionid"
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-secure
CSRF_COOKIE_SECURE = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-name
CSRF_COOKIE_NAME = "__Secure-csrftoken"
# https://docs.djangoproject.com/en/dev/topics/security/#ssl-https
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-seconds
# TODO: set this to 60 seconds first and then to 518400 once you prove the former works
SECURE_HSTS_SECONDS = 31536000
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-include-subdomains
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    default=True,
)
# https://docs.djangoproject.com/en/dev/ref/settings/#secure-hsts-preload
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
# https://docs.djangoproject.com/en/dev/ref/middleware/#x-content-type-options-nosniff
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF",
    default=True,
)
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"


# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
# DigitalOcean Spaces (S3-compatible storage)
# ------------------------------------------------------------------------------
AWS_ACCESS_KEY_ID = env("DO_SPACES_ACCESS_KEY")
AWS_SECRET_ACCESS_KEY = env("DO_SPACES_SECRET_KEY")
DO_SPACES_STATIC_BUCKET = env("DO_SPACES_STATIC_BUCKET_NAME")
DO_SPACES_MEDIA_BUCKET = env("DO_SPACES_MEDIA_BUCKET_NAME")
AWS_S3_REGION_NAME = env("DO_SPACES_REGION")
# DigitalOcean Spaces endpoint
AWS_S3_ENDPOINT_URL = f"https://{AWS_S3_REGION_NAME}.digitaloceanspaces.com"

# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_QUERYSTRING_AUTH = False
# DO NOT change these unless you know what you're doing.
_AWS_EXPIRY = 60 * 60 * 24 * 7
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": f"max-age={_AWS_EXPIRY}, s-maxage={_AWS_EXPIRY}, must-revalidate",
}
# https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html#settings
AWS_S3_MAX_MEMORY_SIZE = env.int(
    "DJANGO_AWS_S3_MAX_MEMORY_SIZE",
    default=100_000_000,  # 100MB
)
# Custom domain for CDN (optional)
AWS_S3_CUSTOM_DOMAIN = env("DO_SPACES_CUSTOM_DOMAIN", default=None)

# DigitalOcean Spaces domain construction
do_static_domain = (
    AWS_S3_CUSTOM_DOMAIN
    or f"{DO_SPACES_STATIC_BUCKET}.{AWS_S3_REGION_NAME}.digitaloceanspaces.com"
)
do_media_domain = (
    AWS_S3_CUSTOM_DOMAIN
    or f"{DO_SPACES_MEDIA_BUCKET}.{AWS_S3_REGION_NAME}.digitaloceanspaces.com"
)

# STATIC & MEDIA with separate DigitalOcean Spaces buckets
# ------------------------
# Note: DO_SPACES_REGION must be the full region code (e.g., 'blr1', 'nyc3', 'sgp1')
STORAGES = {
    "default": {
        "BACKEND": "config.do_storage.DOMediaStorage",
        "OPTIONS": {
            "bucket_name": DO_SPACES_MEDIA_BUCKET,
            "endpoint_url": f"https://{AWS_S3_REGION_NAME}.digitaloceanspaces.com",
            "region_name": AWS_S3_REGION_NAME,
            "location": "media",
            "file_overwrite": False,
        },
    },
    "staticfiles": {
        "BACKEND": "config.do_storage.DOStaticStorage",
        "OPTIONS": {
            "bucket_name": DO_SPACES_STATIC_BUCKET,
            "endpoint_url": f"https://{AWS_S3_REGION_NAME}.digitaloceanspaces.com",
            "region_name": AWS_S3_REGION_NAME,
            "location": "static",
            "default_acl": "public-read",
        },
    },
}
MEDIA_URL = f"https://{do_media_domain}/media/"
COLLECTFASTA_STRATEGY = "collectfasta.strategies.boto3.Boto3Strategy"
STATIC_URL = f"https://{do_static_domain}/static/"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-subject-prefix
EMAIL_SUBJECT_PREFIX = env(
    "DJANGO_EMAIL_SUBJECT_PREFIX",
    default="[sukuna] ",
)
ACCOUNT_EMAIL_SUBJECT_PREFIX = EMAIL_SUBJECT_PREFIX

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL regex.
ADMIN_URL = env("DJANGO_ADMIN_URL")

# Anymail
# ------------------------------------------------------------------------------
# https://anymail.readthedocs.io/en/stable/installation/#installing-anymail
INSTALLED_APPS += ["anymail"]
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
# https://anymail.readthedocs.io/en/stable/installation/#anymail-settings-reference
# https://anymail.readthedocs.io/en/stable/esps/sendgrid/
EMAIL_BACKEND = "anymail.backends.mailgun.EmailBackend"
ANYMAIL = {
    "MAILGUN_API_KEY": env("MAILGUN_API_KEY"),
    "MAILGUN_SENDER_DOMAIN": "midsphere.ai",
}

DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", default="no-reply@midsphere.ai")
SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default="no-reply@midsphere.ai")

# Collectfasta
# ------------------------------------------------------------------------------
# https://github.com/jasongi/collectfasta#installation
INSTALLED_APPS = ["collectfasta", *INSTALLED_APPS]

# LOGGING
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#logging
# See https://docs.djangoproject.com/en/dev/topics/logging for
# more details on how to customize your logging configuration.

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {
            "()": "config.logging.RequestIdFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "config.logging.StructuredJsonFormatter",
        },
        "rich": {
            "format": "%(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "filters": ["request_id"],
            "rich_tracebacks": True,
            "show_time": True,
            "show_path": False,
            "markup": True,
        },
        "json": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "apps.agents": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps.billing": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps.storage": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps.workspace": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "config.middleware": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
        "django.db.backends": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
        # Errors logged by the SDK itself
        "sentry_sdk": {"level": "ERROR", "handlers": ["console"], "propagate": False},
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": False,
        },
    },
}

# Sentry
# ------------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN")
SENTRY_LOG_LEVEL = env.int("DJANGO_SENTRY_LOG_LEVEL", logging.INFO)

sentry_logging = LoggingIntegration(
    level=SENTRY_LOG_LEVEL,  # Capture info and above as breadcrumbs
    event_level=logging.ERROR,  # Send errors as events
)
integrations = [
    sentry_logging,
    DjangoIntegration(),
    CeleryIntegration(),
    RedisIntegration(),
]
sentry_sdk.init(
    dsn=SENTRY_DSN,
    integrations=integrations,
    environment=env("SENTRY_ENVIRONMENT", default="production"),
    # Default 0.0 disables tracing; set SENTRY_TRACES_SAMPLE_RATE env var to enable
    traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0),
)


# CORS
# ------------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "https://midsphere.ai",
        "https://app.midsphere.ai",
        "https://platform.midsphere.ai",
    ],
)
CORS_ALLOW_CREDENTIALS = True

# Your stuff...
# ------------------------------------------------------------------------------
