"""API endpoints for marketplace addon management, user addons, and MCP configurations."""

import logging
from typing import List

from django.core.cache import cache
from django.core.handlers.wsgi import WSGIRequest
from ninja.pagination import paginate

from apps.agents.models import UserCustomMCPConfig
from apps.agents.schemas import (
    MCPConfigDeletionResultSchema,
    MCPConfigResultSchema,
    UserCustomMCPConfigInputSchema,
    UserCustomMCPConfigSchema,
)
from apps.storage.factory.addons import get_addon_service
from apps.storage.schemas.addons import (
    AddonAuthenticationStatus,
    AddonAuthLink,
    AddonConnectionStatus,
    ExpandedAddon,
    MarketplaceAddonModelSchema,
    RegisterAddon,
    RegisterAddonResult,
    UnRegisterAddonResult,
    UserAddonModelSchema,
)
from apps.storage.views import CustomPageNumberPagination, SmallPagination, memory_api
from config.errors.common import NotFoundError

logger = logging.getLogger(__name__)

# Cache TTLs for marketplace endpoints (seconds)
MARKETPLACE_CACHE_TTL = 5 * 60  # 5 minutes
MARKETPLACE_CACHE_PREFIX = "marketplace_addons"


def _invalidate_expanded_addon_cache(user_id: str, addon_id: str) -> None:
    """Invalidate the expanded addon cache for a specific user+addon."""
    cache.delete(f"{MARKETPLACE_CACHE_PREFIX}:expanded:{addon_id}:user:{user_id}")


@memory_api.post("/addons/register", response=RegisterAddonResult)
def register_addon(
    request: WSGIRequest,
    data: RegisterAddon,
):
    """Register a marketplace addon for the authenticated user."""
    service = get_addon_service()
    result = service.register_addon(request, data.addon_id)
    _invalidate_expanded_addon_cache(str(request.auth.id), data.addon_id)
    return result


@memory_api.delete("/user-addons/{user_addon_id}", response=UnRegisterAddonResult)
def unregister_addon(
    request: WSGIRequest,
    user_addon_id: str,
):
    """Unregister and remove a user addon by ID."""
    service = get_addon_service()
    result = service.unregister_addon(request, user_addon_id)
    # Invalidate expanded cache — we don't know the addon_id here, but the
    # TTL is short enough that stale data will clear quickly.
    return result


@memory_api.get("/user-addons/{user_addon_id}/auth-link", response=AddonAuthLink)
def get_addon_auth_link(
    request: WSGIRequest,
    user_addon_id: str,
):
    """Get or generate an OAuth authentication link for a user addon."""
    service = get_addon_service()
    return service.get_addon_auth_link(request, user_addon_id)


@memory_api.post(
    "/user-addons/{user_addon_id}/refresh-auth", response=AddonAuthenticationStatus
)
def check_and_update_auth_status(
    request: WSGIRequest,
    user_addon_id: str,
):
    """Check and refresh the authentication status of a user addon."""
    service = get_addon_service()
    return service.check_and_update_auth_status(request, user_addon_id)


@memory_api.get(
    "/user-addons/{user_addon_id}/connection-status", response=AddonConnectionStatus
)
def get_addon_connection_status(
    request: WSGIRequest,
    user_addon_id: str,
):
    """
    Get the current connection status for a user addon.

    This is a lightweight status check that queries Composio directly
    without updating the database. Useful for polling during OAuth flow.

    Returns connection status values:
    - ACTIVE: Connection is established and working
    - INITIATED: OAuth flow started but not completed
    - PENDING: Being processed
    - EXPIRED: Credentials expired
    - FAILED: Connection attempt failed
    - INACTIVE: Temporarily disabled
    - NOT_INITIATED: No auth link generated yet
    """
    service = get_addon_service()
    user = request.auth
    result = service.get_addon_connection_status(user_addon_id, user.id)
    return AddonConnectionStatus(
        user_addon_id=result["addon_id"],
        addon_name=result["addon_name"],
        status=result["status"],
        is_active=result["is_active"],
        auth_complete=result["auth_complete"],
    )


@memory_api.post(
    "/user-addons/{user_addon_id}/regenerate-auth-link", response=AddonAuthLink
)
def regenerate_addon_auth_link(
    request: WSGIRequest,
    user_addon_id: str,
):
    """
    Regenerate an expired or failed authentication link for a user addon.

    Use this endpoint when:
    - The previous auth link has expired (status: EXPIRED)
    - The OAuth flow failed (status: FAILED)
    - The connection became inactive (status: INACTIVE)

    This endpoint will NOT regenerate if:
    - The addon is already authorized (status: ACTIVE) - returns 400
    - The auth flow is still in progress (status: INITIATED/PENDING) - returns 400

    Returns:
        AddonAuthLink: The newly generated auth link
    """
    service = get_addon_service()
    return service.regenerate_auth_link(request, user_addon_id)


@memory_api.get("/user-addons", response=List[UserAddonModelSchema])
@paginate(CustomPageNumberPagination)
def get_user_addons(request: WSGIRequest):
    """Get all registered addons for the authenticated user with pagination."""
    service = get_addon_service()
    return service.get_user_addons(request)


@memory_api.get("/user-addons/search", response=List[UserAddonModelSchema])
@paginate(CustomPageNumberPagination)
def search_user_addons(request: WSGIRequest, query: str, auth_complete: bool = False):
    """
    Search user addons by query string.

    Args:
        query: Search query string
        auth_complete: Filter by authentication status

    Returns:
        List[UserAddonModelSchema]: Paginated list of matching user addons
    """
    service = get_addon_service()
    return service.search_user_addons(
        request=request, query=query, auth_complete=auth_complete
    )


@memory_api.get("/addons", response=List[MarketplaceAddonModelSchema])
@paginate(CustomPageNumberPagination)
def get_all_addons(request: WSGIRequest):
    """Get all available marketplace addons with pagination."""
    page = request.GET.get("page", "1")
    cache_key = f"{MARKETPLACE_CACHE_PREFIX}:all:page:{page}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    service = get_addon_service()
    result = list(service.get_all_addons())
    cache.set(cache_key, result, MARKETPLACE_CACHE_TTL)
    return result


@memory_api.get("/addons/search", response=List[MarketplaceAddonModelSchema])
@paginate(CustomPageNumberPagination)
def search_all_addons(request: WSGIRequest, query: str):
    """
    Search marketplace addons by query string.

    Args:
        query: Search query string

    Returns:
        List[MarketplaceAddonModelSchema]: Paginated list of matching addons
    """
    page = request.GET.get("page", "1")
    cache_key = f"{MARKETPLACE_CACHE_PREFIX}:search:{query}:{page}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    service = get_addon_service()
    result = list(service.search_marketplace_addons(query=query))
    cache.set(cache_key, result, MARKETPLACE_CACHE_TTL)
    return result


@memory_api.get("/addons/{addon_id}", response=ExpandedAddon)
def get_expanded_addon(
    request: WSGIRequest,
    addon_id: str,
):
    """Get expanded details for a marketplace addon including user registration and features."""
    cache_key = f"{MARKETPLACE_CACHE_PREFIX}:expanded:{addon_id}:user:{request.auth.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    service = get_addon_service()
    result = service.get_expanded_addon(request, addon_id)
    cache.set(cache_key, result, MARKETPLACE_CACHE_TTL)
    return result


# --- MCP Config endpoints ---


@memory_api.post("/mcp-configs", response=MCPConfigResultSchema, tags=["MCP Configs"])
def register_mcp_config(request: WSGIRequest, data: UserCustomMCPConfigInputSchema):
    """
    Register a new Custom MCP Config for the authenticated user.
    """
    config, _created = UserCustomMCPConfig.objects.update_or_create(
        user=request.auth,
        server_name=data.server_name,
        defaults={
            "server_type": data.server_type or "stdio",
            "command": data.command or "",
            "arguments": data.arguments or "",
            "env": data.env or "",
            "description": data.description or "",
            "url": data.url or "",
            "timeout": data.timeout,
            "sse_read_timeout": data.sse_read_timeout,
            "client_session_timeout_seconds": data.client_session_timeout_seconds,
        },
    )
    return {"id": str(config.id)}


@memory_api.delete(
    "/mcp-configs/{config_id}",
    response=MCPConfigDeletionResultSchema,
    tags=["MCP Configs"],
)
def unregister_mcp_config(request: WSGIRequest, config_id: str):
    """
    Unregister (delete) a Custom MCP Config for the authenticated user.
    """
    try:
        config = UserCustomMCPConfig.objects.get(id=config_id, user=request.auth)
    except UserCustomMCPConfig.DoesNotExist:
        raise NotFoundError("MCP config not found")
    config.delete()
    return {"id": config_id, "deleted": True}


@memory_api.get(
    "/mcp-configs", response=List[UserCustomMCPConfigSchema], tags=["MCP Configs"]
)
@paginate(SmallPagination)
def get_mcp_configs(request: WSGIRequest):
    """
    Get all MCP configurations for the authenticated user.
    """
    return UserCustomMCPConfig.objects.filter(user=request.auth)
