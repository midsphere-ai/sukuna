"""Service factory base classes and singleton accessors.

Provides ``get_cache_service`` / ``get_user_service`` module-level helpers
and a generic ``ClassMethodBaseFactory`` that subclasses can use to manage
thread-safe singleton service instances.
"""

import threading
from typing import Any, Dict, Generic, Type, TypeVar

from config.cache.default import DjangoCacheService
from config.protocols.user import WorkspaceUserService

T = TypeVar("T")

_cache_service_instance = None
_user_service_instance = None


def get_cache_service():
    """Return the singleton ``DjangoCacheService`` instance, creating it on first call.

    Returns:
        DjangoCacheService: The shared cache service instance.
    """
    global _cache_service_instance
    if _cache_service_instance is None:
        _cache_service_instance = DjangoCacheService()
    return _cache_service_instance


def get_user_service():
    """Return the singleton ``WorkspaceUserService`` instance, creating it on first call.

    Returns:
        WorkspaceUserService: The shared user service instance.
    """
    global _user_service_instance
    if _user_service_instance is None:
        _user_service_instance = WorkspaceUserService()
    return _user_service_instance


class ClassMethodBaseFactory(Generic[T]):
    """Base factory using class methods (similar to your original pattern)."""

    _instances: Dict[str, Any] = {}
    _service_class: Type[T] = None
    _lock = threading.Lock()

    @classmethod
    def create(cls, **kwargs) -> T:
        """Create a new services instance."""
        if cls._service_class is None:
            raise NotImplementedError("Subclass must set _service_class")
        return cls._service_class(**kwargs)

    @classmethod
    def get_singleton(cls, **kwargs) -> T:
        """Get singleton instance for dependency injection."""
        class_name = cls.__name__
        if class_name not in cls._instances:
            with cls._lock:
                if class_name not in cls._instances:
                    cls._instances[class_name] = cls.create(**kwargs)
        return cls._instances[class_name]

    @classmethod
    def reset_singleton(cls) -> None:
        """Reset singleton (useful for testing)."""
        class_name = cls.__name__
        if class_name in cls._instances:
            del cls._instances[class_name]

    @classmethod
    def reset_all_singletons(cls) -> None:
        """Reset all singleton instances (useful for testing)."""
        cls._instances.clear()
