"""Protocol definitions for core service contracts.

Defines ``UserProfileService`` and ``CacheService`` protocols that
decouple infrastructure implementations from domain services.
"""

from typing import Any, Optional, Protocol, runtime_checkable

from django.core.handlers.wsgi import WSGIRequest

from apps.users.models import User


@runtime_checkable
class UserProfileService(Protocol):
    """Protocol for user profile operations."""

    def get_profile_from_request(self, request: WSGIRequest) -> Optional[User]:
        """Get user profile from request."""
        ...

    def get_logged_in_user(self, token: str) -> Optional[User]:
        """Get user from token."""
        ...


@runtime_checkable
class CacheService(Protocol):
    """Protocol for caching operations."""

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        ...

    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> None:
        """Set value in cache."""
        ...

    def delete(self, key: str) -> None:
        """Delete value from cache."""
        ...
