"""Factory, error handlers, and dependency injection for the MemoryService."""

# Factory for creating services instances
import logging
from typing import Any, Dict, Optional

from django.utils import timezone
from ninja.errors import HttpError

from apps.storage.memory import (
    ConversationNotFoundError,
    MemoryServiceError,
)
from apps.storage.services.memory import (
    MemoryService,
)
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    UnauthorizedAccessError,
)
from config.factory.base import ClassMethodBaseFactory
from config.protocols.base import CacheService, UserProfileService


class MemoryServiceFactory(ClassMethodBaseFactory):
    """Factory for creating properly configured MemoryService instances."""

    _service_class = MemoryService  # Set the services class

    @classmethod
    def create(
        cls,
        user_service: Optional["UserProfileService"] = None,
        cache_service: Optional["CacheService"] = None,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ) -> "MemoryService":
        """Create a new MemoryService instance."""
        return super().create(
            user_service=user_service,
            cache_service=cache_service,
            logger=logger,
            **kwargs,
        )


# Error handlers for Django Ninja integration
def memory_service_error_handler(request, exc: MemoryServiceError):
    """Convert services errors to appropriate HTTP responses."""
    error_map = {
        # 400-series client errors
        InvalidInputError: 400,  # Bad Request
        UnauthorizedAccessError: 401,  # Unauthorized
        FileProcessingError: 422,  # Unprocessable Entity
        # 404 Not Found
        ConversationNotFoundError: 404,
        # 500 Internal Server Error
        MemoryServiceError: 500,
    }

    status_code = error_map.get(type(exc), 500)
    return HttpError(status_code, str(exc))


# Dependency injection function
def get_memory_service() -> MemoryService:
    """Dependency injection function for Django Ninja."""
    return MemoryServiceFactory.get_singleton()


# Health check method
def memory_health_check() -> Dict[str, Any]:
    """Health check for the storage services."""
    try:
        service = MemoryServiceFactory.get_singleton()
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
