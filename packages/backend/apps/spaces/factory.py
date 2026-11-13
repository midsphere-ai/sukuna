"""Factory, error handlers, and dependency injection for the projects service."""

import logging
from typing import Any, Dict, Optional

from django.utils import timezone
from ninja.errors import HttpError

from apps.spaces.errors import (
    CreateProjectFailedError,
    ProjectFileNotFoundError,
    ProjectFileUploadError,
    ProjectObjectNotFoundError,
    ProjectsServiceError,
    UpdateProjectFailedError,
)
from apps.spaces.service import ProjectsService
from config.errors.common import (
    FileProcessingError,
    InvalidInputError,
    UnauthorizedAccessError,
)
from config.factory.base import ClassMethodBaseFactory
from config.protocols.base import CacheService, UserProfileService


class ProjectsServiceFactory(ClassMethodBaseFactory):
    """Factory for creating properly configured ProjectsService instances."""

    _service_class = ProjectsService  # Set the services class

    @classmethod
    def create(
        cls,
        user_service: Optional["UserProfileService"] = None,
        cache_service: Optional["CacheService"] = None,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ) -> "ProjectsService":
        """Create a new ProjectsService instance.

        Args:
            user_service: Optional user profile service for authentication.
            cache_service: Optional cache service for response caching.
            logger: Optional logger instance.
            **kwargs: Additional keyword arguments passed to the service.

        Returns:
            A configured ProjectsService instance.
        """
        return super().create(
            user_service=user_service,
            cache_service=cache_service,
            logger=logger,
            **kwargs,
        )


# Error handlers for Django Ninja integration
def projects_service_error_handler(request, exc: ProjectsServiceError):
    """Convert service errors to appropriate HTTP responses.

    Args:
        request: The incoming HTTP request.
        exc: The ProjectsServiceError that was raised.

    Returns:
        An HttpError with the mapped status code and error message.
    """
    error_map = {
        # 400-series client errors
        InvalidInputError: 400,  # Bad Request
        UnauthorizedAccessError: 401,  # Unauthorized
        FileProcessingError: 422,  # Unprocessable Entity
        ProjectFileUploadError: 422,  # Unprocessable Entity
        # 404 Not Found
        ProjectsServiceError: 404,
        CreateProjectFailedError: 404,
        UpdateProjectFailedError: 404,
        ProjectObjectNotFoundError: 404,
        ProjectFileNotFoundError: 404,
    }

    status_code = error_map.get(type(exc), 500)
    return HttpError(status_code, str(exc))


# Dependency injection function
def get_projects_service() -> ProjectsService:
    """Dependency injection function for Django Ninja.

    Returns:
        The singleton ProjectsService instance.
    """
    return ProjectsServiceFactory.get_singleton()


# Health check method
def projects_health_check() -> Dict[str, Any]:
    """Health check for the projects service.

    Returns:
        A dict with status, version, cache state, and timestamp.
    """
    try:
        service = ProjectsServiceFactory.get_singleton()
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
