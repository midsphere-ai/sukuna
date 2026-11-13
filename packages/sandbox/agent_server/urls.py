"""URL routing for the sandbox agent server.

Mounts all Django Ninja routers defined in server.py onto a single NinjaAPI
instance.  The routers are organized by domain:

  - runs_router:       Run management (POST /runs, GET /runs, DELETE, branch, inject, uploads)
  - streaming_router:  SSE streaming (GET /runs/{id}/stream)
  - hitl_router:       Human-in-the-loop (GET/POST /runs/{id}/hitl/*)
  - mcp_router:        MCP server hot-swap (GET/POST/DELETE /runs/{id}/mcp/*)
  - files_router:      File operations (tree, read, write, create, delete, watch)
  - health_router:     Health + conversations (GET /health, GET /conversations)
  - skills_router:     Skills CRUD (GET/POST/DELETE /skills)

Authentication:
  All routers except ``health_router`` require authentication via either a
  DRF bearer token (shared database) or a static API key (``X-API-Key`` header).
  The ``streaming_router`` additionally accepts ``?api_key=`` query parameters
  for browser EventSource compatibility.  The ``health_router`` is public so
  that load balancers and orchestrators can probe ``/health`` without credentials.
"""

import logging
import os
import traceback
from inspect import unwrap

from django.http import JsonResponse
from django.urls import path
from ninja import NinjaAPI
from ninja.errors import HttpError

from agent_server.server import (
    default_auth,
    files_router,
    health_router,
    hitl_router,
    integrations_router,
    mcp_router,
    runs_router,
    skills_router,
    streaming_router,
)

log = logging.getLogger("agent_server")

api = NinjaAPI(title="Sukuna Agent Server", docs_url="/docs", auth=default_auth)


# ── Error handlers ─────────────────────────────────────────────────────────
#
# Without an explicit exception handler, Django Ninja falls back to Django's
# default 500 page, which the frontend cannot parse.  We log the traceback and
# return a JSON envelope so browser devtools show the real error.


@api.exception_handler(HttpError)
def _ninja_http_error(request, exc: HttpError):
    return JsonResponse(
        {"error": exc.message, "status": exc.status_code},
        status=exc.status_code,
    )


@api.exception_handler(Exception)
def _ninja_unhandled(request, exc: Exception):
    tb = traceback.format_exc()
    log.exception("Unhandled error in %s %s: %s", request.method, request.path, exc)
    body = {
        "error": f"{exc.__class__.__name__}: {exc}",
        "error_code": "UNHANDLED_EXCEPTION",
        "status": 500,
    }
    # Only leak the full traceback when the server is running in dev/debug mode
    # (local .env.local or explicit opt-in).  In production E2B sandboxes the
    # env is not set so the body stays minimal.
    if os.environ.get("SUKUNA_SANDBOX_DEBUG_ERRORS", "").lower() in {"1", "true", "yes"}:
        body["traceback"] = tb
    return JsonResponse(body, status=500)


# Mount all routers — endpoints are defined at the router level with full paths
# (e.g. @runs_router.post("/runs")), so we mount with an empty prefix.
api.add_router("", runs_router)
api.add_router("", streaming_router)
api.add_router("", hitl_router)
api.add_router("", mcp_router)
api.add_router("", files_router)
api.add_router("", health_router)
api.add_router("", skills_router)
api.add_router("", integrations_router)


def _rebuild_ninja_operation_models() -> None:
    """Resolve Ninja-generated operation models that still hold forward refs."""
    for router in (
        runs_router,
        streaming_router,
        hitl_router,
        mcp_router,
        files_router,
        health_router,
        skills_router,
        integrations_router,
    ):
        for path, path_view in getattr(router, "path_operations", {}).items():
            for operation in getattr(path_view, "operations", []):
                target_view = unwrap(operation.view_func)
                types_namespace = dict(getattr(target_view, "__globals__", {}))
                for model in getattr(operation, "models", []):
                    if getattr(model, "__pydantic_complete__", True):
                        continue
                    model.model_rebuild(_types_namespace=types_namespace)
                    log.info(
                        "Rebuilt Ninja operation model %s for %s %s",
                        model.__name__,
                        ",".join(operation.methods),
                        path,
                    )


_rebuild_ninja_operation_models()

urlpatterns = [
    path("", api.urls),
]
