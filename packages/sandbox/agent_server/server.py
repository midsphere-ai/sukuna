"""Backward-compatible facade for the agent server.

This module re-exports all public symbols from the sub-modules so that
existing ``from agent_server.server import X`` statements continue to work.

The actual implementation lives in:
  - prompts.py        — Prompt constants
  - config.py         — Runtime configuration & vault
  - auth.py           — Authentication backends
  - infra/            — Tool registry, backend sync, guardrails, event bus, lease (was core.py)
  - engine/run.py     — Agent execution engine (_run_agent) (was runner.py)
  - engine/context.py — Context engine (was context_engine.py)
  - engine/knowledge.py — Knowledge manager (was knowledge_manager.py)
  - engine/harness.py — Orchestrator harness (was orchestrator_harness.py)
  - engine/mcp.py     — MCP offload (was mcp_offload.py)
  - api/              — API endpoints & server lifecycle (was routes.py)
"""

from __future__ import annotations

# Re-export routes (endpoints register on routers at import time)
from agent_server.api import (  # noqa: F401
    _FILES_ROOT,
    _build_tree,
    _cli,
    _resolve_sandbox_path,
    init_server,
    shutdown_server,
)

# Re-export auth
from agent_server.auth import (  # noqa: F401
    BearerTokenAuth,
    JWTStreamAuth,
    QueryParamAPIKeyAuth,
    QueryParamJWTAuth,
    StaticAPIKeyAuth,
    default_auth,
    stream_auth,
)

# Re-export config
from agent_server.config import (  # noqa: F401
    _STATUS_SUPPRESS,
    _TERMINAL_STATUSES,
    AGENT_INSTRUCTIONS,
    AGENT_MAX_STEPS,
    AGENT_MODEL,
    AGENT_PROVIDER_TIMEOUT_SECONDS,
    AGENT_PTC_ENABLED,
    AGENT_RUN_TIMEOUT,
    API_KEY,
    DATABASE_URL,
    EVENT_BATCH_FLUSH_MS,
    EVENT_BATCH_SIZE,
    EXECUTOR_MAX_STEPS,
    EXTERNAL_MCP_CONFIGS,
    HITL_TIMEOUT,
    LLM_EVENT_TIMEOUT_RETRIES,
    LLM_EVENT_TIMEOUT_SECONDS,
    LLM_PREFLIGHT_BACKOFF_SECONDS,
    LLM_PREFLIGHT_ENABLED,
    LLM_PREFLIGHT_MAX_RETRIES,
    LLM_PREFLIGHT_TIMEOUT_SECONDS,
    PORT,
    RUN_STREAM_DB_CHUNK_SIZE,
    RUN_STREAM_KEEPALIVE_SECONDS,
    SANDBOX_WORKSPACE_ROOT,
    SUKUNA_SANDBOX_ID,
    USAGE_FLUSH_EVENTS,
    USAGE_FLUSH_SECONDS,
    MCPServerConfig,
    _inject_tool_env_vars,
    _load_exo_md,
    _parse_external_mcp_servers,
    load_env_from_vault,
)

# Re-export agent hooks
from agent_server.engine.hooks import (  # noqa: F401
    budget_monitor_hook,
    context_persistence_hook,
)

# Re-export runner
from agent_server.engine.run import (  # noqa: F401
    HTTPHumanInputHandler,
    _run_agent,
)

# Re-export core infrastructure
# Re-export backend sync helpers (used by tests)
from agent_server.infra import (  # noqa: F401
    LeaseEnforcer,
    LeaseLimits,
    LeaseViolation,
    RunNotifyChannel,
    ToolRegistry,
    ToolWhitelistRail,
    UsageTotals,
    _active_conversations,
    _apply_usage,  # noqa: F401
    _check_prd_completion,
    _format_sse_event,
    _get_run,
    _hitl_pending,
    _memory_store,
    _merge_prd_passes,
    _parse_positive_float,
    _parse_positive_int,
    _read_progress_patterns,
    _run_agents,
    _run_channels,
    _run_mcp_config_paths,
    _run_mcp_servers,
    _run_tasks,
    attach_guardrails,
    build_cli_tool_catalog,
    cleanup_run_usage,
    create_input_guardrail,
    files_router,
    health_router,
    hitl_router,
    integrations_router,
    mcp_router,
    parse_lease_limits,
    persist_context_event,
    populate_registry,
    populate_skill_registry,
    registry,
    runs_router,
    skill_registry,
    skills_router,
    streaming_router,
    sync_attachment,
    sync_plan,
    sync_run_cancelled,
    sync_run_completed,
    sync_run_failed,
    sync_run_started,
    sync_run_usage,
    update_usage_totals,
    update_usage_tracking,
)

# Re-export prompts
from agent_server.prompts import (  # noqa: F401
    _PRD_JSON_SCHEMA_DOC,
    BROWSER_EXTENSION,
    CODE_PROMPT,
    GUARD_PROMPT,
    OCR_PROMPT,
    RALPH_WORKER_INSTRUCTIONS,
    REASONING_PROMPT,
    VQA_PROMPT,
)
