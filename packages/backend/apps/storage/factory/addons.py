"""Factory, error handlers, and dependency injection for the AddonsService."""

import logging
from typing import Any, Dict, Optional

from django.utils import timezone
from ninja.errors import HttpError

from apps.storage.errors import (
    AddonAlreadyRegistered,
    AddonError,
    AddonNotAuthorised,
    AlreadyAuthorised,
    AuthLinkAlreadyExists,
    NonExistentAddon,
    NoToolsFound,
    RegisterFailed,
    UnRegisterFailed,
)
from apps.storage.services.addons import AddonsService
from config.factory.base import ClassMethodBaseFactory
from config.protocols.base import CacheService, UserProfileService


class AddonsServiceFactory(ClassMethodBaseFactory):
    """Factory for creating properly configured AddonsService instances."""

    _service_class = AddonsService  # Set the services class

    @classmethod
    def create(
        cls,
        user_service: Optional["UserProfileService"] = None,
        cache_service: Optional["CacheService"] = None,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ) -> "AddonsService":
        """Create a new AddonsService instance."""
        return super().create(
            user_service=user_service,
            cache_service=cache_service,
            logger=logger,
            **kwargs,
        )


# Error handlers for Django Ninja integration
def addon_service_error_handler(request, exc: AddonError):
    """Convert services errors to appropriate HTTP responses."""
    error_map = {
        # 404 Not Found
        NoToolsFound: 404,
        NonExistentAddon: 404,
        # 409 Conflict
        AddonAlreadyRegistered: 409,
        AuthLinkAlreadyExists: 409,
        AlreadyAuthorised: 409,
        # 401 Unauthorized / 403 Forbidden
        AddonNotAuthorised: 401,  # could be 403 if the addon exists but access is forbidden
        # 500 Internal Server Error
        RegisterFailed: 500,
        UnRegisterFailed: 500,
        AddonError: 500,
    }

    status_code = error_map.get(type(exc), 500)
    return HttpError(status_code, str(exc))


# Dependency injection function
def get_addon_service() -> AddonsService:
    """Dependency injection function for Django Ninja."""
    return AddonsServiceFactory.get_singleton()


# Health check method
def addon_health_check() -> Dict[str, Any]:
    """Health check for the addon services."""
    try:
        service = AddonsServiceFactory.get_singleton()
        return {
            "status": "healthy",
            "version": service.config["version"],
            "cache_enabled": service._cache_service is not None,
            "timestamp": timezone.now().isoformat(),
        }
    except Exception as e:
        return {
            "status": "degraded",
            "error": str(e),
            "timestamp": timezone.now().isoformat(),
        }
