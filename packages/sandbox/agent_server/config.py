"""Runtime configuration, environment loading, and vault integration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path as FilePath

import requests
import urllib3
from pydantic import BaseModel, Field, TypeAdapter

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

log = logging.getLogger("agent_server")

# Ensure tools/ is importable — tool modules use ``from lib.utils import ...``
# which requires the tools/ directory on sys.path.
_tools_dir = str(FilePath(__file__).resolve().parent.parent / "tools")
if _tools_dir not in sys.path:
    sys.path.insert(0, _tools_dir)


# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  VAULT — OpenBao/Vault secret loading                                      ║
# ║                                                                            ║
# ║  Reads VAULT_ADDR + VAULT_TOKEN from os.environ, fetches all secrets       ║
# ║  from the vault, and injects them back into os.environ so every module     ║
# ║  downstream can use plain os.getenv() to access them.                      ║
# ╚══════════════════════════════════════════════════════════════════════════════╝


class OpenBaoEnvLoader:
    def __init__(self, vault_addr: str, token: str):
        self.vault_addr = vault_addr.rstrip("/")
        self.token = token
        self.headers = {"X-Vault-Token": token}

    def load_secrets(self, secret_path: str, mount_point: str = "cubbyhole") -> dict:
        if mount_point == "cubbyhole":
            url = f"{self.vault_addr}/v1/{mount_point}/{secret_path}"
        else:
            url = f"{self.vault_addr}/v1/{mount_point}/data/{secret_path}"

        try:
            response = requests.get(url, headers=self.headers, verify=False)
            response.raise_for_status()
            data = response.json()
            if mount_point == "cubbyhole":
                return data.get("data", {})
            else:
                return data.get("data", {}).get("data", {})
        except requests.exceptions.RequestException as e:
            log.error("Error loading secrets from vault: %s", e)
            return {}

    def load_to_env(self, secret_path: str = "root", mount_point: str = "cubbyhole") -> int:
        secrets = self.load_secrets(secret_path, mount_point)
        count = 0
        for key, value in secrets.items():
            os.environ[key.upper()] = str(value)
            count += 1
        return count


def load_env_from_vault(secret_path: str = "root", mount_point: str = "cubbyhole") -> int:
    """Load all secrets from vault into os.environ.

    Reads only VAULT_ADDR and VAULT_TOKEN from the environment.
    Raises RuntimeError if either is missing.
    """
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")

    if not vault_addr or not vault_token:
        missing = []
        if not vault_addr:
            missing.append("VAULT_ADDR")
        if not vault_token:
            missing.append("VAULT_TOKEN")
        raise RuntimeError(
            f"Required environment variable(s) not set: {', '.join(missing)}. "
            "These are the only env vars the agent server requires at startup."
        )

    log.info("Connecting to vault at: %s", vault_addr)
    loader = OpenBaoEnvLoader(vault_addr, vault_token)
    count = loader.load_to_env(secret_path=secret_path, mount_point=mount_point)
    log.info("Loaded %d environment variables from vault", count)
    return count


# ── CONFIG — Runtime configuration constants ──────────────────────────────────


class MCPServerConfig(BaseModel):
    """Pydantic model mirroring exo's MCPServerConfig fields."""

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] | None = None
    timeout: float = 30.0
    sse_read_timeout: float = 300.0
    cache_tools: bool = False
    session_timeout: float | None = 120.0
    # Billing tier for per-tool-call credit billing (basic/standard/premium)
    credit_tier: str = "standard"


# ── Inject standard env var names from vault's MANAGED_* secrets ──────────────

_g = os.getenv  # shorthand


# OpenAI-compatible endpoint (super LLM)
if _g("MANAGED_SUPER_LLM_API_KEY") and not _g("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = _g("MANAGED_SUPER_LLM_API_KEY", "")
if _g("MANAGED_SUPER_LLM_BASE_URL") and not _g("OPENAI_BASE_URL"):
    os.environ["OPENAI_BASE_URL"] = _g("MANAGED_SUPER_LLM_BASE_URL", "")


# ── Core constants ─────────────────────────────────────────────────────────────

# Vault stores the DB URL as MIDSPHERE_DB_URL; fall back to DATABASE_URL.
DATABASE_URL: str = _g("DATABASE_URL") or _g("MIDSPHERE_DB_URL", "")
# Sandbox memory-store DB pool bounds (avoids asyncpg default 10/10 pool per process).
AGENT_MEMORY_DB_POOL_MIN_SIZE: int = max(int(_g("AGENT_MEMORY_DB_POOL_MIN_SIZE", "1")), 1)
AGENT_MEMORY_DB_POOL_MAX_SIZE: int = max(
    int(_g("AGENT_MEMORY_DB_POOL_MAX_SIZE", "2")),
    AGENT_MEMORY_DB_POOL_MIN_SIZE,
)
AGENT_MEMORY_DB_POOL_MAX_QUERIES: int = max(int(_g("AGENT_MEMORY_DB_POOL_MAX_QUERIES", "50000")), 1)
AGENT_MEMORY_DB_POOL_MAX_INACTIVE_SECONDS: float = max(
    float(_g("AGENT_MEMORY_DB_POOL_MAX_INACTIVE_SECONDS", "60")),
    0.0,
)

PORT: int = int(_g("PORT", "8000"))

# Build AGENT_MODEL from vault's MANAGED_SUPER_LLM_* if not explicitly set.
_super_provider = _g("MANAGED_SUPER_LLM_PROVIDER", "openai")
_super_model = _g("MANAGED_SUPER_LLM_MODEL", "zai-org/glm-5-maas")
AGENT_MODEL: str = _g("AGENT_MODEL", f"{_super_provider}:{_super_model}")

# Per-agent LLM-call budgets. Both have to be larger than the context
# engine's compaction interval (default 150) for compaction to fire even
# once during a single agent's lifetime, and ideally larger than the
# summarization interval (default 400) for long-running executors.
#
#   AGENT_MAX_STEPS    — planner; persists for the whole run, mostly
#                        delegates so its turn count is loosely bounded.
#   EXECUTOR_MAX_STEPS — each delegation; gets a fresh ContextEngineState,
#                        so its turn count starts from zero per delegation.
AGENT_MAX_STEPS: int = int(_g("AGENT_MAX_STEPS", "200"))
EXECUTOR_MAX_STEPS: int = int(_g("EXECUTOR_MAX_STEPS", "250"))
AGENT_PTC_ENABLED: bool = _g("AGENT_PTC_ENABLED", "true").lower() in ("1", "true", "yes")
AGENT_KM_ENABLED: bool = _g("AGENT_KM_ENABLED", "true").lower() in ("1", "true", "yes", "on")
# Ralph autonomous multi-story loop. Disabled by default — the implementation has
# proven messy and unintuitive in practice. Code paths are kept for future
# reference; flip this on to re-expose the tool to the planner.
AGENT_RALPH_ENABLED: bool = _g("AGENT_RALPH_ENABLED", "false").lower() in ("1", "true", "yes", "on")
HITL_TIMEOUT: float = float(_g("HITL_TIMEOUT_SECONDS", "172800"))
from agent_server.engine.prompts import PLANNER_BASE_INSTRUCTIONS  # noqa: E402

AGENT_INSTRUCTIONS: str = _g("AGENT_INSTRUCTIONS", PLANNER_BASE_INSTRUCTIONS)
# Event persistence batching (smaller commit count, lower DB overhead).
EVENT_BATCH_SIZE: int = max(int(_g("EVENT_BATCH_SIZE", "20")), 1)
EVENT_BATCH_FLUSH_MS: float = max(float(_g("EVENT_BATCH_FLUSH_MS", "100")), 1.0)
# Cap per-run in-memory replay history to avoid unbounded growth on long runs.
RUN_EVENT_BUS_MAX_EVENTS: int = max(int(_g("RUN_EVENT_BUS_MAX_EVENTS", "1000")), 1)
# Chunk size for streaming DB-backed SSE replays.
RUN_STREAM_DB_CHUNK_SIZE: int = max(int(_g("RUN_STREAM_DB_CHUNK_SIZE", "1000")), 1)
# SSE keepalive period for stream endpoints.
RUN_STREAM_KEEPALIVE_SECONDS: float = max(float(_g("RUN_STREAM_KEEPALIVE_SECONDS", "10.0")), 1.0)

# Upstream LLM hardening.
# - PREFLIGHT: fast connectivity check before the main run stream starts.
# - PROVIDER TIMEOUT: per-provider request timeout passed to exo get_provider.
# - EVENT TIMEOUT: max time to wait for the next run.stream() event before fail.
LLM_PREFLIGHT_ENABLED: bool = _g("LLM_PREFLIGHT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
LLM_PREFLIGHT_TIMEOUT_SECONDS: float = max(float(_g("LLM_PREFLIGHT_TIMEOUT_SECONDS", "12.0")), 0.1)
LLM_PREFLIGHT_MAX_RETRIES: int = max(int(_g("LLM_PREFLIGHT_MAX_RETRIES", "2")), 0)
LLM_PREFLIGHT_BACKOFF_SECONDS: float = max(float(_g("LLM_PREFLIGHT_BACKOFF_SECONDS", "1.0")), 0.0)
AGENT_PROVIDER_TIMEOUT_SECONDS: float = max(float(_g("AGENT_PROVIDER_TIMEOUT_SECONDS", "600.0")), 1.0)
LLM_EVENT_TIMEOUT_SECONDS: float = max(float(_g("LLM_EVENT_TIMEOUT_SECONDS", "120.0")), 0.1)
LLM_EVENT_TIMEOUT_RETRIES: int = max(int(_g("LLM_EVENT_TIMEOUT_RETRIES", "2")), 0)

# Usage callback batching thresholds — how often to sync usage to backend tables.
USAGE_FLUSH_SECONDS: float = max(float(_g("SUKUNA_BACKEND_USAGE_FLUSH_SECONDS", "5.0")), 0.1)
USAGE_FLUSH_EVENTS: int = max(int(_g("SUKUNA_BACKEND_USAGE_FLUSH_EVENTS", "5")), 1)

# Sandbox identity for backend_sync calls.
SUKUNA_SANDBOX_ID: str | None = _g("SUKUNA_SANDBOX_ID") or None

# ── Shared Azure creds (read once, referenced by multiple tool envs) ───────────
_azure_api_key = _g("AZURE_OPENAI_API_KEY", "")
_azure_endpoint = _g("AZURE_OPENAI_ENDPOINT", "")
_azure_api_version = _g("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")


def _resolve_workspace_root() -> str:
    """Resolve workspace root from runtime environment with safe fallback."""
    return _g("PROJECT_DIR") or _g("WORKSPACE") or _g("SANDBOX_WORKSPACE_ROOT") or str(FilePath.home())


# Sandbox workspace root used by tool modules.
SANDBOX_WORKSPACE_ROOT: str = _resolve_workspace_root()

# Bundled scaffolding assets live alongside the installed agent_server/ package
# (mirrors the bundled-skills resolution in agent_server/infra/registry.py).
# They are install-time static assets — NOT workspace-relative.
_INSTALL_ROOT = FilePath(__file__).resolve().parent.parent
_SANDBOX_TEMPLATES = str(_INSTALL_ROOT / "templates")

_SANDBOX_PRESENTATIONS = f"{SANDBOX_WORKSPACE_ROOT}/presentations"
_SANDBOX_COOKIES = f"{SANDBOX_WORKSPACE_ROOT}/cookies.json"


def _inject_tool_env_vars() -> None:
    """Inject env vars that both in-process and CLI-offloaded tools expect.

    All vars set here are inherited by ``exo tool call`` subprocesses via
    standard process environment inheritance (``asyncio.create_subprocess_shell``
    with no explicit ``env=``).  This keeps secrets in-memory only — never
    written to disk.  Do NOT add ``env=`` overrides to the shell tool's
    subprocess calls, or CLI-offloaded tools will lose access to these vars.

    For env vars that conflict across tool modules (LLM_API_KEY, LLM_BASE_URL,
    etc.), the tool modules have been updated to prefer their own MANAGED_*
    prefixed names (e.g. MANAGED_AUDIO_LLM_API_KEY).  Only non-conflicting
    vars are injected here.
    """
    _setdefault = os.environ.setdefault

    # ── Workspace paths (shared across multiple tools) ──────────────────
    _setdefault("PROJECT_DIR", SANDBOX_WORKSPACE_ROOT)
    _setdefault("WORKSPACE", SANDBOX_WORKSPACE_ROOT)
    _setdefault("MIDSPHERE_WORKSPACE", SANDBOX_WORKSPACE_ROOT)
    _setdefault("TEMPLATE_BASE_PATH", _SANDBOX_TEMPLATES)
    _setdefault("MOBILE_TEMPLATE_PATH", f"{_SANDBOX_TEMPLATES}/websites/expo-mobile-template")
    _setdefault("PRESENTATIONS_DIR", _SANDBOX_PRESENTATIONS)
    _setdefault("TEMPLATES_DIR", _SANDBOX_TEMPLATES)
    _setdefault("COOKIES_FILE_PATH", _SANDBOX_COOKIES)

    # ── Plan tool defaults ──────────────────────────────────────────────
    _setdefault("CURRENT_SCHEDULED_TASKS_LENGTH", "0")
    _setdefault("MAX_ALLOWED_SCHEDULED_TASKS", "10")

    # ── Audio/Vision default temperatures (previously hardcoded in MCP env) ──
    _setdefault("LLM_MODEL_TEMPERATURE", "0.7")
    _setdefault("LLM_MODEL_TRANSCRIPTION_NAME", "whisper-1")

    # ── Exo CLI tool offloading (exo tool call) ───────────────────────────
    # EXO_TOOL_SOURCE points to the barrel module so agents don't need
    # --from on every call.  PYTHONPATH ensures tool modules' internal
    # imports (from lib.utils, etc.) resolve in the CLI subprocess.
    _cli_tools_path = str(FilePath(__file__).resolve().parent.parent / "tools" / "cli_tools.py")
    _setdefault("EXO_TOOL_SOURCE", _cli_tools_path)
    _existing_pypath = os.environ.get("PYTHONPATH", "")
    if _tools_dir not in _existing_pypath.split(os.pathsep):
        os.environ["PYTHONPATH"] = _tools_dir + os.pathsep + _existing_pypath if _existing_pypath else _tools_dir


# ── EXO.md project context loading ──────────────────────────────────────────

_EXO_MD_MAX_BYTES = 50 * 1024  # 50 KB


def _load_exo_md() -> tuple[str | None, bool]:
    """Load EXO.md from workspace root (case-insensitive).

    Returns ``(content, truncated)`` or ``(None, False)`` if no file found.
    """
    workspace = FilePath(SANDBOX_WORKSPACE_ROOT)
    try:
        for entry in workspace.iterdir():
            if entry.name.lower() == "exo.md" and entry.is_file():
                raw = entry.read_text(encoding="utf-8", errors="replace")
                byte_len = len(raw.encode("utf-8"))
                if byte_len > _EXO_MD_MAX_BYTES:
                    raw = raw[:_EXO_MD_MAX_BYTES] + "\n\n[WARNING: EXO.md truncated at 50KB]"
                    return raw, True
                return raw, False
    except Exception:
        log.debug("Failed to scan workspace for EXO.md", exc_info=True)
    return None, False


def _seed_agents_md(
    *,
    project_title: str,
    project_custom_instructions: str,
    project_files: list[dict] | None,
) -> bool:
    """Seed ``AGENTS.md`` at workspace root for a project-scoped run.

    Idempotent and race-safe: uses ``open(path, "x")`` so concurrent
    seeders cannot clobber each other, and the file is never overwritten
    once it exists (so learnings appended by prior agents survive).

    Returns ``True`` when this call wrote the file, ``False`` when it
    already existed or writing failed.
    """
    path = FilePath(SANDBOX_WORKSPACE_ROOT) / "AGENTS.md"

    file_lines: list[str] = []
    if project_files:
        for entry in project_files:
            if not isinstance(entry, dict):
                continue
            filename = str(entry.get("filename", "")).strip()
            sandbox_path = str(entry.get("sandbox_path") or entry.get("file_path") or "").strip()
            if filename and sandbox_path:
                file_lines.append(f"- {filename} — {sandbox_path}")
            elif filename:
                file_lines.append(f"- {filename}")
            elif sandbox_path:
                file_lines.append(f"- {sandbox_path}")
    if not file_lines:
        file_lines.append("- (none)")

    instructions_body = (project_custom_instructions or "").strip() or "(none provided)"

    body = (
        "# AGENTS.md — Project Coordination Channel\n\n"
        "This file is a shared scratchpad between AI agents that may be "
        "working concurrently in this project sandbox. Read it before you "
        "start. Append to it as you learn things other agents will need "
        "to know.\n\n"
        "## Concurrency model\n"
        "- Multiple conversations can share this sandbox simultaneously.\n"
        "- Treat the workspace as shared mutable state.\n"
        "- For any coding work, create a dedicated `git worktree` under "
        "`.worktrees/` so your edits do not clobber another agent's "
        "in-progress branch.\n"
        '- Record the worktree path you claimed in "Active worktrees" '
        "below.\n\n"
        "## Project\n"
        f"Title: {project_title or '(untitled)'}\n\n"
        "## Custom Prompt Extension\n"
        f"{instructions_body}\n\n"
        "## Uploaded project files\n" + "\n".join(file_lines) + "\n\n"
        "## Shared learnings\n"
        "(Agents append notes here. Keep entries dated and signed with "
        "run_id.)\n\n"
        "## Active worktrees\n"
        "(Agents list the worktree paths they currently hold.)\n"
    )

    try:
        with path.open("x", encoding="utf-8") as fh:
            fh.write(body)
    except FileExistsError:
        return False
    except Exception:
        log.warning("Failed to seed AGENTS.md at %s", path, exc_info=True)
        return False
    log.info("Seeded AGENTS.md at %s (%d bytes)", path, len(body))
    return True


# ── External MCP server configs (user-provided, not built-in tools) ──────────
_ta = TypeAdapter(list[MCPServerConfig])


def _parse_external_mcp_servers() -> list[MCPServerConfig]:
    """Parse MCP_SERVERS_JSON for external (user-provided) MCP servers only.

    Built-in tools are now native @tool functions loaded via the tool registry.
    This only applies when users explicitly set MCP_SERVERS_JSON in vault.
    """
    raw = _g("MCP_SERVERS_JSON", "[]")
    try:
        configs = _ta.validate_json(raw)
        return configs if configs else []
    except Exception as exc:
        raise ValueError(f"MCP_SERVERS_JSON is not valid: {exc}") from exc


EXTERNAL_MCP_CONFIGS: list[MCPServerConfig] = _parse_external_mcp_servers()

# float("0") → 0.0 → falsy → None (unlimited); float("300") → 300.0 → truthy → 300.0
AGENT_RUN_TIMEOUT: float | None = float(_g("AGENT_RUN_TIMEOUT_SECONDS", "0")) or None

# Sub-agent StatusEvent statuses that should NOT be forwarded to SSE clients.
# These represent individual agent-step endings, not run-level terminal state.
# The actual run lifecycle is signalled by run_completed / run_failed / run_cancelled.
_STATUS_SUPPRESS: frozenset[str] = frozenset({"completed", "cancelled", "error"})

# Empty string treated as unset (auth disabled)
# Prefer explicit namespaced key and keep API_KEY as legacy fallback.
API_KEY: str | None = _g("SUKUNA_AGENT_SERVER_API_KEY") or _g("API_KEY") or None

# Terminal statuses that must never be overwritten.
_TERMINAL_STATUSES: set[str] = {"completed", "failed", "cancelled"}
