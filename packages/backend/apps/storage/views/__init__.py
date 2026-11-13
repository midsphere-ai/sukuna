"""Storage views package: NinjaAPI instances, pagination, settings, stats, and health endpoints."""

import logging
from typing import List

from django.core.handlers.wsgi import WSGIRequest
from ninja import NinjaAPI, Schema
from ninja.pagination import PageNumberPagination

from apps.users.adapters import AsyncTokenAuthentication, NinjaAuthAdapter  # noqa: E402
from config.cache.local import PersistentMem
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)


class CustomPageNumberPagination(PageNumberPagination):
    """Default pagination: 50 items per page, max 500."""

    def __init__(self, **kwargs):
        super().__init__(page_size=50, max_page_size=500, **kwargs)


class SmallPagination(PageNumberPagination):
    """Pagination for smaller lists: 20 items per page."""

    def __init__(self, **kwargs):
        super().__init__(page_size=20, max_page_size=100, **kwargs)


memory_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="storage")

# Unauthenticated API for public endpoints (e.g., shared conversations)
memory_public_api = NinjaAPI(urls_namespace="storage_public")

# Separate async API for SSE streaming endpoints
storage_stream_api = NinjaAPI(
    auth=AsyncTokenAuthentication(), urls_namespace="storage_stream"
)


register_error_handlers(memory_api)
register_error_handlers(memory_public_api)
register_error_handlers(storage_stream_api)

loc_cache = PersistentMem("loc_cache", {})


# --- Settings endpoints ---

from apps.storage.schemas.memory import (  # noqa: E402
    HealthResponse,
    UserSettingsSchema,
    UserSettingsUpdateSchema,
)


@memory_api.get("/settings", response=UserSettingsSchema, tags=["Settings"])
def get_settings(request: WSGIRequest):
    """Get the current user's settings (auto-creates on first access)."""
    from apps.users.models import UserSettings

    settings, _ = UserSettings.objects.get_or_create(user=request.auth)
    return settings


@memory_api.patch("/settings", response=UserSettingsSchema, tags=["Settings"])
def update_settings(request: WSGIRequest, payload: UserSettingsUpdateSchema):
    """Partially update the current user's settings."""
    from apps.users.models import UserSettings

    settings, _ = UserSettings.objects.get_or_create(user=request.auth)
    for field, value in payload.dict(exclude_unset=True).items():
        setattr(settings, field, value)
    settings.save()
    return settings


# --- Statistics endpoints ---


class UserStatsResponse(Schema):
    """Response for user statistics."""

    conversation_count: int
    files_uploaded: int


class CacheStatsResponse(Schema):
    """Response for cache statistics."""

    cache_size: int
    cache_keys: List[str]
    cache_type: str


@memory_api.get("/stats/user", response=UserStatsResponse)
def get_user_stats(
    request: WSGIRequest,
):
    """
    Get user statistics (conversation count, file count, etc.).

    Returns:
        Dict with user statistics
    """
    from apps.storage.factory.memory import get_memory_service

    memory = get_memory_service()
    user_conversations = memory.get_user_conversations(request)
    conversation_count = user_conversations.count()

    return {
        "conversation_count": conversation_count,
        "files_uploaded": memory.get_user_files(request).count()
        if hasattr(memory, "get_user_files")
        else 0,
    }


# Integration with existing cache system
@memory_api.get("/stats/cache", response=CacheStatsResponse)
def get_cache_stats(request: WSGIRequest):
    """
    Get cache statistics for debugging/monitoring.

    Returns:
        Dict with cache information
    """
    cache_data = dict(loc_cache.data) if hasattr(loc_cache, "data") else {}

    return {
        "cache_size": len(cache_data),
        "cache_keys": list(cache_data.keys())[:10],  # First 10 keys for debugging
        "cache_type": type(loc_cache).__name__,
    }


# --- Health endpoint ---


@memory_api.get("/health", response=HealthResponse)
def health_check_endpoint(request: WSGIRequest):
    """
    Health check endpoint for monitoring services status.

    Returns:
        HealthResponse: Service health information
    """
    from apps.storage.factory.memory import memory_health_check

    return memory_health_check()


# Import view modules to register their endpoints with the API instances
from apps.storage.views import (
    addons,  # noqa: E402, F401
    conversations,  # noqa: E402, F401
    files,  # noqa: E402, F401
    skills,  # noqa: E402, F401
    user_skills,  # noqa: E402, F401
)
