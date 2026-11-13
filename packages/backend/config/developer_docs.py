"""Combined OpenAPI spec endpoint for developer documentation.

Aggregates OpenAPI schemas from all app NinjaAPI instances into a single
spec, filtering out internal/sensitive endpoints and grouping by category.
All public endpoints are served under the ``/api/v1/`` prefix.
"""

import copy

from django.http import JsonResponse
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_GET

# Current public API version prefix applied to all documented paths.
_API_VERSION_PREFIX = "/api/v1"

# Endpoints matching these path prefixes are filtered out of the public spec.
_INTERNAL_PATH_PREFIXES = (
    "/admin",
    "/webhook",
    "/internal",
    "/callback",
    "/sentry",
    "/health",
    "/live",
    "/ready",
)

# Map URL prefix → human-readable tag for grouping.
_PREFIX_TAG_MAP = {
    "/workspace": "Users & Auth",
    "/memory": "Conversations & Storage",
    "/chat": "Chat & Agent Runs",
    "/spaces": "Projects",
    "/billing": "Billing & Subscriptions",
    "/cms": "Content",
    "/developer": "Developer API Keys",
}


def _get_api_instances():
    """Lazy-import all NinjaAPI instances to avoid circular imports."""
    from apps.agents.views import agent_api, agent_public_api
    from apps.billing.views import billing_api
    from apps.billing.views import unsecured_api as billing_public_api
    from apps.blogs.views import api as blogs_public_api
    from apps.blogs.views import authenticated_api as blogs_auth_api
    from apps.spaces.views import spaces_api
    from apps.storage.views import memory_api, memory_public_api
    from apps.users.developer_views import developer_api
    from config.schemas.base import api as workspace_public_api
    from config.schemas.base import authenticated_api as workspace_auth_api

    return [
        ("/workspace", workspace_public_api),
        ("/workspace", workspace_auth_api),
        ("/memory", memory_api),
        ("/memory", memory_public_api),
        ("/chat", agent_api),
        ("/chat", agent_public_api),
        ("/spaces", spaces_api),
        ("/billing", billing_api),
        ("/billing", billing_public_api),
        ("/cms", blogs_auth_api),
        ("/cms", blogs_public_api),
        ("/developer", developer_api),
    ]


def _is_internal(path: str) -> bool:
    """Return True if the path should be excluded from public docs."""
    lower = path.lower()
    return any(lower.startswith(p) for p in _INTERNAL_PATH_PREFIXES)


def _tag_for_path(path: str) -> str:
    """Determine the display tag for a given path."""
    for prefix, tag in _PREFIX_TAG_MAP.items():
        if path.startswith(prefix):
            return tag
    return "Other"


def _build_combined_spec():
    """Merge all NinjaAPI OpenAPI schemas into one."""
    combined = {
        "openapi": "3.1.0",
        "info": {
            "title": "Jatayu AI API",
            "version": "1.0.0",
            "description": (
                "The Jatayu AI developer API. Use these endpoints to manage "
                "conversations, projects, billing, and more."
            ),
        },
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
        "tags": [],
    }

    seen_tags = set()

    for prefix, api_instance in _get_api_instances():
        try:
            schema = api_instance.get_openapi_schema()
        except Exception:
            continue

        # Merge paths, rewriting keys with the versioned mount prefix.
        for path, methods in (schema.get("paths") or {}).items():
            full_path = f"{prefix}{path}" if not path.startswith(prefix) else path

            if _is_internal(full_path):
                continue

            tag = _tag_for_path(full_path)
            # Prefix with the API version so documented paths match the URL scheme.
            full_path = f"{_API_VERSION_PREFIX}{full_path}"
            if tag not in seen_tags:
                seen_tags.add(tag)
                combined["tags"].append({"name": tag})

            # Inject tag into every operation.
            methods_copy = copy.deepcopy(methods)
            for method_detail in methods_copy.values():
                if isinstance(method_detail, dict):
                    method_detail["tags"] = [tag]

            if full_path in combined["paths"]:
                combined["paths"][full_path].update(methods_copy)
            else:
                combined["paths"][full_path] = methods_copy

        # Merge component schemas (simple union, last-write wins for dupes).
        for schema_name, schema_def in (
            schema.get("components", {}).get("schemas") or {}
        ).items():
            combined["components"]["schemas"][schema_name] = schema_def

    # Add Bearer auth security scheme.
    combined["components"]["securitySchemes"]["BearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "description": "Token-based authentication. Pass your auth token as a Bearer token.",
    }

    # Sort tags alphabetically.
    combined["tags"].sort(key=lambda t: t["name"])

    return combined


@require_GET
@cache_page(60 * 5)  # Cache for 5 minutes
def developer_openapi_spec(request):
    """Serve the combined OpenAPI JSON spec."""
    spec = _build_combined_spec()
    return JsonResponse(spec, json_dumps_params={"indent": 2})
