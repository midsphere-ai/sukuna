"""Default Django cache service implementation.

Wraps Django's built-in cache framework behind a simple service interface
used by ``BaseService`` and the service factory.
"""

from typing import Any, Optional

from django.core.cache import cache


# Default implementations
class DjangoCacheService:
    """Default Django cache services implementation."""

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value from the cache.

        Args:
            key: The cache key to look up.

        Returns:
            The cached value, or ``None`` if the key does not exist.
        """
        return cache.get(key)

    def set(self, key: str, value: Any, timeout: Optional[int] = None) -> None:
        """Store a value in the cache.

        Args:
            key: The cache key.
            value: The value to store.
            timeout: Expiration time in seconds. ``None`` uses the default timeout.
        """
        cache.set(key, value, timeout)

    def delete(self, key: str) -> None:
        """Remove a key from the cache.

        Args:
            key: The cache key to delete.
        """
        cache.delete(key)

    def incr(self, key: str, delta: int = 1) -> int:
        """Increment a cache value by *delta*.

        Args:
            key: The cache key whose value should be incremented.
            delta: Amount to increment by (default ``1``).

        Returns:
            The new integer value after incrementing.
        """
        return cache.incr(key, delta)
