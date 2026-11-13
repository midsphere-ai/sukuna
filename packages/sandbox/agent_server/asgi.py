"""ASGI entrypoint for the sandbox agent server.

Wraps the Django ASGI application with a lifespan handler that initializes
the memory store and MCP connections on startup, and cleans them up on shutdown.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "agent_server.settings")

import django  # noqa: E402

django.setup()

from django.core.asgi import get_asgi_application  # noqa: E402

_django_app = get_asgi_application()

# Track whether init_server has been called (idempotent guard).
_server_initialized = False


async def application(scope, receive, send):
    """ASGI application with lifespan support for init_server/shutdown_server."""
    global _server_initialized  # noqa: PLW0603

    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    from agent_server.server import init_server

                    if not _server_initialized:
                        await init_server()
                        _server_initialized = True
                    await send({"type": "lifespan.startup.complete"})
                except Exception as exc:
                    await send({"type": "lifespan.startup.failed", "message": str(exc)})
                    return
            elif message["type"] == "lifespan.shutdown":
                try:
                    from agent_server.server import shutdown_server

                    await shutdown_server()
                except Exception:
                    pass
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        await _django_app(scope, receive, send)
