# Midsphere Sandbox — Agent Server

The sandbox package is the agent runtime of the Midsphere platform. It runs LLM agents on the [Exo framework](https://github.com/midsphere-ai/exo) inside an E2B sandbox and streams what they do over SSE.

The skill modules and project templates this server loads at run time are published with the standalone runtime at [sukuna-sandbox](https://github.com/midsphere-ai/sukuna-sandbox).

## Directory Structure

```
packages/sandbox/
├── agent_server/          # Django-based agent runtime
│   ├── prompts.py         # Prompt constants
│   ├── config.py          # Runtime config & vault integration
│   ├── auth.py            # Authentication backends
│   ├── server.py          # Re-exports of the routers and engine entry points
│   ├── models.py          # Django ORM models
│   ├── engine/            # Agent execution subsystem
│   │   ├── run.py         # Core _run_agent() function
│   │   ├── context.py     # Two-stage context reduction
│   │   ├── knowledge.py   # Vital info extraction
│   │   ├── harness.py     # Planner+executor orchestration
│   │   └── mcp.py         # MCP server offloading
│   ├── infra/             # Core infrastructure
│   │   ├── registry.py    # Tool & skill registries
│   │   ├── sync.py        # Backend sync service
│   │   ├── guards.py      # Security guardrails
│   │   ├── state.py       # Event bus, lease enforcement
│   │   └── ralph.py       # Ralph loop helpers
│   └── api/               # API endpoints
│       ├── runs.py        # Run management & SSE streaming
│       ├── handlers.py    # HITL & MCP endpoints
│       ├── files.py       # File operations & health
│       └── startup.py     # Server lifecycle
├── tools/                 # 15 unified agent tools
│   ├── file/              # File operations (package)
│   ├── perception/        # Media analysis (package)
│   ├── shell.py, search.py, plan.py, browse.py, ...
│   └── _lib/              # Shared utilities
├── tests/                 # Test suite
└── e2b/                   # Sandbox environment setup
```

## Development

### Running Locally

```bash
cd packages/sandbox
uv sync
LOCAL_MODE=1 uv run python -m agent_server    # starts on localhost:8000
```

`LOCAL_MODE=1` skips HashiCorp Vault and reads LLM provider config from `.env.local`.

### Running Tests

```bash
cd packages/sandbox
uv run pytest
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/runs` | POST | Start an agent run |
| `/runs/{run_id}` | GET | Get run status |
| `/runs/{run_id}/stream` | GET | SSE event stream (JWT auth) |
| `/health` | GET | Health check |

### Direct Stream Authentication

The direct stream endpoint uses short-lived JWTs minted by the backend:

- Supplied via query param `?token=<jwt>` or `Authorization: Bearer <jwt>`
- Required claims: `iss`, `aud`, `sub` (run_id), `conversation_id`, `user_id`, `scope` (`stream:read`), `exp`, `iat`, `jti`
- Optional lease fields: `max_runtime_seconds`, `max_total_tokens`, `max_cost_usd`

## Tool Registration

Tools are split into two categories:

**Native tools** are loaded directly into the agent's `tools=` parameter and execute in-process. These include file operations, shell, search, browse, match, plan, and skill. They are registered via the `ToolRegistry` in `agent_server/infra/registry.py`.

**CLI-offloaded tools** are invoked via `exo tool call <name>` in a subprocess, keeping the LLM's tool list compact and preserving KV cache efficiency. These include perception and reasoning. The offloaded tool catalog is defined in `tools/cli_tools.py` and built into markdown instructions at agent startup.

MCP servers configured per-conversation are offloaded via `exo-mcp tool call` using `mcp.json` configs managed by `agent_server/engine/mcp.py`.

## Backend Metering Callbacks

The agent server emits server-to-server callbacks through a durable outbox with retries and exponential backoff.

**Event types:** `run_started`, `run_usage` (periodic), `run_finished` / `run_failed` / `run_cancelled` (terminal).

**Callback signature:** Each request includes `X-Sukuna-Timestamp`, `X-Sukuna-Signature`, and `X-Sukuna-Event-Id`. Signature is `HMAC-SHA256(secret, "{timestamp}.{raw_body}")`.

## Lease Enforcement

Run-level resource limits are enforced from run metadata:

- `max_runtime_seconds` / `max_total_tokens` / `max_cost_usd`
- Exceeding a limit stops the run with an explicit error code: `lease_runtime_exceeded`, `lease_tokens_exceeded`, or `lease_cost_exceeded`

## PyArmor 9 Encryption

Production deployments protect source code via the build pipeline in `e2b/protection/protect.py`:

1. **`agent_server/`** is obfuscated with PyArmor 9 (`pyarmor gen -r -i`), replacing `.py` files with encrypted equivalents that require the PyArmor runtime to execute.
2. **`tools/`** is compiled to `.pyc` bytecode with thin `.py` stubs for entry points, allowing CLI-offloaded tool invocation while stripping source.
3. The protected output is packaged into the E2B sandbox Docker image (`e2b/Dockerfile`).
