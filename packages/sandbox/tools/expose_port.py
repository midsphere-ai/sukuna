"""
Expose Port Tool

Provides an ``expose_port`` tool that the agent calls when it wants to make
a running service (web dev server, mobile preview, API, etc.) accessible to
the user.  This:

1. Extends the sandbox idle-pause timer so the sandbox stays alive while
   the user is viewing the preview.
2. Returns the publicly-accessible E2B URL for the given port.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, Any, Optional

import httpx
from _lib.utils import error_result, success_result
from exo import tool

__version__ = "0.1.0"

log = logging.getLogger(__name__)

_AGENT_SERVER_PORT = os.getenv("PORT", "8000")
_SANDBOX_ID: str | None = os.getenv("SUKUNA_SANDBOX_ID") or None


def _autodetect_framework_kind(port: int) -> tuple[Optional[str], Optional[str]]:
    """Best-effort lookup of (framework, kind) by matching port to a dev server
    and reading the project's .sandbox-meta.json.

    Returns (None, None) on any failure — auto-detect is purely additive.
    """
    try:
        # Lazy imports to avoid circular imports at module load time.
        from tools import mobile as mobile_mod  # type: ignore
        from tools import web as web_mod  # type: ignore

        project_path: Optional[Path] = None
        if getattr(web_mod, "server_port", None) == port:
            project_path = getattr(web_mod, "current_project_path", None)
        elif getattr(mobile_mod, "server_port", None) == port:
            project_path = getattr(mobile_mod, "current_project_path", None)

        if project_path is None:
            return None, None

        meta_file = Path(project_path) / ".sandbox-meta.json"
        if not meta_file.exists():
            return None, None

        data = json.loads(meta_file.read_text())
        framework = data.get("framework")
        kind = data.get("kind")
        return (
            framework if isinstance(framework, str) else None,
            kind if isinstance(kind, str) else None,
        )
    except Exception as e:
        log.debug("expose_port: auto-detect failed: %s", e)
        return None, None


@tool(name="expose")
async def expose_port_tool(
    port: Annotated[int, "Local port number in the sandbox to expose for public access."],
    label: Annotated[str | None, "Optional human-readable label (e.g. 'Next.js dev server')."] = None,
    framework: Annotated[
        Optional[str], "Optional framework hint (e.g. 'next', 'expo'). Auto-detected when omitted."
    ] = None,
    kind: Annotated[Optional[str], "Optional kind hint (e.g. 'web', 'expo-web'). Auto-detected when omitted."] = None,
) -> dict[str, Any]:
    """Expose a local port in the sandbox for temporary public access.

    <instructions>
    - This tool returns a temporary public proxied domain for the specified port in the sandbox.
    - Port information is encoded in domain prefix, no additional port specification needed.
    - Exposed services MUST NOT bind to specific IP addresses or Host headers.
    - DO NOT use for production as services will become unavailable after sandbox shutdown.
    </instructions>

    <recommended_usage>
    - Use for providing temporary public access for locally running services.
    </recommended_usage>
    """
    if port < 1 or port > 65535:
        return error_result(
            f"Invalid port {port}.",
            hint="Port must be between 1 and 65535.",
        )

    # Auto-detect framework/kind from .sandbox-meta.json if caller didn't supply them.
    if framework is None and kind is None:
        detected_framework, detected_kind = _autodetect_framework_kind(port)
        if framework is None:
            framework = detected_framework
        if kind is None:
            kind = detected_kind

    # Ask the agent server to extend the sandbox idle-pause timer.
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:{_AGENT_SERVER_PORT}/expose-port",
                json={"port": port, "label": label or ""},
                timeout=5,
            )
        data = resp.json()
        if data.get("status") != "ok":
            return error_result(
                "Could not expose port.",
                detail=data.get("message", ""),
            )
    except Exception as e:
        log.warning("expose_port: failed to call agent server: %s", e)
        return error_result("Failed to expose port.", error=str(e))

    public_url = data.get("url", "")
    extra: dict[str, Any] = {}
    if framework is not None:
        extra["framework"] = framework
    if kind is not None:
        extra["kind"] = kind

    result = success_result(
        f"Port {port} exposed — sandbox will stay alive for 30 minutes.",
        port=port,
        url=public_url,
        **extra,
    )
    if label:
        result["label"] = label
    return result


EXPOSE_PORT_TOOLS = [expose_port_tool]
