"""Memory-store helpers for sandbox runtime."""

from __future__ import annotations

import logging

import asyncpg
from exo.memory.backends.postgres import PostgresMemoryStore

log = logging.getLogger("agent_server")

# Keep schema bootstrap in sync with exo's PostgresMemoryStore.
_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS memory_items (
    id          TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'accepted',
    metadata    JSONB NOT NULL DEFAULT '{}',
    extra_json  JSONB NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted     SMALLINT NOT NULL DEFAULT 0,
    version     INTEGER NOT NULL DEFAULT 1
)"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_items(memory_type) WHERE deleted = 0",
    "CREATE INDEX IF NOT EXISTS idx_status ON memory_items(status) WHERE deleted = 0",
    "CREATE INDEX IF NOT EXISTS idx_created_at ON memory_items(created_at) WHERE deleted = 0",
    "CREATE INDEX IF NOT EXISTS idx_metadata_user ON memory_items((metadata->>'user_id')) WHERE deleted = 0",
    "CREATE INDEX IF NOT EXISTS idx_metadata_session ON memory_items((metadata->>'session_id')) WHERE deleted = 0",
]


class BoundedPostgresMemoryStore(PostgresMemoryStore):
    """Postgres memory store with explicit asyncpg pool bounds.

    Why this exists:
    asyncpg defaults to ``min_size=10`` and ``max_size=10``. In a many-sandbox
    deployment, that eagerly reserves a large number of DB connections.
    """

    __slots__ = (
        "_pool_max_inactive_connection_lifetime",
        "_pool_max_queries",
        "_pool_max_size",
        "_pool_min_size",
    )

    def __init__(
        self,
        dsn: str,
        *,
        min_size: int = 1,
        max_size: int = 2,
        max_queries: int = 50_000,
        max_inactive_connection_lifetime: float = 60.0,
    ) -> None:
        super().__init__(dsn)
        min_size = max(min_size, 1)
        max_size = max(max_size, min_size)
        self._pool_min_size = min_size
        self._pool_max_size = max_size
        self._pool_max_queries = max(max_queries, 1)
        self._pool_max_inactive_connection_lifetime = max(
            max_inactive_connection_lifetime,
            0.0,
        )

    async def init(self) -> None:
        """Open a bounded asyncpg pool and bootstrap schema."""
        if self._pool is not None:
            return

        log.info(
            "Initializing memory DB pool (min=%s, max=%s, inactive_lifetime=%ss)",
            self._pool_min_size,
            self._pool_max_size,
            self._pool_max_inactive_connection_lifetime,
        )
        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=self._pool_min_size,
            max_size=self._pool_max_size,
            max_queries=self._pool_max_queries,
            max_inactive_connection_lifetime=self._pool_max_inactive_connection_lifetime,
        )
        pool = self._pool
        assert pool is not None
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
            for idx_sql in _CREATE_INDEXES:
                await conn.execute(idx_sql)
        self._initialized = True
