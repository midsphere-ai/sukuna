# ruff: noqa: ERA001, E501
"""Base settings to build other settings files upon."""

import ssl
from pathlib import Path

import environ
from celery.schedules import crontab

from .unfold import *  # noqa: F403

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent.parent
# sukuna/
APPS_DIR = BASE_DIR / "sukuna"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=True)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    env.read_env(str(BASE_DIR / ".env"))

# GENERAL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#debug
DEBUG = env.bool("DJANGO_DEBUG", False)
# Local time zone. Choices are
# http://en.wikipedia.org/wiki/List_of_tz_zones_by_name
# though not all of them may be available with every OS.
# In Windows, this must be set to your system time zone.
TIME_ZONE = "GMT"
# https://docs.djangoproject.com/en/dev/ref/settings/#language-code
LANGUAGE_CODE = "en-us"
# https://docs.djangoproject.com/en/dev/ref/settings/#languages
# https://docs.djangoproject.com/en/dev/ref/settings/#site-id
SITE_ID = 1
# https://docs.djangoproject.com/en/dev/ref/settings/#use-i18n
USE_I18N = True
# https://docs.djangoproject.com/en/dev/ref/settings/#use-tz
USE_TZ = True
# https://docs.djangoproject.com/en/dev/ref/settings/#locale-paths
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# DATABASES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#databases
DB_CONN_MAX_AGE = max(env.int("DJANGO_DB_CONN_MAX_AGE", default=60), 0)
DB_CONN_HEALTH_CHECKS = env.bool("DJANGO_DB_CONN_HEALTH_CHECKS", default=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": f"{env('POSTGRES_DB')}",
        "USER": f"{env('POSTGRES_USER')}",
        "PASSWORD": f"{env('POSTGRES_PASSWORD')}",
        "HOST": f"{env('POSTGRES_HOST')}",
        "PORT": f"{env('POSTGRES_PORT')}",
        "CONN_MAX_AGE": DB_CONN_MAX_AGE,
        "CONN_HEALTH_CHECKS": DB_CONN_HEALTH_CHECKS,
        "ASYNC": True,
        "OPTIONS": {"server_side_binding": True},
    }
}

# https://docs.djangoproject.com/en/stable/ref/settings/#std:setting-DEFAULT_AUTO_FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#root-urlconf
ROOT_URLCONF = "config.urls"
# https://docs.djangoproject.com/en/dev/ref/settings/#wsgi-application
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"
# APPS
# ------------------------------------------------------------------------------

UNFOLD_APPS = [
    "unfold",  # before django.contrib.admin
    "unfold.contrib.filters",  # optional, if special filters are needed
    "unfold.contrib.forms",  # optional, if special form elements are needed
    "unfold.contrib.inlines",  # optional, if special inlines are needed
    "unfold.contrib.import_export",  # optional, if django-import-export package is used
    "unfold.contrib.guardian",  # optional, if django-guardian package is used
    "unfold.contrib.simple_history",  # optional, if django-simple-history package is used
    "unfold.contrib.location_field",  # optional, if django-location-field package is used
    "unfold.contrib.constance",  # optional, if django-constance package is used
]

DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # "django.contrib.humanize", # Handy template tags
    "django.contrib.admin",
    "django.forms",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.github",
    "allauth.socialaccount.providers.microsoft",
    "allauth.socialaccount.providers.apple",
    "rest_framework.authtoken",
    "dj_rest_auth",
    "django_celery_beat",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.users",
    "apps.blogs",
    "apps.storage",
    "apps.billing",
    "apps.workspace",
    "apps.spaces",
    "apps.agents",
    "apps.compliance",
    "apps.claw",
    # Your stuff: custom apps go here
]
# https://docs.djangoproject.com/en/dev/ref/settings/#installed-apps
INSTALLED_APPS = UNFOLD_APPS + DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIGRATIONS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#migration-modules
MIGRATION_MODULES = {
    "sites": "sukuna.contrib.sites.migrations",
    "mfa": "sukuna.contrib.mfa.migrations",
}

# AUTHENTICATION
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#authentication-backends
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-user-model
AUTH_USER_MODEL = "users.User"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-redirect-url
LOGIN_REDIRECT_URL = "users:redirect"
# https://docs.djangoproject.com/en/dev/ref/settings/#login-url
LOGIN_URL = "account_login"

# PASSWORDS
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#password-hashers
PASSWORD_HASHERS = [
    # https://docs.djangoproject.com/en/dev/topics/auth/passwords/#using-argon2-with-django
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
# https://docs.djangoproject.com/en/dev/ref/settings/#auth-password-validators
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# MIDDLEWARE
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.request_id.RequestIdMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.compliance.middleware.AuditMiddleware",
    "apps.compliance.security_middleware.SecurityPolicyMiddleware",
    "apps.workspace.ip_middleware.IPAllowlistMiddleware",
    "apps.workspace.ip_middleware.ConditionalAccessMiddleware",
    "apps.users.mfa_middleware.MFAEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "config.middleware.security.ContentSecurityPolicyMiddleware",
    "config.middleware.api_version.APIVersionHeaderMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "apps.users.adapters.APIKeyRateLimitMiddleware",
]

# STATIC
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#static-root
STATIC_ROOT = str(BASE_DIR / "staticfiles")
# https://docs.djangoproject.com/en/dev/ref/settings/#static-url
STATIC_URL = "/static/"
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#std:setting-STATICFILES_DIRS
STATICFILES_DIRS = [str(APPS_DIR / "static")]
# https://docs.djangoproject.com/en/dev/ref/contrib/staticfiles/#staticfiles-finders
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#media-root
MEDIA_ROOT = str(APPS_DIR / "media")
# https://docs.djangoproject.com/en/dev/ref/settings/#media-url
MEDIA_URL = "/media/"

# DigitalOcean Spaces Media URL (used for generating full URLs in API responses)
# Format: https://<bucket>.<region>.digitaloceanspaces.com/media/
DO_SPACES_MEDIA_URL = env("DO_SPACES_MEDIA_URL", default=None)

# TEMPLATES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#templates
TEMPLATES = [
    {
        # https://docs.djangoproject.com/en/dev/ref/settings/#std:setting-TEMPLATES-BACKEND
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # https://docs.djangoproject.com/en/dev/ref/settings/#dirs
        "DIRS": [str(APPS_DIR / "templates")],
        # https://docs.djangoproject.com/en/dev/ref/settings/#app-dirs
        "APP_DIRS": True,
        "OPTIONS": {
            # https://docs.djangoproject.com/en/dev/ref/settings/#template-context-processors
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
                "apps.users.context_processors.allauth_settings",
            ],
        },
    },
]

# https://docs.djangoproject.com/en/dev/ref/settings/#form-renderer
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"

# http://django-crispy-forms.readthedocs.io/en/latest/install.html#template-packs
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# FIXTURES
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#fixture-dirs
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# SECURITY
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#session-cookie-httponly
SESSION_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#csrf-cookie-httponly
CSRF_COOKIE_HTTPONLY = True
# https://docs.djangoproject.com/en/dev/ref/settings/#x-frame-options
X_FRAME_OPTIONS = "DENY"

# EMAIL
# ------------------------------------------------------------------------------
# https://docs.djangoproject.com/en/dev/ref/settings/#email-backend
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
# https://docs.djangoproject.com/en/dev/ref/settings/#email-timeout
EMAIL_TIMEOUT = 5

# ADMIN
# ------------------------------------------------------------------------------
# Django Admin URL.
ADMIN_URL = "admin/"
# https://docs.djangoproject.com/en/dev/ref/settings/#admins
ADMINS = [("Admin", "admin@example.com")]
# https://docs.djangoproject.com/en/dev/ref/settings/#managers
MANAGERS = ADMINS
# https://cookiecutter-django.readthedocs.io/en/latest/settings.html#other-environment-settings
# Force the `admin` sign in process to go through the `django-allauth` workflow
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

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
        "pii_redaction": {
            "()": "apps.compliance.log_filters.PIIRedactionFilter",
        },
    },
    "formatters": {
        "rich": {
            "format": "%(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "rich.logging.RichHandler",
            "formatter": "rich",
            "filters": ["request_id", "pii_redaction"],
            "rich_tracebacks": True,
            "show_time": True,
            "show_path": False,
            "markup": True,
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "apps.agents": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
        "apps.billing": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "apps.storage": {"level": "DEBUG", "handlers": ["console"], "propagate": False},
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
    },
}

# Celery Redis configuration
CELERY_REDIS_URL = env("CELERY_REDIS_URL")
CELERY_REDIS_SSL = CELERY_REDIS_URL.startswith("rediss://")

# General Redis URL for caching/channels (defaults to Celery Redis)
REDIS_URL = env("REDIS_URL", default=CELERY_REDIS_URL)
ARQ_REDIS_URL = env("ARQ_REDIS_URL", default=REDIS_URL)

# Celery
# ------------------------------------------------------------------------------
if USE_TZ:
    # https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-timezone
    CELERY_TIMEZONE = TIME_ZONE
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-broker_url
CELERY_BROKER_URL = CELERY_REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_BROKER_USE_SSL = (
    {"ssl_cert_reqs": ssl.CERT_REQUIRED} if CELERY_REDIS_SSL else None
)
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_backend
CELERY_RESULT_BACKEND = CELERY_REDIS_URL
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#redis-backend-use-ssl
CELERY_REDIS_BACKEND_USE_SSL = (
    {"ssl_cert_reqs": ssl.CERT_REQUIRED} if CELERY_REDIS_SSL else None
)
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-extended
CELERY_RESULT_EXTENDED = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-always-retry
# https://github.com/celery/celery/pull/6122
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#result-backend-max-retries
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-accept_content
CELERY_ACCEPT_CONTENT = ["json"]
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-task_serializer
CELERY_TASK_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std:setting-result_serializer
CELERY_RESULT_SERIALIZER = "json"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_TIME_LIMIT = 120 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#task-soft-time-limit
# TODO: set to whatever value is adequate in your circumstances
CELERY_TASK_SOFT_TIME_LIMIT = 110 * 60
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#beat-scheduler
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-send-task-events
CELERY_WORKER_SEND_TASK_EVENTS = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#std-setting-task_send_sent_event
CELERY_TASK_SEND_SENT_EVENT = True
# https://docs.celeryq.dev/en/stable/userguide/configuration.html#worker-hijack-root-logger
CELERY_WORKER_HIJACK_ROOT_LOGGER = False

CELERY_TASK_ACKS_LATE = True

CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_BEAT_SCHEDULE = {
    "purge_empty_conversations": {
        "task": "apps.storage.tasks.purge_empty_conversations",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
    },
    "set_title_conversations": {
        "task": "apps.storage.tasks.set_title_conversations",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
    },
    "check-expired-subscriptions": {
        "task": "apps.billing.tasks.check_expired_subscriptions",
        "schedule": crontab(minute=0),  # Every hour
    },
    "notify-expiring-subscriptions": {
        "task": "apps.billing.tasks.notify_expiring_subscriptions",
        "schedule": crontab(hour=9, minute=0),  # 9 AM daily
    },
    "process-scheduled-plan-changes": {
        "task": "apps.billing.tasks.process_scheduled_plan_changes",
        "schedule": crontab(hour=0, minute=0),  # Midnight daily
    },
    "retry-failed-payments": {
        "task": "apps.billing.tasks.retry_failed_payments",
        "schedule": crontab(hour=10, minute=0),  # 10 AM daily
    },
    "end-grace-periods": {
        "task": "apps.billing.tasks.end_grace_periods",
        "schedule": crontab(minute=30),  # Every hour at 30 minutes
    },
    "check-trial-conversions": {
        "task": "apps.billing.tasks.check_trial_conversions",
        "schedule": crontab(hour=8, minute=0),  # 8 AM daily
    },
    "sync-with-dodo": {
        "task": "apps.billing.tasks.sync_subscriptions_with_dodo",
        "schedule": crontab(hour=2, minute=0),  # 2 AM daily
    },
    "cleanup-old-data": {
        "task": "apps.billing.tasks.cleanup_old_data",
        "schedule": crontab(hour=3, minute=0, day_of_week=0),  # 3 AM every Sunday
    },
    "generate-daily-report": {
        "task": "apps.billing.tasks.generate_daily_report",
        "schedule": crontab(hour=23, minute=0),  # 11 PM daily
    },
    "terminate-delayed-sandboxes": {
        "task": "apps.agents.tasks.terminate_delayed_sandboxes",
        "schedule": crontab(minute="*/2"),  # Every 2 minutes
    },
    "monitor-assigned-sandboxes": {
        "task": "apps.agents.tasks.monitor_assigned_sandboxes",
        "schedule": crontab(minute="*/2"),  # Every 2 minutes
    },
    "check-pending-addon-authorizations": {
        "task": "apps.storage.tasks.check_pending_addon_authorizations",
        "schedule": 30.0,  # Every 30 seconds for near real-time auth updates
    },
    "expire-addon-auth-links": {
        "task": "apps.storage.tasks.expire_auth_links",
        "schedule": crontab(minute="*/30"),  # Every 30 minutes
    },
    "replenish-sandbox-pool": {
        "task": "apps.agents.tasks.replenish_sandbox_pool",
        "schedule": 60.0,  # Every 60 seconds
    },
    "expire-stale-pool-sandboxes": {
        "task": "apps.agents.tasks.expire_stale_pool_sandboxes",
        "schedule": crontab(minute="*/5"),  # Every 5 minutes
    },
    "kill-orphaned-sandboxes": {
        "task": "apps.agents.tasks.kill_orphaned_sandboxes",
        "schedule": crontab(minute="*/3"),  # Every 3 minutes
    },
    "apply-retention-policies": {
        "task": "apps.compliance.tasks.apply_retention_policies",
        "schedule": crontab(hour=3, minute=0),  # Daily at 3 AM UTC
    },
    "check-sso-certificate-expiry": {
        "task": "apps.compliance.tasks.check_sso_certificate_expiry",
        "schedule": crontab(hour=4, minute=0),  # Daily at 4 AM UTC
    },
    "run-compliance-exports": {
        "task": "apps.compliance.tasks.run_compliance_exports",
        "schedule": crontab(hour=5, minute=0),  # Daily at 5 AM UTC
    },
    "archive-idle-conversations": {
        "task": "apps.compliance.tasks.archive_idle_conversations",
        "schedule": crontab(minute=0),  # Every hour
    },
    "reset-project-budgets-monthly": {
        "task": "apps.workspace.tasks.reset_project_budgets_monthly",
        "schedule": crontab(
            day_of_month=1, hour=0, minute=5
        ),  # 1st of month at 00:05 UTC
    },
}


# django-allauth
# ------------------------------------------------------------------------------
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_LOGIN_METHODS = {"email"}
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_EMAIL_VERIFICATION = "optional"
# https://docs.allauth.org/en/latest/account/configuration.html
ACCOUNT_ADAPTER = "apps.users.adapters.AccountAdapter"
# https://docs.allauth.org/en/latest/account/forms.html
ACCOUNT_FORMS = {"signup": "apps.users.forms.UserSignupForm"}
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_ADAPTER = "apps.users.adapters.SocialAccountAdapter"
# https://docs.allauth.org/en/latest/socialaccount/configuration.html
SOCIALACCOUNT_FORMS = {"signup": "apps.users.forms.UserSocialSignupForm"}

SOCIALACCOUNT_PROVIDERS = {
    "google": {
        "SCOPE": [
            "profile",
            "email",
        ],
        "AUTH_PARAMS": {
            "access_type": "online",
        },
        "OAUTH_PKCE_ENABLED": True,
    },
    "github": {
        "SCOPE": [
            "read:user",
            "user:email",
        ],
        "APP": {
            "client_id": env("GITHUB_OAUTH_CLIENT_ID", default=""),
            "secret": env("GITHUB_OAUTH_CLIENT_SECRET", default=""),
        },
    },
    "microsoft": {
        "SCOPE": [
            "openid",
            "profile",
            "email",
            "User.Read",
        ],
        "APP": {
            "client_id": env("MICROSOFT_OAUTH_CLIENT_ID", default=""),
            "secret": env("MICROSOFT_OAUTH_CLIENT_SECRET", default=""),
        },
        "TENANT": env("MICROSOFT_OAUTH_TENANT", default="common"),
    },
    "apple": {
        "SCOPE": [
            "email",
            "name",
        ],
        "APP": {
            "client_id": env("APPLE_OAUTH_CLIENT_ID", default=""),
            "secret": env("APPLE_OAUTH_CLIENT_SECRET", default=""),
            "key": env("APPLE_OAUTH_KEY_ID", default=""),
        },
        "CERTIFICATE_KEY": env("APPLE_OAUTH_CERTIFICATE_KEY", default=""),
    },
}
# Account linking: auto-connect social accounts to existing users with matching email
SOCIALACCOUNT_EMAIL_AUTHENTICATION_AUTO_CONNECT = True


# MFA (allauth.mfa)
# ------------------------------------------------------------------------------
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes", "webauthn"]
MFA_TOTP_ISSUER = "Jatayu AI"

# SESSION SECURITY
# ------------------------------------------------------------------------------
# Global session timeout: 24 hours (overridable per-org)
SESSION_COOKIE_AGE = 60 * 60 * 24  # 24 hours in seconds
# Sliding window: reset expiry on every request so active users stay logged in
SESSION_SAVE_EVERY_REQUEST = True

# Global defaults for org-level security policies
SECURITY_DEFAULT_SESSION_TIMEOUT_MINUTES = 24 * 60  # 24 hours
SECURITY_DEFAULT_MAX_CONCURRENT_SESSIONS = 5
SECURITY_MIN_SESSION_TIMEOUT_MINUTES = 5  # orgs cannot set below 5 minutes
SECURITY_MAX_SESSION_TIMEOUT_MINUTES = 43200  # 30 days
# ------------------------------------------------------------------------------
# Django REST Framework
# ------------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
}

# CORS
# ------------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=True)
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=False)

CSRF_TRUSTED_ORIGINS = ["http://localhost:8000"]

NGROK_DOMAIN = env("NGROK_DOMAIN", default="")
if NGROK_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f"https://{NGROK_DOMAIN}")


# Payments — Dodo Payments
# ------------------------------------------------------------------------------
DODO_PAYMENTS_API_KEY = env("DODO_PAYMENTS_API_KEY", default="")
DODO_PAYMENTS_WEBHOOK_SECRET = env("DODO_PAYMENTS_WEBHOOK_SECRET", default="")
DODO_PAYMENTS_ENVIRONMENT = env("DODO_PAYMENTS_ENVIRONMENT", default="test_mode")
DODO_ADDON_PACK_PRODUCT_ID = env("DODO_ADDON_PACK_PRODUCT_ID", default="")
FRONTEND_URL = env("FRONTEND_URL", default="http://localhost:5173")
ADMIN_EMAIL = "billing@midsphere.ai"


# Agent defaults
# ------------------------------------------------------------------------------
COMPOSIO_KEY = env("COMPOSIO_KEY")
AGENT_SERVER_API_KEY = env(
    "AGENT_SERVER_API_KEY",
    default=env(
        "SUKUNA_AGENT_SERVER_API_KEY",
        default=env("API_KEY", default="midsphere-internal"),
    ),
)
SERPER_API_KEY = env("SERPER_API_KEY")
JINA_API_KEY = env("JINA_API_KEY")

# E2B sandbox template name
AGENT_SANDBOX_TEMPLATE = env(
    "AGENT_SANDBOX_TEMPLATE", default="exo-native-agent-sandbox"
)

# Port inside E2B sandbox where the agent server listens
SANDBOX_AGENT_SERVER_PORT = env.int("SANDBOX_AGENT_SERVER_PORT", default=8000)

# Number of prewarmed pool sandboxes to keep ready (0 to disable)
SANDBOX_POOL_SIZE = env.int("SANDBOX_POOL_SIZE", default=2)

# Direct stream JWT settings (backend -> sandbox UI stream auth)
# Preferred env key: SUKUNA_STREAM_JWT_SECRET
# Legacy fallback: SANDBOX_STREAM_JWT_SECRET
SUKUNA_STREAM_JWT_SECRET = env(
    "SUKUNA_STREAM_JWT_SECRET",
    default=env("SANDBOX_STREAM_JWT_SECRET", default=""),
)
SANDBOX_STREAM_JWT_ISSUER = env("SANDBOX_STREAM_JWT_ISSUER", default="sukuna-backend")
SANDBOX_STREAM_JWT_AUDIENCE = env(
    "SANDBOX_STREAM_JWT_AUDIENCE",
    default="sukuna-sandbox-stream",
)
SANDBOX_STREAM_JWT_TTL_SECONDS = env.int("SANDBOX_STREAM_JWT_TTL_SECONDS", default=120)
SANDBOX_DESKTOP_STREAM_TTL_SECONDS = env.int(
    "SANDBOX_DESKTOP_STREAM_TTL_SECONDS",
    default=120,
)

# Optional default lease limits forwarded to sandbox on run creation.
# Set to 0 to disable each limit.
SANDBOX_LEASE_MAX_RUNTIME_SECONDS = env.int(
    "SANDBOX_LEASE_MAX_RUNTIME_SECONDS",
    default=0,
)

# BYOM (Bring Your Own Model) — Fernet encryption key for user API keys at rest.
# Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
BYOM_ENCRYPTION_KEY = env("BYOM_ENCRYPTION_KEY", default="")
# Telegram bot integration — token from @BotFather, secret for webhook validation
TELEGRAM_BOT_TOKEN = env("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_WEBHOOK_SECRET = env("TELEGRAM_WEBHOOK_SECRET", default="")
# Slack bot integration
SLACK_BOT_TOKEN = env("SLACK_BOT_TOKEN", default="")
SLACK_SIGNING_SECRET = env("SLACK_SIGNING_SECRET", default="")
SLACK_CLIENT_ID = env("SLACK_CLIENT_ID", default="")
SLACK_CLIENT_SECRET = env("SLACK_CLIENT_SECRET", default="")
# Discord bot integration
DISCORD_BOT_TOKEN = env("DISCORD_BOT_TOKEN", default="")

SANDBOX_LEASE_MAX_TOTAL_TOKENS = env.int("SANDBOX_LEASE_MAX_TOTAL_TOKENS", default=0)
SANDBOX_LEASE_MAX_COST_USD = env.float("SANDBOX_LEASE_MAX_COST_USD", default=0.0)


# Managed Provider defaults
# ------------------------------------------------------------------------------
# Managed Super Agent defaults
MANAGED_SUPER_LLM_PROVIDER = env("MANAGED_SUPER_LLM_PROVIDER", default="openai")
MANAGED_SUPER_LLM_MODEL = env("MANAGED_SUPER_LLM_MODEL", default="gpt-4o")
MANAGED_SUPER_LLM_API_KEY = env("MANAGED_SUPER_LLM_API_KEY")
MANAGED_SUPER_LLM_BASE_URL = env("MANAGED_SUPER_LLM_BASE_URL")

# Managed Reasoning Agent defaults
REASONING_USE_SAME_AS_SUPER = env("REASONING_USE_SAME_AS_SUPER", default=False)

if REASONING_USE_SAME_AS_SUPER:
    MANAGED_REASONING_LLM_PROVIDER = MANAGED_SUPER_LLM_PROVIDER
    MANAGED_REASONING_LLM_MODEL = MANAGED_SUPER_LLM_MODEL
    MANAGED_REASONING_LLM_API_KEY = MANAGED_SUPER_LLM_API_KEY
    MANAGED_REASONING_LLM_BASE_URL = MANAGED_SUPER_LLM_BASE_URL
else:
    MANAGED_REASONING_LLM_PROVIDER = env(
        "MANAGED_REASONING_LLM_PROVIDER", default="openai"
    )
    MANAGED_REASONING_LLM_MODEL = env("MANAGED_REASONING_LLM_MODEL", default="gpt-4o")
    MANAGED_REASONING_LLM_API_KEY = env("MANAGED_REASONING_LLM_API_KEY")
    MANAGED_REASONING_LLM_BASE_URL = env("MANAGED_REASONING_LLM_BASE_URL")


# Managed Vision Agent defaults
VISION_USE_SAME_AS_SUPER = env("VISION_USE_SAME_AS_SUPER", default=False)

if VISION_USE_SAME_AS_SUPER:
    MANAGED_VISION_LLM_PROVIDER = MANAGED_SUPER_LLM_PROVIDER
    MANAGED_VISION_LLM_MODEL = MANAGED_SUPER_LLM_MODEL
    MANAGED_VISION_LLM_API_KEY = MANAGED_SUPER_LLM_API_KEY
    MANAGED_VISION_LLM_BASE_URL = MANAGED_SUPER_LLM_BASE_URL
else:
    MANAGED_VISION_LLM_PROVIDER = env("MANAGED_VISION_LLM_PROVIDER", default="openai")
    MANAGED_VISION_LLM_MODEL = env("MANAGED_VISION_LLM_MODEL", default="gpt-4o")
    MANAGED_VISION_LLM_API_KEY = env("MANAGED_VISION_LLM_API_KEY")
    MANAGED_VISION_LLM_BASE_URL = env("MANAGED_VISION_LLM_BASE_URL")

# Managed Audio Agent defaults
AUDIO_USE_SAME_AS_SUPER = env("AUDIO_USE_SAME_AS_SUPER", default=False)

if AUDIO_USE_SAME_AS_SUPER:
    MANAGED_AUDIO_LLM_PROVIDER = MANAGED_SUPER_LLM_PROVIDER
    MANAGED_AUDIO_LLM_MODEL = MANAGED_SUPER_LLM_MODEL
    MANAGED_AUDIO_LLM_API_KEY = MANAGED_SUPER_LLM_API_KEY
    MANAGED_AUDIO_LLM_BASE_URL = MANAGED_SUPER_LLM_BASE_URL
else:
    MANAGED_AUDIO_LLM_PROVIDER = env("MANAGED_AUDIO_LLM_PROVIDER", default="openai")
    MANAGED_AUDIO_LLM_MODEL = env("MANAGED_AUDIO_LLM_MODEL", default="gpt-4o")
    MANAGED_AUDIO_LLM_API_KEY = env("MANAGED_AUDIO_LLM_API_KEY")
    MANAGED_AUDIO_LLM_BASE_URL = env("MANAGED_AUDIO_LLM_BASE_URL")

# Managed Media Gen Agent defaults
MANAGED_VIDEO_GENERATION_MODEL = env("MANAGED_VIDEO_GENERATION_MODEL", default="gpt-4o")
MANAGED_IMAGE_GENERATION_MODEL = env("MANAGED_IMAGE_GENERATION_MODEL", default="gpt-4o")
GOOGLE_CREDENTIALS = None
