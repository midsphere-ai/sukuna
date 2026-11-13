"""Abstract base service providing common infrastructure for domain services.

``BaseService`` centralises authentication, caching, validation, error
handling, transaction management, and health-check logic so that
concrete service subclasses can focus on domain-specific behaviour.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from functools import cached_property
from typing import Any, Dict, Optional, Type, Union

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.handlers.wsgi import WSGIRequest
from django.db import transaction

from apps.billing.models import UserSubscription
from apps.users.models import User
from config.cache.default import DjangoCacheService
from config.errors.common import InvalidInputError, UnauthorizedAccessError
from config.protocols.base import CacheService, UserProfileService
from config.protocols.user import WorkspaceUserService


class BaseService(ABC):
    """
    Base services class providing common infrastructure for all domain services.

    Features:
    - User authentication and authorization
    - Caching integration
    - Structured error handling
    - UUID validation
    - Logging
    - Configuration management
    - Transaction management
    """

    # Service identification - to be overridden by subclasses
    SERVICE_NAME: str = "base"
    SERVICE_VERSION: str = "1.0.0"

    # Default cache timeout - can be overridden by subclasses
    DEFAULT_CACHE_TIMEOUT: int = 3600  # 1 hour

    def __init__(
        self,
        user_service: Optional[UserProfileService] = None,
        cache_service: Optional[CacheService] = None,
        logger: Optional[logging.Logger] = None,
        **kwargs,
    ):
        """
        Initialize base services with common dependencies.

        Args:
            user_service: Service for user profile operations
            cache_service: Service for caching operations
            logger: Logger instance
            **kwargs: Additional services-specific parameters
        """
        self._user_service = user_service or WorkspaceUserService()
        self._cache_service = cache_service or DjangoCacheService()
        self._logger = logger or logging.getLogger(
            f"{__name__}.{self.__class__.__name__}"
        )
        self._service_kwargs = kwargs

        # Log services initialization
        self._logger.info(
            f"Initialized {self.__class__.__name__} v{self.SERVICE_VERSION}"
        )

    @cached_property
    @abstractmethod
    def config(self) -> Dict[str, Any]:
        """
        Service-specific configuration. Must be implemented by subclasses.

        Should include at least:
        - version: Service version
        - Any services-specific settings

        Returns:
            Dict[str, Any]: Configuration dictionary
        """
        pass

    @property
    def service_info(self) -> Dict[str, Any]:
        """
        Get services information including name, version, and status.

        Returns:
            Dict[str, Any]: Service information
        """
        return {
            "name": self.SERVICE_NAME,
            "version": self.SERVICE_VERSION,
            "config": self.config,
            "initialized_at": getattr(self, "_initialized_at", None),
        }

    def _get_user_subscription(self, user: User) -> UserSubscription:
        with self._handle_service_errors():
            return UserSubscription.objects.select_related("plan").get(user=user)

    async def _aget_user_subscription(self, user: User) -> UserSubscription:
        with self._handle_service_errors():
            return await UserSubscription.objects.select_related("plan").aget(user=user)

    # Cache Management

    def _get_cache_key(
        self, prefix: str, identifier: str, namespace: Optional[str] = None
    ) -> str:
        """
        Generate standardized cache key.

        Args:
            prefix: Cache key prefix (e.g., 'user', 'conversation')
            identifier: Unique identifier for the cached item
            namespace: Optional namespace for multi-tenancy

        Returns:
            str: Formatted cache key
        """
        base_key = f"{self.SERVICE_NAME}:{prefix}:{identifier}"
        if namespace:
            base_key = f"{namespace}:{base_key}"
        return base_key

    def _cache_get(self, key: str, default: Any = None) -> Any:
        """
        Get item from cache with error handling.

        Args:
            key: Cache key
            default: Default value if not found or error occurs

        Returns:
            Any: Cached value or default
        """
        try:
            return self._cache_service.get(key, default)
        except Exception as e:
            self._logger.warning(f"Cache get failed for key '{key}': {e}")
            return default

    def _cache_set(self, key: str, value: Any, timeout: Optional[int] = None) -> bool:
        """
        Set item in cache with error handling.

        Args:
            key: Cache key
            value: Value to cache
            timeout: Cache timeout in seconds

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            timeout = timeout or self.config.get(
                "cache_timeout", self.DEFAULT_CACHE_TIMEOUT
            )
            self._cache_service.set(key, value, timeout)
            return True
        except Exception as e:
            self._logger.warning(f"Cache set failed for key '{key}': {e}")
            return False

    def _cache_delete(self, key: str) -> bool:
        """
        Delete item from cache with error handling.

        Args:
            key: Cache key to delete

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            self._cache_service.delete(key)
            return True
        except Exception as e:
            self._logger.warning(f"Cache delete failed for key '{key}': {e}")
            return False

    def _cache_clear_pattern(self, pattern: str) -> bool:
        """
        Clear cache entries matching a pattern (if supported by cache backend).

        Args:
            pattern: Pattern to match (implementation dependent)

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if hasattr(self._cache_service, "delete_pattern"):
                self._cache_service.delete_pattern(pattern)
                return True
            else:
                self._logger.warning("Cache backend doesn't support pattern deletion")
                return False
        except Exception as e:
            self._logger.warning(
                f"Cache pattern delete failed for pattern '{pattern}': {e}"
            )
            return False

    # User Authentication & Authorization

    def _get_authenticated_user(self, request: WSGIRequest) -> User:
        """
        Get authenticated user from request with caching and error handling.

        Args:
            request: The HTTP request object

        Returns:
            User: The authenticated user

        Raises:
            UnauthorizedAccessError: If user is not authenticated
        """
        profile = self._user_service.get_profile_from_request(request)
        return self._validate_user(profile)

    def _validate_user(self, profile: User) -> User:
        try:
            if not profile or not isinstance(profile, User):
                self._logger.warning("Authentication failed: No valid profile found")
                raise UnauthorizedAccessError("Authentication required")
            return profile
        except UnauthorizedAccessError:
            # Re-raise our own exceptions without wrapping them
            raise
        except Exception as e:
            self._logger.warning(f"Authentication failed: {e}")
            raise UnauthorizedAccessError("Invalid authentication") from e

    def _check_user_permission(
        self, user: User, resource_owner_id: Union[int, str], permission: str = "access"
    ) -> None:
        """
        Check if user has permission to access a resource.

        Args:
            user: User requesting access
            resource_owner_id: ID of the resource owner
            permission: Type of permission to check

        Raises:
            UnauthorizedAccessError: If user doesn't have permission
        """
        if str(user.id) != str(resource_owner_id):
            self._logger.warning(
                f"User {user.id} denied {permission} to resource owned by {resource_owner_id}"
            )
            raise UnauthorizedAccessError(
                f"Access denied: insufficient {permission} permissions"
            )

    # Validation Utilities
    def _validate_object(self, value: Any, type: Type):
        if not isinstance(value, type):
            raise InvalidInputError(f"Object {value} is not of type {type}")

    def _validate_uuid(self, value: str, field_name: str = "ID") -> uuid.UUID:
        """
        Validate and convert string to UUID.

        Args:
            value: String to validate
            field_name: Name of the field for error messages

        Returns:
            uuid.UUID: Validated UUID

        Raises:
            InvalidInputError: If validation fails
        """
        if not value or not isinstance(value, str):
            raise InvalidInputError(f"{field_name} is required and must be a string")

        try:
            return uuid.UUID(value)
        except ValueError as e:
            raise InvalidInputError(f"Invalid {field_name} format") from e

    def _validate_required_field(
        self, value: Any, field_name: str, expected_type: Optional[Type] = None
    ) -> None:
        # Check if required
        if value is None or (isinstance(value, str) and not value.strip()):
            raise InvalidInputError(f"{field_name} is required")

        # Check type if specified
        if expected_type is not None and not isinstance(value, expected_type):
            raise InvalidInputError(
                f"{field_name} must be of type {expected_type.__name__}, got {type(value).__name__}"
            )

    def _validate_pagination_params(
        self, limit: Optional[int] = None, offset: Optional[int] = None
    ) -> Dict[str, int]:
        """
        Validate pagination parameters.

        Args:
            limit: Number of items to return
            offset: Number of items to skip

        Returns:
            Dict[str, int]: Validated pagination parameters

        Raises:
            InvalidInputError: If parameters are invalid
        """
        default_limit = self.config.get("default_page_size", 20)
        max_limit = self.config.get("max_page_size", 100)

        if limit is None:
            limit = default_limit
        elif not isinstance(limit, int) or limit <= 0:
            raise InvalidInputError("Limit must be a positive integer")
        elif limit > max_limit:
            raise InvalidInputError(f"Limit cannot exceed {max_limit}")

        if offset is None:
            offset = 0
        elif not isinstance(offset, int) or offset < 0:
            raise InvalidInputError("Offset must be a non-negative integer")

        return {"limit": limit, "offset": offset}

    # Error Handling

    def _map_and_log_error(self, e: Exception, context: str) -> Exception:
        """
        Map raw exceptions to domain-specific errors and log consistently.
        Can be overridden by subclasses to handle services-specific exceptions.
        """
        if isinstance(e, (UnauthorizedAccessError, InvalidInputError)):
            self._logger.info(f"{context} failed with domain error: {e}")
            return e

        if isinstance(e, ValidationError):
            self._logger.warning(f"{context} validation error: {e}")
            return InvalidInputError(str(e))

        self._logger.error(
            f"Unexpected error in {context} for {self.__class__.__name__}: {e}",
            exc_info=True,
        )
        return Exception(f"An unexpected error occurred during {context}")

    @contextmanager
    def _handle_service_errors(self, operation_name: str = "operation"):
        """
        Context manager for consistent error handling and logging.

        Args:
            operation_name: Name of the operation for logging
        """
        try:
            yield
        except Exception as e:
            raise self._map_and_log_error(e, operation_name)

    # Transaction Management

    @contextmanager
    def _atomic_operation(self, operation_name: str = "operation"):
        """
        Context manager for atomic database operations with error handling.

        Args:
            operation_name: Name of the operation for logging
        """
        with self._handle_service_errors(operation_name):
            with transaction.atomic():
                self._logger.debug(f"Starting atomic {operation_name}")
                try:
                    yield
                    self._logger.debug(f"Completed atomic {operation_name}")
                except Exception:
                    self._logger.debug(f"Rolling back atomic {operation_name}")
                    raise

    # Health Check and Monitoring

    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check of the services and its dependencies.

        Returns:
            Dict[str, Any]: Health status information
        """
        status = {
            "services": self.SERVICE_NAME,
            "version": self.SERVICE_VERSION,
            "status": "healthy",
            "checks": {},
        }

        # Check cache services
        try:
            test_key = self._get_cache_key("health_check", "test")
            self._cache_set(test_key, "test_value", 10)
            cached_value = self._cache_service.get(test_key)
            self._cache_delete(test_key)

            status["checks"]["cache"] = {
                "status": "healthy" if cached_value == "test_value" else "degraded",
                "message": "Cache services operational",
            }
        except Exception as e:
            status["checks"]["cache"] = {
                "status": "unhealthy",
                "message": f"Cache services error: {e}",
            }
            status["status"] = "degraded"

        # Check user services
        try:
            # Basic check - just verify the services exists and is callable
            if hasattr(self._user_service, "get_profile_from_request"):
                status["checks"]["user_service"] = {
                    "status": "healthy",
                    "message": "User services operational",
                }
            else:
                status["checks"]["user_service"] = {
                    "status": "unhealthy",
                    "message": "User services missing required methods",
                }
                status["status"] = "degraded"
        except Exception as e:
            status["checks"]["user_service"] = {
                "status": "unhealthy",
                "message": f"User services error: {e}",
            }
            status["status"] = "degraded"

        return status

    # Utility Methods for Subclasses

    def _log_operation(
        self,
        operation: str,
        user_id: Optional[Union[int, str]] = None,
        resource_id: Optional[str] = None,
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Log services operations with consistent format.

        Args:
            operation: Operation being performed
            user_id: ID of user performing operation
            resource_id: ID of resource being operated on
            extra_context: Additional context for logging
        """
        log_data = {
            "services": self.SERVICE_NAME,
            "operation": operation,
        }

        if user_id is not None:
            log_data["user_id"] = str(user_id)
        if resource_id is not None:
            log_data["resource_id"] = resource_id
        if extra_context:
            log_data.update(extra_context)

        self._logger.info("Service operation", extra=log_data)

    def _get_config_value(
        self, key: str, default: Any = None, required: bool = False
    ) -> Any:
        """
        Get configuration value with fallback to Django settings.

        Args:
            key: Configuration key
            default: Default value if not found
            required: Whether the value is required

        Returns:
            Any: Configuration value

        Raises:
            InvalidInputError: If required value is missing
        """
        # First check services config
        if hasattr(self, "config") and key in self.config:
            return self.config[key]

        # Then check Django settings with services prefix
        setting_key = f"{self.SERVICE_NAME.upper()}_{key.upper()}"
        value = getattr(settings, setting_key, default)

        if required and value is None:
            raise InvalidInputError(f"Required configuration '{key}' is missing")

        return value
