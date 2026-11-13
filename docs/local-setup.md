# Local Setup Guide

Run the full Midsphere stack locally with your own LLMs — no E2B cloud, no API keys required for the agent itself.

## Architecture

```
Frontend (SvelteKit :5173)
    |
Backend (Django :8001)     ← proxies runs/streams to agent server
    |
Agent Server (:8000)       ← runs agents with local LLM (Ollama, vLLM, etc.)
```

In **cloud mode** (default), the backend creates E2B sandboxes and boots the agent server inside them. In **local mode**, you run the agent server yourself and the backend proxies directly to it.

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Backend + Agent Server |
| uv | latest | Python package manager |
| Node.js | 20+ | Frontend |
| npm | 10+ | Frontend packages |
| PostgreSQL | 15+ | Backend database |
| An LLM provider | any | Ollama, vLLM, LM Studio, or a cloud API key |

### Install Ollama (recommended local LLM)

```bash
# Linux
curl -fsSL https://ollama.com/install.sh | sh

# macOS
brew install ollama

# Pull a model
ollama pull qwen3:32b    # or llama3.1:8b for lighter hardware
```

---

## Step 1: Agent Server

The agent server is the runtime that executes agents, manages tools, and streams events.

```bash
cd packages/sandbox
uv sync
```

Create your local config:

```bash
cp .env.local.example .env.local
```

Edit `.env.local` with your LLM provider:

```bash
LOCAL_MODE=1

# ── Ollama ────────────────────────────────────────
MANAGED_SUPER_LLM_PROVIDER=ollama
MANAGED_SUPER_LLM_MODEL=qwen3:32b
MANAGED_SUPER_LLM_BASE_URL=http://localhost:11434/v1
MANAGED_SUPER_LLM_API_KEY=ollama

# ── Or vLLM ──────────────────────────────────────
# MANAGED_SUPER_LLM_PROVIDER=openai
# MANAGED_SUPER_LLM_MODEL=Qwen/Qwen3-32B
# MANAGED_SUPER_LLM_BASE_URL=http://localhost:8001/v1
# MANAGED_SUPER_LLM_API_KEY=dummy

# ── Or cloud API (OpenAI, Anthropic, etc.) ───────
# MANAGED_SUPER_LLM_PROVIDER=anthropic
# MANAGED_SUPER_LLM_MODEL=claude-sonnet-4-20250514
# MANAGED_SUPER_LLM_API_KEY=sk-ant-...

PORT=8000
```

Start the agent server:

```bash
LOCAL_MODE=1 uv run python -m agent_server
```

Verify it's running:

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

### Using without the backend

You can use the agent server standalone via curl:

```bash
# Start a run
curl -X POST http://localhost:8000/runs \
  -H "Content-Type: application/json" \
  -d '{"task": "Write a Python hello world script", "conversation_id": "test-1"}'

# Stream events (use the run_id from above)
curl -N http://localhost:8000/runs/<run_id>/stream
```

---

## Step 2: Backend

The backend handles auth, conversations, billing, and proxies requests to the agent server.

```bash
cd packages/backend
uv sync
```

The backend loads its configuration from HashiCorp Vault (see `.env` for vault address/token). Make sure your vault credentials are set, then:

```bash
uv run python manage.py runserver 0.0.0.0:8001
```

### Database

The backend requires PostgreSQL. Vault provides the `DATABASE_URL`. If running locally, ensure your Postgres instance is accessible and the database exists.

```bash
# Apply migrations (if needed)
uv run python manage.py migrate
```

---

## Step 3: Frontend

```bash
cd packages/frontend
npm install
npm run dev
```

The dev server starts at `http://localhost:5173`. If the backend runs on a different host/port, set:

```bash
VITE_API_BASE_URL=http://localhost:8001 npm run dev
```

---

## Step 4: Enable Local Mode

Once all three processes are running:

1. Open the app at `http://localhost:5173`
2. Log in to your account
3. Open **Settings** (gear icon in sidebar)
4. Go to the **Advanced** tab
5. Toggle **Enable Local Mode**
6. Set **Agent Server URL** to `http://localhost:8000`
7. Start a conversation — the backend will proxy to your local agent server

The local agent server uses whatever LLM you configured in `.env.local`. No need to configure models in the Models tab — local mode bypasses BYOM overrides entirely.

---

## Environment Variables Reference

### Agent Server (.env.local)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LOCAL_MODE` | Yes | - | Set to `1` to skip vault |
| `MANAGED_SUPER_LLM_PROVIDER` | Yes | `openai` | LLM provider: `ollama`, `openai`, `anthropic`, `gemini`, `vertex` |
| `MANAGED_SUPER_LLM_MODEL` | Yes | - | Model name (e.g., `qwen3:32b`, `gpt-4o`) |
| `MANAGED_SUPER_LLM_BASE_URL` | For local LLMs | - | API endpoint (e.g., `http://localhost:11434/v1`) |
| `MANAGED_SUPER_LLM_API_KEY` | Yes | - | API key (use `ollama` for Ollama) |
| `PORT` | No | `8000` | Server port |
| `AGENT_MAX_STEPS` | No | `50` | Max tool-use steps per run |
| `AGENT_RUN_TIMEOUT_SECONDS` | No | disabled | Timeout per run in seconds |
| `DATABASE_URL` | No | SQLite in-memory | PostgreSQL URL for persistent history |

### Backend

The backend uses Vault for all configuration. The only env vars needed in `.env`:

| Variable | Required | Description |
|----------|----------|-------------|
| `VAULT_ADDR` | Yes | Vault server URL |
| `VAULT_TOKEN` | Yes | Vault auth token |
| `SANDBOX_POOL_SIZE` | No | Set to `0` to disable E2B pool replenishment |

---

## How It Works

When local mode is enabled for a user:

1. **Starting a run**: Backend detects `local_mode=True` in user settings, skips E2B sandbox creation, health-checks your local agent server, and POSTs the task directly. The `model` field is omitted — the agent server uses its own configured LLM.

2. **Streaming**: Backend proxies SSE from `http://localhost:8000/runs/{id}/stream` to the frontend, same as it does for E2B sandboxes.

3. **Follow-ups/inject**: Same proxy path, no E2B SDK calls.

4. **Tools**: All tools (file, shell, search, browse, git, etc.) run on your local machine. There is no sandbox isolation — be mindful of what you let agents do.

5. **Billing**: Skipped entirely in local mode.

6. **File uploads**: Skipped (files are already on your local machine — the agent's tools can access them directly).

---

## Supported LLM Providers

Any OpenAI-compatible API works. Tested configurations:

| Provider | PROVIDER value | BASE_URL | Notes |
|----------|---------------|----------|-------|
| Ollama | `ollama` | `http://localhost:11434/v1` | Best for local dev |
| vLLM | `openai` | `http://localhost:8000/v1` | Use a different port than agent server |
| LM Studio | `openai` | `http://localhost:1234/v1` | GUI-based |
| OpenAI | `openai` | (omit) | Requires real API key |
| Anthropic | `anthropic` | (omit) | Requires real API key |
| Google Gemini | `gemini` | (omit) | Requires real API key |

---

## Troubleshooting

**Agent server won't start without vault**
Ensure `LOCAL_MODE=1` is set. The env var must be present before the process starts — pass it inline or in `.env.local`.

**"Local agent server not reachable" when starting a chat**
Check the agent server is running on the URL you configured in Settings > Advanced. Verify with `curl http://localhost:8000/health`.

**Model errors / empty responses**
Confirm your LLM is running (`ollama list`, `curl http://localhost:11434/v1/models`). Check the model name matches exactly.

**Tools fail with permission errors**
Local mode runs tools on your actual machine with your user permissions. No sandboxing. Make sure working directories exist and are writable.

**SQLite "database is locked" errors**
The agent server defaults to SQLite in-memory (no persistence). For persistent conversation history, set `DATABASE_URL` to a PostgreSQL instance.

**Frontend can't connect to backend**
Set `VITE_API_BASE_URL=http://localhost:8001` when starting the frontend if the backend isn't on the default port.
