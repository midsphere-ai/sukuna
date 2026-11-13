"""Root URL configuration for the Sukuna Django project.

Maps top-level URL patterns to the individual application routers,
health-check endpoints, the Django admin, and debug/error pages.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from django.views import defaults as default_views
from django.views.generic import TemplateView

from apps.agents.byom import byom_api
from apps.users.developer_views import developer_api
from apps.users.mfa_api import mfa_api
from config.developer_docs import developer_openapi_spec
from config.health import (
    health_check,
    liveness_check,
    readiness_check,
)


def trigger_error(request):
    """Intentionally raise an exception for Sentry error-reporting verification."""
    1 / 0


_v1_patterns = [
    path("", include("apps.workspace.urls")),
    path("", include("apps.storage.urls")),
    path("", include("apps.spaces.urls")),
    path("", include("apps.blogs.urls")),
    path("", include("apps.billing.urls")),
    # Agent execution API (proxy to sandbox agent server)
    path("", include("apps.agents.urls")),
    # GDPR / compliance endpoints
    path("", include("apps.compliance.urls")),
    # BYOM (Bring Your Own Model) — user LLM provider config
    path("byom/", byom_api.urls),
    # Multi-factor authentication
    path("", mfa_api.urls),
    # Developer API key management
    path("developer/", developer_api.urls),
    # Developer API documentation (combined OpenAPI spec)
    path(
        "developer/openapi.json", developer_openapi_spec, name="developer_openapi_spec"
    ),
]

urlpatterns = [
    # Health check endpoints for load balancers and Kubernetes
    path("health/", health_check, name="health_check"),
    path("live/", liveness_check, name="liveness_check"),
    path("ready/", readiness_check, name="readiness_check"),
    path("", TemplateView.as_view(template_name="pages/home.html"), name="home"),
    path("authentication/", include("dj_rest_auth.urls")),
    path("accounts/", include("allauth.urls")),
    path(settings.ADMIN_URL, admin.site.urls),
    path("users/", include("apps.users.urls")),
    # Versioned public API — all public endpoints live under /api/v1/
    path("api/v1/", include(_v1_patterns)),
    *static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT),
]
if settings.DEBUG:
    # Static file serving when using Gunicorn + Uvicorn for local web socket development
    urlpatterns += staticfiles_urlpatterns()


if settings.DEBUG:
    # Sentry debug endpoint - only available in DEBUG mode
    urlpatterns += [path("sentry-debug/", trigger_error)]
    # This allows the error pages to be debugged during development, just visit
    # these url in browser to see how these error pages look like.
    urlpatterns += [
        path(
            "400/",
            default_views.bad_request,
            kwargs={"exception": Exception("Bad Request!")},
        ),
        path(
            "403/",
            default_views.permission_denied,
            kwargs={"exception": Exception("Permission Denied")},
        ),
        path(
            "404/",
            default_views.page_not_found,
            kwargs={"exception": Exception("Page not Found")},
        ),
        path("500/", default_views.server_error),
    ]
    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns = [
            path("__debug__/", include(debug_toolbar.urls)),
            *urlpatterns,
        ]
