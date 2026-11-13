"""HITL (Human-in-the-Loop) and MCP server management endpoints.

GET  /runs/{id}/hitl/pending     -> Poll for oldest pending HITL request
GET  /runs/{id}/hitl             -> List all HITL requests for a run
POST /runs/{id}/hitl/{req_id}    -> Submit human response, unblock agent
GET    /runs/{id}/mcp            -> List dynamic MCP servers on a run
POST   /runs/{id}/mcp            -> Hot-add an MCP server to a live run
DELETE /runs/{id}/mcp/{server}   -> Remove a dynamic MCP server
"""

from __future__ import annotations

import logging
from pathlib import Path as FilePath
from typing import Any

from asgiref.sync import sync_to_async
from django.utils import timezone
from ninja import Body, Schema
from ninja.errors import HttpError

from agent_server.auth import require_scope
from agent_server.config import MCPServerConfig
from agent_server.infra import (
    _hitl_pending,
    _run_agents,
    _run_mcp_config_paths,
    _run_mcp_servers,
    hitl_router,
    mcp_router,
)
from agent_server.models import (
    DjangoConversation,
    SandboxRun,
)
from agent_server.models import (
    HitlRequest as HitlRequestModel,
)

log = logging.getLogger("agent_server")


# ── Request / response schemas ───────────────────────────────────────────────


class HitlResponseSchema(Schema):
    response: str


class AddMcpServerRequest(MCPServerConfig):
    pass


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 8 — HITL (Human-in-the-Loop) ENDPOINTS                           ║
# ║                                                                            ║
# ║  GET  /runs/{id}/hitl/pending     → Poll for oldest pending HITL request   ║
# ║  GET  /runs/{id}/hitl             → List all HITL requests for a run       ║
# ║  POST /runs/{id}/hitl/{req_id}    → Submit human response, unblock agent   ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@hitl_router.get("/runs/{run_id}/hitl/pending")
@require_scope(["stream:read"])
async def get_pending_hitl(request, run_id: str) -> dict[str, Any]:
    """Poll for the oldest pending HITL request on this run."""
    # Validate the run exists before querying HITL requests.
    run_exists = await sync_to_async(SandboxRun.objects.filter(id=run_id).exists)()
    if not run_exists:
        raise HttpError(404, f"Run {run_id} not found")

    hitl = await sync_to_async(
        HitlRequestModel.objects.filter(run_id=run_id, status="pending").order_by("created_at").first
    )()

    if hitl is None:
        return {"pending": False}
    return {
        "pending": True,
        "request_id": hitl.id,
        "prompt": hitl.prompt,
        "choices": hitl.choices,
    }


@hitl_router.get("/runs/{run_id}/hitl")
@require_scope(["stream:read"])
async def list_hitl_requests(
    request,
    run_id: str,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Return all HITL requests for a run (full history, not just pending)."""
    agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
    if agent_run is None:
        raise HttpError(404, f"Run {run_id} not found")

    qs = HitlRequestModel.objects.filter(run_id=run_id)
    if status is not None:
        qs = qs.filter(status=status)

    total = await sync_to_async(qs.count)()

    hitl_requests = await sync_to_async(list)(qs.order_by("created_at")[offset : offset + limit])

    return {
        "run_id": run_id,
        "hitl_requests": [
            {
                "request_id": h.id,
                "prompt": h.prompt,
                "choices": h.choices,
                "status": h.status,
                "response": h.response,
                "created_at": h.created_at.isoformat(),
                "responded_at": h.responded_at.isoformat() if h.responded_at else None,
            }
            for h in hitl_requests
        ],
        "total": total,
    }


@hitl_router.post("/runs/{run_id}/hitl/{request_id}")
@require_scope(["hitl:respond"])
async def respond_to_hitl(
    request,
    run_id: str,
    request_id: str,
    body: HitlResponseSchema = Body(...),
) -> dict[str, str]:
    """Submit a human response, unblocking the agent."""
    future = _hitl_pending.get(run_id, {}).get(request_id)
    if future is None:
        raise HttpError(404, f"No pending HITL request {request_id} for run {run_id}")
    if future.done():
        raise HttpError(409, "HITL request already responded to")

    future.set_result(body.response)

    await sync_to_async(HitlRequestModel.objects.filter(id=request_id).update)(
        status="responded",
        response=body.response,
        responded_at=timezone.now(),
    )

    # Clear the conversation-level HITL flag. Use run_id → conversation_id lookup
    # rather than requiring the caller to pass it — one round-trip inside a
    # sync_to_async is cheap and keeps the API surface unchanged.
    agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
    if agent_run is not None and agent_run.conversation_id:
        try:
            await sync_to_async(DjangoConversation.objects.filter(id=agent_run.conversation_id).update)(
                requires_user_input=False
            )
        except Exception:
            log.debug(
                "Failed to clear requires_user_input on conversation %s",
                agent_run.conversation_id,
                exc_info=True,
            )

    log.info("HITL resolved: run=%s request=%s", run_id, request_id)
    return {"status": "ok", "request_id": request_id}


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  SECTION 9 — MCP SERVER MANAGEMENT ENDPOINTS                              ║
# ║                                                                            ║
# ║  GET    /runs/{id}/mcp              → List dynamic MCP servers on a run    ║
# ║  POST   /runs/{id}/mcp              → Hot-add an MCP server to a live run  ║
# ║  DELETE /runs/{id}/mcp/{server}     → Remove a dynamic MCP server          ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


@mcp_router.get("/runs/{run_id}/mcp")
@require_scope(["stream:read"])
async def list_run_mcp_servers(request, run_id: str) -> dict[str, Any]:
    """List MCP servers dynamically added to a live run."""
    agent_run = await sync_to_async(SandboxRun.objects.filter(id=run_id).first)()
    if agent_run is None:
        raise HttpError(404, f"Run {run_id} not found")

    return {
        "run_id": run_id,
        "is_active": run_id in _run_agents,
        "mcp_servers": [{"name": name, "tools": tools} for name, tools in _run_mcp_servers.get(run_id, {}).items()],
    }


@mcp_router.post("/runs/{run_id}/mcp", response={201: dict})
@require_scope(["mcp:manage"])
async def add_run_mcp_server(request, run_id: str, body: AddMcpServerRequest = Body(...)) -> tuple[int, dict[str, Any]]:
    """Hot-add an MCP server to a live run via exo-mcp-cli offloading.

    The server config is written to mcp.json on disk and a notification
    message is injected into the agent so it knows a new server is available.
    Tools are NOT added to the agent's tool list — they stay offloaded.
    """
    from agent_server.engine.mcp import (
        MCP_CONFIG_PATH,
        add_server_to_config,
        build_server_catalog_snippet,
    )

    harness = _run_agents.get(run_id)
    if harness is None:
        raise HttpError(409, f"Run {run_id} is not active — hot-add requires a live run")

    server_name = body.name
    if server_name in _run_mcp_servers.get(run_id, {}):
        raise HttpError(409, f"MCP server '{server_name}' is already registered on run {run_id}")

    # Update mcp.json on disk
    config_path = FilePath(_run_mcp_config_paths.get(run_id, str(MCP_CONFIG_PATH)))
    add_server_to_config(body, config_path)

    # Discover tools from the new server and build a catalog snippet
    snippet = await build_server_catalog_snippet(server_name, config_path)

    # Track tool names (from the catalog listing)
    from agent_server.engine.mcp import _list_server_tools

    tools = await _list_server_tools(server_name, config_path)
    tool_names = [t.get("name", "") for t in tools]
    _run_mcp_servers.setdefault(run_id, {})[server_name] = tool_names

    # Store config path if not yet set (for runs that started without MCP)
    if run_id not in _run_mcp_config_paths:
        _run_mcp_config_paths[run_id] = str(config_path)

    # Notify the agent via inject_message
    harness.inject_message(snippet)

    log.info("Hot-added MCP server '%s' to run %s (offloaded): %s", server_name, run_id, tool_names)
    return 201, {"server_name": server_name, "tools_added": tool_names}


@mcp_router.delete("/runs/{run_id}/mcp/{server_name}")
@require_scope(["mcp:manage"])
async def remove_run_mcp_server(request, run_id: str, server_name: str) -> dict[str, Any]:
    """Remove a dynamically-added MCP server from a live run.

    The server config is removed from mcp.json and a notification message
    is injected so the agent knows to stop calling that server's tools.
    """
    from agent_server.engine.mcp import MCP_CONFIG_PATH, remove_server_from_config

    harness = _run_agents.get(run_id)
    if harness is None:
        raise HttpError(409, f"Run {run_id} is not active — tool removal requires a live run")

    servers = _run_mcp_servers.get(run_id, {})
    tool_names = servers.get(server_name)
    if tool_names is None:
        raise HttpError(404, f"MCP server '{server_name}' not found on run {run_id}")

    # Update mcp.json on disk
    config_path = FilePath(_run_mcp_config_paths.get(run_id, str(MCP_CONFIG_PATH)))
    remove_server_from_config(server_name, config_path)

    del servers[server_name]

    # Notify the agent
    harness.inject_message(
        f"MCP server '{server_name}' has been removed. Do not call its tools ({', '.join(tool_names)})."
    )

    log.info("Removed MCP server '%s' from run %s: %s", server_name, run_id, tool_names)
    return {"server_name": server_name, "tools_removed": tool_names}
