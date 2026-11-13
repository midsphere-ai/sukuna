"""MCP tool offloading via exo-mcp CLI.

Instead of loading MCP tools into the agent's tool list (which bloats
the LLM ``tools=`` parameter and breaks KV cache), we write an
``mcp.json`` config to disk and let the agent call tools via::

    exo-mcp tool call <server> <tool> --config <path> -j '{"arg": "val"}'

This module provides helpers to:
- Convert ``MCPServerConfig`` objects to ``mcp.json`` format
- Add/remove servers from an existing ``mcp.json``
- Hoist secrets from env/headers into real env vars (never written to disk)
- Enumerate tools from each server via ``exo-mcp tool list``
- Build a markdown catalog for agent instructions
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_server.server import MCPServerConfig

log = logging.getLogger(__name__)

MCP_CONFIG_DIR = Path("/tmp/.exo-mcp")
MCP_CONFIG_PATH = MCP_CONFIG_DIR / "mcp.json"

# Matches ${VAR} or ${vault:NAME} — used to detect values that are
# already references (should NOT be hoisted again).
_REF_PATTERN = re.compile(r"\$\{.+?\}")


# ---------------------------------------------------------------------------
# Env hoisting — keep secrets in process env, not on disk
# ---------------------------------------------------------------------------


def _is_reference(value: str) -> bool:
    """Return True if the value is already a ``${...}`` reference."""
    return bool(_REF_PATTERN.fullmatch(value.strip()))


def _hoist_env(server_name: str, env: dict[str, str]) -> dict[str, str]:
    """Hoist literal env values into ``os.environ`` and return a dict of
    ``${ENV_VAR}`` references for mcp.json.

    Values that are already ``${...}`` references are passed through as-is.
    """
    refs: dict[str, str] = {}
    for key, value in env.items():
        if _is_reference(value):
            refs[key] = value
        else:
            # Namespace to avoid collisions: MCP_<SERVER>_<KEY>
            env_name = f"MCP_{_safe_name(server_name)}_{key}"
            os.environ[env_name] = value
            refs[key] = f"${{{env_name}}}"
    return refs


def _hoist_headers(server_name: str, headers: dict[str, str]) -> dict[str, str]:
    """Hoist literal header values into ``os.environ`` and return a dict of
    ``${ENV_VAR}`` references for mcp.json.
    """
    refs: dict[str, str] = {}
    for key, value in headers.items():
        if _is_reference(value):
            refs[key] = value
        else:
            env_name = f"MCP_{_safe_name(server_name)}_HDR_{_safe_name(key)}"
            os.environ[env_name] = value
            refs[key] = f"${{{env_name}}}"
    return refs


def _safe_name(name: str) -> str:
    """Sanitise a name for use as an env-var segment (uppercase, underscores)."""
    return re.sub(r"[^A-Za-z0-9]", "_", name).upper()


# ---------------------------------------------------------------------------
# Config file management
# ---------------------------------------------------------------------------


def _server_to_entry(cfg: MCPServerConfig) -> dict[str, Any]:
    """Convert a single MCPServerConfig to mcp.json entry format.

    Literal secrets in ``env`` and ``headers`` are hoisted into process
    env vars so mcp.json only contains ``${ENV_VAR}`` references.
    """
    entry: dict[str, Any] = {"transport": cfg.transport}
    if cfg.command is not None:
        entry["command"] = cfg.command
    if cfg.args:
        entry["args"] = cfg.args
    if cfg.env:
        entry["env"] = _hoist_env(cfg.name, cfg.env)
    if cfg.cwd is not None:
        entry["cwd"] = cfg.cwd
    if cfg.url is not None:
        entry["url"] = cfg.url
    if cfg.headers is not None:
        entry["headers"] = _hoist_headers(cfg.name, cfg.headers)
    if cfg.timeout != 30.0:
        entry["timeout"] = cfg.timeout
    return entry


def write_mcp_config(
    configs: list[MCPServerConfig],
    path: Path = MCP_CONFIG_PATH,
) -> Path:
    """Convert MCPServerConfig list to ``mcp.json`` and write to disk.

    Literal secrets in env/headers are hoisted into ``os.environ`` so
    the config file only stores ``${ENV_VAR}`` references — never
    plain-text secrets.

    Returns the path to the written config file.
    """
    servers: dict[str, Any] = {}
    for cfg in configs:
        servers[cfg.name] = _server_to_entry(cfg)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}, indent=2))
    log.debug("Wrote mcp.json with %d servers to %s", len(servers), path)
    return path


def _read_config(path: Path) -> dict[str, Any]:
    """Read existing mcp.json, returning empty structure if missing."""
    if path.exists():
        return json.loads(path.read_text())
    return {"mcpServers": {}}


def add_server_to_config(
    cfg: MCPServerConfig,
    path: Path = MCP_CONFIG_PATH,
) -> None:
    """Add a single server to an existing ``mcp.json``."""
    data = _read_config(path)
    data["mcpServers"][cfg.name] = _server_to_entry(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    log.debug("Added server '%s' to %s", cfg.name, path)


def remove_server_from_config(
    server_name: str,
    path: Path = MCP_CONFIG_PATH,
) -> None:
    """Remove a server from ``mcp.json``."""
    data = _read_config(path)
    removed = data["mcpServers"].pop(server_name, None)
    if removed is not None:
        path.write_text(json.dumps(data, indent=2))
        log.debug("Removed server '%s' from %s", server_name, path)


# ---------------------------------------------------------------------------
# Tool catalog builder
# ---------------------------------------------------------------------------


async def _list_server_tools(
    server_name: str,
    config_path: Path,
) -> list[dict[str, Any]]:
    """Run ``exo-mcp tool list <server> --json`` and return parsed tool list."""
    cmd = [
        "exo-mcp",
        "tool",
        "list",
        server_name,
        "--json",
        "--config",
        str(config_path),
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        if proc.returncode != 0:
            log.warning(
                "exo-mcp tool list %s failed (rc=%d): %s",
                server_name,
                proc.returncode,
                stderr.decode().strip(),
            )
            return []
        return json.loads(stdout.decode())
    except asyncio.TimeoutError:
        log.warning("exo-mcp tool list %s timed out", server_name)
        return []
    except Exception as exc:
        log.warning("exo-mcp tool list %s error: %s", server_name, exc)
        return []


def _format_tool_signature(tool: dict[str, Any]) -> str:
    """Format a single tool as ``name(arg: type, ...) -- description``."""
    name = tool.get("name", "?")
    desc = tool.get("description", "")
    schema = tool.get("inputSchema") or {}
    props = schema.get("properties", {})
    required = set(schema.get("required", []))

    params: list[str] = []
    for pname, pschema in props.items():
        ptype = pschema.get("type", "any")
        marker = "" if pname in required else "?"
        params.append(f"{pname}{marker}: {ptype}")

    sig = f"{name}({', '.join(params)})"
    if desc:
        # Take first sentence only to keep catalog concise
        short = desc.split(". ")[0].rstrip(".")
        return f"- {sig} -- {short}"
    return f"- {sig}"


async def build_tool_catalog(
    config_path: Path = MCP_CONFIG_PATH,
) -> str:
    """Enumerate tools from all servers in ``mcp.json`` and return a
    markdown catalog suitable for agent instructions.

    Returns empty string if no servers or no tools found.
    """
    data = _read_config(config_path)
    server_names = list(data.get("mcpServers", {}).keys())
    if not server_names:
        return ""

    # List tools from all servers in parallel
    results = await asyncio.gather(*(_list_server_tools(name, config_path) for name in server_names))

    sections: list[str] = []
    for server_name, tools in zip(server_names, results):
        if not tools:
            continue
        lines = [f"### {server_name}"]
        for t in tools:
            lines.append(_format_tool_signature(t))
        sections.append("\n".join(lines))

    if not sections:
        return ""

    header = (
        "## External MCP Tools\n"
        "\n"
        "The following tools are available via external MCP servers.\n"
        "Call them using the shell tool:\n"
        "\n"
        "```\n"
        f'exo-mcp tool call <server> <tool> --config {config_path} -j \'{{"arg": "value"}}\'\n'
        "```\n"
    )
    return header + "\n" + "\n\n".join(sections) + "\n"


async def build_server_catalog_snippet(
    server_name: str,
    config_path: Path = MCP_CONFIG_PATH,
) -> str:
    """Build a catalog snippet for a single server (used for hot-add notifications)."""
    tools = await _list_server_tools(server_name, config_path)
    if not tools:
        return f"MCP server '{server_name}' connected (no tools discovered)."

    lines = [
        f"MCP server '{server_name}' is now available with the following tools:",
        f'Call via: exo-mcp tool call {server_name} <tool> --config {config_path} -j \'{{"arg": "value"}}\'',
        "",
    ]
    for t in tools:
        lines.append(_format_tool_signature(t))
    return "\n".join(lines)
