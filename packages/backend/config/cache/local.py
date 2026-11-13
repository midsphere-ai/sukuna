"""Thread-safe in-memory cache backend.

A persistent, process-local cache that survives Django's per-request
teardown. Data is stored in module-level dictionaries keyed by cache
name, with thread-safe locking around all mutations.
"""

import time
from collections import OrderedDict
from contextlib import contextmanager
from threading import Lock

from django.core.cache.backends.base import DEFAULT_TIMEOUT, BaseCache

# Global in-storage store of cache data. Keyed by name, to provide
# multiple named local storage caches.
_caches = {}
_expire_info = {}
_locks = {}


@contextmanager
def dummy():
    """A context manager that does nothing special."""
    yield


class PersistentMem(BaseCache):
    """Process-local LRU cache that persists across Django requests.

    Unlike Django's built-in ``LocMemCache``, cached data is kept in
    module-level globals so it is not cleared between requests.
    """

    def __init__(self, name, params):
        BaseCache.__init__(self, params)
        self._cache = _caches.setdefault(name, OrderedDict())
        self._expire_info = _expire_info.setdefault(name, {})
        self._lock = _locks.setdefault(name, Lock())

    def add(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        """Store a value only if the key does not already exist (or has expired).

        Args:
            key: The cache key.
            value: The value to store.
            timeout: Expiration timeout in seconds.
            version: Optional cache key version.

        Returns:
            ``True`` if the value was stored, ``False`` if the key already exists.
        """
        key = self.make_key(key, version=version)
        self.validate_key(key)
        with self._lock:
            if self._has_expired(key):
                self._set(key, value, timeout)
                return True
            return False

    def get(self, key, default=None, version=None, acquire_lock=True):
        """Retrieve a value from the cache.

        Args:
            key: The cache key to look up.
            default: Value to return if the key is missing or expired.
            version: Optional cache key version.
            acquire_lock: Whether to acquire the thread lock (set ``False``
                when the caller already holds it).

        Returns:
            The cached value, or *default* if not found.
        """
        key = self.make_key(key, version=version)
        self.validate_key(key)
        with self._lock if acquire_lock else dummy():
            if not self._has_expired(key):
                return self._cache[key]
            try:
                del self._cache[key]
                del self._expire_info[key]
            except KeyError:
                pass
            return default

    def _set(self, key, value, timeout=DEFAULT_TIMEOUT):
        if len(self._cache) >= self._max_entries:
            self._cull()
        self._cache[key] = value
        self._expire_info[key] = self.get_backend_timeout(timeout)

    def set(self, key, value, timeout=DEFAULT_TIMEOUT, version=None):
        """Store a value in the cache, overwriting any existing entry.

        Args:
            key: The cache key.
            value: The value to store.
            timeout: Expiration timeout in seconds.
            version: Optional cache key version.
        """
        key = self.make_key(key, version=version)
        self.validate_key(key)
        with self._lock:
            self._set(key, value, timeout)

    def incr(self, key, delta=1, version=None):
        """Increment a cached integer value.

        Args:
            key: The cache key.
            delta: Amount to increment by (default ``1``).
            version: Optional cache key version.

        Returns:
            The new value after incrementing.

        Raises:
            ValueError: If the key does not exist in the cache.
        """
        with self._lock:
            value = self.get(key, version=version, acquire_lock=False)
            if value is None:
                raise ValueError("Key '%s' not found" % key)
            new_value = value + delta
            key = self.make_key(key, version=version)
            self._cache[key] = new_value
        return new_value

    def has_key(self, key, version=None):
        """Check whether a key exists and has not expired.

        Args:
            key: The cache key.
            version: Optional cache key version.

        Returns:
            ``True`` if the key exists and is not expired, ``False`` otherwise.
        """
        key = self.make_key(key, version=version)
        self.validate_key(key)
        with self._lock:
            if not self._has_expired(key):
                return True
            try:
                del self._cache[key]
                del self._expire_info[key]
            except KeyError:
                pass
            return False

    def _has_expired(self, key):
        exp = self._expire_info.get(key, -1)
        if exp is None or exp > time.time():
            return False
        return True

    def _cull(self):
        if self._cull_frequency == 0:
            self.clear()
        else:
            doomed = [
                k for (i, k) in enumerate(self._cache) if i % self._cull_frequency == 0
            ]
            for k in doomed:
                self._delete(k)

    def _delete(self, key):
        try:
            del self._cache[key]
        except KeyError:
            pass
        try:
            del self._expire_info[key]
        except KeyError:
            pass

    def delete(self, key, version=None):
        """Remove a key from the cache.

        Args:
            key: The cache key to delete.
            version: Optional cache key version.
        """
        key = self.make_key(key, version=version)
        self.validate_key(key)
        with self._lock:
            self._delete(key)

    def clear(self):
        """Remove all entries from this cache instance."""
        with self._lock:
            self._cache.clear()
            self._expire_info.clear()
