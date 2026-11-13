"""Server lifecycle: initialization and shutdown.

init_server() replaces the old FastAPI lifespan context manager.
It initializes the tool registry, memory store, and skills.
Called once at Django startup (e.g., from AppConfig.ready() or ASGI).

_cli() provides a standalone CLI entry point for development.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path as FilePath

from asgiref.sync import sync_to_async

from agent_server.config import (
    AGENT_MEMORY_DB_POOL_MAX_INACTIVE_SECONDS,
    AGENT_MEMORY_DB_POOL_MAX_QUERIES,
    AGENT_MEMORY_DB_POOL_MAX_SIZE,
    AGENT_MEMORY_DB_POOL_MIN_SIZE,
    AGENT_MODEL,
    EXTERNAL_MCP_CONFIGS,
    PORT,
    SANDBOX_WORKSPACE_ROOT,
    _inject_tool_env_vars,
)
from agent_server.infra import (
    _run_tasks,
    populate_registry,
    populate_skill_registry,
)
from agent_server.infra.memory_store import BoundedPostgresMemoryStore

log = logging.getLogger("agent_server")


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 12 — SERVER INITIALIZATION & STARTUP                             ║
# ║                                                                            ║
# ║  init_server() replaces the old FastAPI lifespan context manager.          ║
# ║  It initializes the tool registry, memory store, and skills.               ║
# ║  Called once at Django startup (e.g., from AppConfig.ready() or ASGI).     ║
# ║                                                                            ║
# ║  _cli() provides a standalone CLI entry point for development.             ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


async def init_server() -> None:
    """Initialize server-level resources.

    This must be called once during Django startup (e.g. from an AppConfig.ready()
    hook or the ASGI application entry point).  It:

    1. Injects tool environment variables (replaces old MCP subprocess env configs).
    2. Populates the native tool registry (16 action-based tools).
    3. Reads the DATABASE_URL for the PostgresMemoryStore.
    4. Initializes the memory store.
    """
    import agent_server.infra as _core

    # Ensure sandbox-owned schema is up to date regardless of entrypoint.
    # ``python -m agent_server`` already runs this in __main__, but direct
    # ASGI startup (uvicorn agent_server.asgi:application) does not.
    try:
        from django.core.management import call_command  # noqa: PLC0415

        await sync_to_async(call_command)("migrate", "agent_server", "--fake-initial", verbosity=0)
        log.info("Agent server migrations are up to date")
    except Exception as exc:
        log.warning("Agent server migration check failed (non-fatal): %s", exc)

    # Inject env vars that in-process tool modules expect (replaces MCP env config).
    _inject_tool_env_vars()

    # Create context directory for navigator mode persistence (vital context,
    # summaries).  This survives sandbox pause/resume cycles.
    _context_dir = FilePath(f"{SANDBOX_WORKSPACE_ROOT}/.agent/context")
    _context_dir.mkdir(parents=True, exist_ok=True)
    log.info("Context directory ready: %s", _context_dir)

    _plans_dir = FilePath(f"{SANDBOX_WORKSPACE_ROOT}/.agent/plans")
    _plans_dir.mkdir(parents=True, exist_ok=True)
    log.info("Plans directory ready: %s", _plans_dir)

    # Populate the native tool registry — 16 action-based tools loaded in-process.
    tool_count = populate_registry()
    log.info("Native tool registry ready: %d tools", tool_count)

    skill_count = populate_skill_registry()
    log.info("Skill registry ready: %d skills", skill_count)

    # Read DB URL fresh — config constants are captured at import time but vault
    # may use MIDSPHERE_DB_URL instead of DATABASE_URL.
    _dsn = os.environ.get("DATABASE_URL") or os.environ.get("MIDSPHERE_DB_URL", "")
    if not _dsn:
        log.error("No database URL found. Set DATABASE_URL or MIDSPHERE_DB_URL in vault.")
        return

    _core._memory_store = BoundedPostgresMemoryStore(
        _dsn,
        min_size=AGENT_MEMORY_DB_POOL_MIN_SIZE,
        max_size=AGENT_MEMORY_DB_POOL_MAX_SIZE,
        max_queries=AGENT_MEMORY_DB_POOL_MAX_QUERIES,
        max_inactive_connection_lifetime=AGENT_MEMORY_DB_POOL_MAX_INACTIVE_SECONDS,
    )
    await _core._memory_store.init()
    log.info("Memory store ready (model default: %s)", AGENT_MODEL)

    if EXTERNAL_MCP_CONFIGS:
        log.info(
            "Vault MCP servers configured (%d): %s — will be passed to each run on demand",
            len(EXTERNAL_MCP_CONFIGS),
            [c.name for c in EXTERNAL_MCP_CONFIGS],
        )

    from agent_server.infra.registry import skill_registry  # noqa: C0415
    from agent_server.versioning import build_manifest, log_manifest  # noqa: C0415

    _startup_manifest = build_manifest(skill_registry=skill_registry)
    log_manifest(_startup_manifest, prefix="Server startup")


async def shutdown_server() -> None:
    """Graceful shutdown: cancel active runs, close memory store.

    Called during Django shutdown (e.g. ASGI lifespan shutdown event).
    """
    import agent_server.infra as _core

    # Cancel active runs.
    if _run_tasks:
        log.info("Shutdown: cancelling %d active run(s)", len(_run_tasks))
        for task in list(_run_tasks.values()):
            task.cancel()
        await asyncio.gather(*list(_run_tasks.values()), return_exceptions=True)

    # Close memory store.
    if _core._memory_store is not None:
        with contextlib.suppress(Exception):
            await _core._memory_store.close()
        _core._memory_store = None


def _cli() -> None:
    """Standalone CLI entry point for development.

    Starts Django's ASGI server (via uvicorn/daphne) with the sandbox
    Django project settings.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Exo Agent Server (Django Ninja)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=PORT, help="Port (overrides PORT vault secret)")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes (dev)")
    parser.add_argument("--workers", type=int, default=1, help="Uvicorn worker count")
    parser.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])

    args = parser.parse_args()

    if args.workers > 1:
        print(
            f"WARNING: --workers {args.workers} is not supported — the agent server uses "
            "in-process shared state (_run_tasks, _run_channels, _hitl_pending) that cannot "
            "be shared across worker processes. Forcing --workers 1.",
            file=sys.stderr,
        )
        args.workers = 1

    import uvicorn

    # Point at the Django ASGI application.
    uvicorn.run(
        "agent_server.asgi:application",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers if not args.reload else 1,  # reload requires single worker
        log_level=args.log_level,
    )


if __name__ == "__main__":
    _cli()
