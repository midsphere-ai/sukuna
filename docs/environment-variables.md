# Environment Variables Reference

Complete reference of every environment variable used across backend, frontend, sandbox agent server, and infrastructure.

> **Secret management:** In production, only `VAULT_ADDR` and `VAULT_TOKEN` are stored in `.env`. All other secrets are loaded at startup from OpenBao/Vault (`cubbyhole/root` path) via `config/openbao.py`.

---

## Table of Contents

- [Vault / OpenBao Bootstrap](#vault--openbao-bootstrap)
- [Django Backend](#django-backend)
  - [Core Django](#core-django)
  - [Database (PostgreSQL)](#database-postgresql)
  - [Redis & Celery](#redis--celery)
  - [CORS & Network](#cors--network)
  - [Email](#email)
  - [Payment Processing (Dodo Payments)](#payment-processing-dodo-payments)
  - [Agent & External APIs](#agent--external-apis)
  - [Sandbox Configuration](#sandbox-configuration)
  - [Stream Authentication (JWT)](#stream-authentication-jwt)
  - [Sandbox Leases](#sandbox-leases)
  - [Managed LLM Providers](#managed-llm-providers)
  - [Media Generation & Google Cloud](#media-generation--google-cloud)
  - [Production-Only](#production-only)
  - [DigitalOcean Spaces (Production)](#digitalocean-spaces-production)
  - [Sentry (Production)](#sentry-production)
  - [Mailgun (Production)](#mailgun-production)
  - [Local Development Overrides](#local-development-overrides)
- [Frontend (SvelteKit)](#frontend-sveltekit)
- [Sandbox Agent Server](#sandbox-agent-server)
  - [Server Configuration](#server-configuration)
  - [Agent Configuration](#agent-configuration)
  - [Event Persistence & Streaming](#event-persistence--streaming)
  - [Backend Metering & Callbacks](#backend-metering--callbacks)
  - [Tool-Specific Variables](#tool-specific-variables)
- [Infrastructure / Docker](#infrastructure--docker)
  - [Docker Compose Services](#docker-compose-services)
  - [Dockerfile Build-Time](#dockerfile-build-time)
  - [Gunicorn (Production Entrypoint)](#gunicorn-production-entrypoint)

---

## Vault / OpenBao Bootstrap

These are the only variables that need to exist in the `.env` file. Everything else is loaded from Vault at process startup (in `manage.py`, `config/celery.py`, `config/asgi.py`).

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VAULT_ADDR` | Yes | — | OpenBao/Vault server address (e.g. `https://vault.example.com:8200`) |
| `VAULT_TOKEN` | Yes | — | Authentication token for Vault |
| `VAULT_VERIFY_SSL` | No | `false` | Whether to verify TLS certificates on Vault connection |

**Source:** `config/openbao.py`, `.env`, `.env.example`

---

## Django Backend

All variables below use `django-environ` (`env()`) unless noted as `os.getenv()`.

### Core Django

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_READ_DOT_ENV_FILE` | No | `True` | Whether to read `.env` file on startup |
| `DJANGO_DEBUG` | No | `False` | Enable Django debug mode |
| `DJANGO_SECRET_KEY` | Prod only | Dev has hardcoded default | Django secret key for cryptographic signing |
| `DJANGO_ALLOWED_HOSTS` | Prod only | Production defaults | Comma-separated list of allowed hostnames |
| `DJANGO_ADMIN_URL` | Prod only | — | Django admin URL path (security through obscurity) |
| `DJANGO_ADMIN_FORCE_ALLAUTH` | No | `False` | Force admin login through django-allauth |
| `DJANGO_ACCOUNT_ALLOW_REGISTRATION` | No | `True` | Allow new user registration |

**Source:** `config/settings/base.py`, `config/settings/production.py`, `config/settings/local.py`

### Database (PostgreSQL)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_DB` | Yes | — | Database name |
| `POSTGRES_USER` | Yes | — | Database username |
| `POSTGRES_PASSWORD` | Yes | — | Database password |
| `POSTGRES_HOST` | Yes | — | Database host address |
| `POSTGRES_PORT` | Yes | — | Database port |

**Source:** `config/settings/base.py`

### Redis & Celery

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CELERY_REDIS_URL` | Yes | — | Redis URL for Celery broker |
| `REDIS_URL` | No | Falls back to `CELERY_REDIS_URL` | General Redis URL for caching |
| `ARQ_REDIS_URL` | No | Falls back to `REDIS_URL` | Redis URL for ARQ async task queue |

**Source:** `config/settings/base.py`

### CORS & Network

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CORS_ALLOWED_ORIGINS` | No | `[]` | Comma-separated CORS allowed origins |
| `CORS_ALLOW_CREDENTIALS` | No | `True` | Allow credentials in CORS requests |
| `CORS_ALLOW_ALL_ORIGINS` | No | `False` | Allow all origins (development only) |
| `NGROK_DOMAIN` | No | `""` | Ngrok tunnel domain, appended to CSRF trusted origins |

**Source:** `config/settings/base.py`, `config/settings/production.py`

### Email

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_EMAIL_BACKEND` | No | `django.core.mail.backends.smtp.EmailBackend` | Email backend class |
| `DJANGO_EMAIL_SUBJECT_PREFIX` | No | `"[sukuna] "` | Subject line prefix for emails |
| `DJANGO_DEFAULT_FROM_EMAIL` | No | `"no-reply@midsphere.ai"` | Default "From" address |
| `DJANGO_SERVER_EMAIL` | No | `"no-reply@midsphere.ai"` | Server error notification "From" address |

**Source:** `config/settings/base.py`, `config/settings/production.py`

### Payment Processing (Dodo Payments)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DODO_PAYMENTS_API_KEY` | Yes | — | Dodo Payments API key |
| `DODO_PAYMENTS_WEBHOOK_SECRET` | Yes | — | Dodo Payments webhook signature secret |
| `DODO_PAYMENTS_ENVIRONMENT` | No | — | Dodo Payments environment |
| `DODO_ADDON_PACK_PRODUCT_ID` | No | — | Product ID of the credit add-on pack |

**Source:** `config/settings/base.py`

### Agent & External APIs

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `COMPOSIO_KEY` | Yes | — | Composio API key for MCP addon generation |
| `AGENT_SERVER_API_KEY` | No | Falls back: `SUKUNA_AGENT_SERVER_API_KEY` → `API_KEY` → `"midsphere-internal"` | API key for authenticating with sandbox agent server |
| `SUKUNA_AGENT_SERVER_API_KEY` | No | — | Legacy agent server API key (first fallback) |
| `API_KEY` | No | `"midsphere-internal"` | Generic API key (final fallback) |
| `SERPER_API_KEY` | Yes | — | Serper API key for web search (serper.dev) |
| `JINA_API_KEY` | Yes | — | Jina API key for web scraping via Jina Reader |

**Source:** `config/settings/base.py`, `apps/agents/tasks.py`

### Sandbox Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SANDBOX_AGENT_SERVER_PORT` | No | `8000` | Port for agent server inside E2B sandbox |
| `SANDBOX_POOL_SIZE` | No | `2` | Number of prewarmed sandbox instances in pool |
| `SUKUNA_BACKEND_EVENTS_URL` | No | `""` | Backend webhook URL for sandbox event callbacks |
| `SUKUNA_BACKEND_EVENTS_SECRET` | No | `""` | HMAC secret for sandbox webhook authentication |
| `SANDBOX_CALLBACK_MAX_SKEW_SECONDS` | No | `300` | Max clock skew tolerance for sandbox callbacks (seconds) |
| `SKIP_DB_DDL` | No | `"true"` | Skip database DDL creation in sandbox environment (`os.getenv`) |

**Source:** `config/settings/base.py`, `apps/agents/models.py`

### Stream Authentication (JWT)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUKUNA_STREAM_JWT_SECRET` | No | Falls back to `SANDBOX_STREAM_JWT_SECRET`, then `""` | JWT secret for backend→sandbox streaming auth |
| `SANDBOX_STREAM_JWT_SECRET` | No | `""` | Legacy JWT secret (deprecated, use `SUKUNA_STREAM_JWT_SECRET`) |
| `SANDBOX_STREAM_JWT_ALGORITHM` | No | `"HS256"` | JWT signing algorithm |
| `SANDBOX_STREAM_JWT_ISSUER` | No | `"sukuna-backend"` | JWT issuer claim |
| `SANDBOX_STREAM_JWT_AUDIENCE` | No | `"sukuna-sandbox-stream"` | JWT audience claim |
| `SANDBOX_STREAM_JWT_TTL_SECONDS` | No | `120` | JWT token time-to-live (seconds) |
| `SANDBOX_DESKTOP_STREAM_TTL_SECONDS` | No | `120` | Desktop VNC stream TTL (seconds) |

**Source:** `config/settings/base.py`

### Sandbox Leases

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SANDBOX_LEASE_MAX_RUNTIME_SECONDS` | No | `0` (disabled) | Max runtime limit per sandbox lease |
| `SANDBOX_LEASE_MAX_TOTAL_TOKENS` | No | `0` (disabled) | Max token limit per sandbox lease |
| `SANDBOX_LEASE_MAX_COST_USD` | No | `0.0` (disabled) | Max cost limit per sandbox lease (USD) |

**Source:** `config/settings/base.py`

### Managed LLM Providers

Each agent role (super, reasoning, vision, audio, browser) has its own provider configuration. Roles other than "super" support a `*_USE_SAME_AS_SUPER` flag to inherit super's settings.

**Super Agent (primary):**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MANAGED_SUPER_LLM_PROVIDER` | No | `"openai"` | LLM provider name |
| `MANAGED_SUPER_LLM_MODEL` | No | `"gpt-4o"` | LLM model identifier |
| `MANAGED_SUPER_LLM_API_KEY` | Yes | — | LLM provider API key |
| `MANAGED_SUPER_LLM_BASE_URL` | Yes | — | LLM provider base URL |

**Reasoning Agent:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REASONING_USE_SAME_AS_SUPER` | No | `False` | Inherit super agent settings |
| `MANAGED_REASONING_LLM_PROVIDER` | No | `"openai"` | Provider (ignored if USE_SAME_AS_SUPER) |
| `MANAGED_REASONING_LLM_MODEL` | No | `"gpt-4o"` | Model |
| `MANAGED_REASONING_LLM_API_KEY` | Yes | — | API key |
| `MANAGED_REASONING_LLM_BASE_URL` | Yes | — | Base URL |

**Vision Agent:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VISION_USE_SAME_AS_SUPER` | No | `False` | Inherit super agent settings |
| `MANAGED_VISION_LLM_PROVIDER` | No | `"openai"` | Provider |
| `MANAGED_VISION_LLM_MODEL` | No | `"gpt-4o"` | Model |
| `MANAGED_VISION_LLM_API_KEY` | Yes | — | API key |
| `MANAGED_VISION_LLM_BASE_URL` | Yes | — | Base URL |

**Audio Agent:**

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AUDIO_USE_SAME_AS_SUPER` | No | `False` | Inherit super agent settings |
| `MANAGED_AUDIO_LLM_PROVIDER` | No | `"openai"` | Provider |
| `MANAGED_AUDIO_LLM_MODEL` | No | `"gpt-4o"` | Model |
| `MANAGED_AUDIO_LLM_API_KEY` | Yes | — | API key |
| `MANAGED_AUDIO_LLM_BASE_URL` | Yes | — | Base URL |

**Source:** `config/settings/base.py`

> **Note:** Browser Agent LLM settings (`MANAGED_BROWSER_LLM_*`, `BROWSER_USE_SAME_AS_SUPER`) were removed — browser tools now use Playwright MCP directly with no separate LLM.

### Media Generation & Google Cloud

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MANAGED_VIDEO_GENERATION_MODEL` | No | `"gpt-4o"` | Video generation model name |
| `MANAGED_IMAGE_GENERATION_MODEL` | No | `"gpt-4o"` | Image generation model name |
| `MANAGED_VERTEX_API_KEY` | Yes | — | Google Vertex AI API key |
| `MANAGED_GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `MANAGED_VERTEX_PROJECT_ID` | Yes | — | Google Cloud project ID for Vertex |
| `MANAGED_VERTEX_PROJECT_LOCATION` | Yes | — | Google Cloud region for Vertex |
| `GOOGLE_SERVICE_ACCOUNT_B64` | No | `""` | Base64-encoded Google service account JSON |

**Source:** `config/settings/base.py`

### Production-Only

#### Security

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DJANGO_SECURE_SSL_REDIRECT` | No | `True` | Force HTTPS redirect |
| `DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS` | No | `True` | Include subdomains in HSTS |
| `DJANGO_SECURE_HSTS_PRELOAD` | No | `True` | Enable HSTS preload |
| `DJANGO_SECURE_CONTENT_TYPE_NOSNIFF` | No | `True` | Set X-Content-Type-Options: nosniff |

**Source:** `config/settings/production.py`

### DigitalOcean Spaces (Production)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DO_SPACES_ACCESS_KEY` | Yes | — | DigitalOcean Spaces access key |
| `DO_SPACES_SECRET_KEY` | Yes | — | DigitalOcean Spaces secret key |
| `DO_SPACES_STATIC_BUCKET_NAME` | Yes | — | Bucket for static files |
| `DO_SPACES_MEDIA_BUCKET_NAME` | Yes | — | Bucket for media uploads |
| `DO_SPACES_REGION` | Yes | — | Region (e.g. `blr1`, `nyc3`) |
| `DO_SPACES_MEDIA_URL` | No | — | Media URL override |
| `DO_SPACES_CUSTOM_DOMAIN` | No | — | Custom CDN domain |
| `DJANGO_AWS_S3_MAX_MEMORY_SIZE` | No | `100000000` (100 MB) | Max in-memory size for S3 uploads |

**Source:** `config/settings/base.py`, `config/settings/production.py`

### Sentry (Production)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SENTRY_DSN` | Yes | — | Sentry error tracking DSN |
| `DJANGO_SENTRY_LOG_LEVEL` | No | `20` (INFO) | Minimum log level sent to Sentry |
| `SENTRY_ENVIRONMENT` | No | `"production"` | Environment label in Sentry |
| `SENTRY_TRACES_SAMPLE_RATE` | No | `0.0` | Sentry performance trace sampling rate (0.0–1.0) |

**Source:** `config/settings/production.py`

### Mailgun (Production)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MAILGUN_API_KEY` | Yes | — | Mailgun email service API key |

**Source:** `config/settings/production.py`

### Local Development Overrides

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `USE_DOCKER` | No | `"no"` | Set to `"yes"` when running inside Docker |
| `AGENT_SERVER_API_KEY` | No | `"midsphere-dev-key"` | Overridden dev API key |

**Source:** `config/settings/local.py`

---

## Frontend (SvelteKit)

All frontend variables use the `VITE_` prefix and are accessed via `import.meta.env`. They are embedded at build time.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_API_BASE_URL` | No | `""` (same origin) | Backend API base URL |
| `VITE_BACKEND_URL` | No | `"http://localhost:8000"` | Backend URL for Vite dev proxy (Node.js `process.env`, not client-side) |
| `VITE_GOOGLE_CLIENT_ID` | No | `""` | Google OAuth client ID for sign-in/sign-up |
| `VITE_SENTRY_DSN` | No | — | Sentry DSN; Sentry only initializes if set |
| `VITE_SENTRY_ENVIRONMENT` | No | `"development"` | Sentry environment label |
| `VITE_POSTHOG_KEY` | No | — | PostHog analytics API key; analytics only initializes if set |
| `VITE_POSTHOG_HOST` | No | `"https://us.i.posthog.com"` | PostHog API host |

**Built-in Vite variables also used:**
- `import.meta.env.DEV` — development mode flag (used in `DevStreamTransportBadge.svelte`)
- `process.env.CI` — CI detection in `playwright.config.ts`

**Source:** `packages/frontend/src/lib/api/client.ts`, `packages/frontend/src/lib/services/analytics.ts`, `packages/frontend/src/routes/(public)/login/+page.svelte`, `packages/frontend/src/routes/(public)/signup/+page.svelte`, `packages/frontend/vite.config.ts`

---

## Sandbox Agent Server

The agent server (`packages/sandbox/agent_server/`) is a Django Ninja application running inside E2B sandboxes.

### Server Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `PORT` | No | `8000` | Uvicorn listen port |
| `DATABASE_URL` | Yes | Falls back to `MIDSPHERE_DB_URL` | PostgreSQL connection string for SQLAlchemy |
| `MIDSPHERE_DB_URL` | No | — | Alternative database URL (set by Vault) |
| `SKIP_DB_DDL` | No | `"false"` | Skip database table creation on startup |
| `SUKUNA_SANDBOX_ID` | No | — | Self-identification sandbox ID |
| `MCP_SERVERS_JSON` | No | `"[]"` | JSON array of custom MCP server configs |

### Agent Configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_MODEL` | No | `"{super_provider}:{super_model}"` | LLM model in `provider:model` format |
| `AGENT_MAX_STEPS` | No | `50` | Maximum steps per agent run |
| `AGENT_INSTRUCTIONS` | No | Default system prompt | Agent system prompt |
| `AGENT_RUN_TIMEOUT_SECONDS` | No | `0` (unlimited) | Maximum runtime per execution |

### Event Persistence & Streaming

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EVENT_BATCH_SIZE` | No | `20` | Events batched before DB commit |
| `EVENT_BATCH_FLUSH_MS` | No | `100` | Forced batch flush interval (ms) |
| `RUN_EVENT_BUS_MAX_EVENTS` | No | `1000` | Max in-memory replay history per run |
| `RUN_START_MCP_PRELOAD_WAIT_SECONDS` | No | `1.5` | Wait time for MCP server preload |
| `RUN_STREAM_DB_CHUNK_SIZE` | No | `1000` | Chunk size for SSE replay from database |
| `RUN_STREAM_KEEPALIVE_SECONDS` | No | `10.0` | SSE keepalive ping interval |
| `SUKUNA_HITL_TIMEOUT_SECONDS` | No | `3600` | Human-in-the-loop response timeout (seconds) |

### Authentication

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUKUNA_AGENT_SERVER_API_KEY` | No | — | Preferred API key for `X-API-Key` header auth |
| `API_KEY` | No | — | Legacy API key fallback |
| `SUKUNA_STREAM_JWT_SECRET` | No | — | JWT secret for direct stream authentication |
| `SUKUNA_STREAM_JWT_ALGORITHM` | No | `"HS256"` | JWT algorithm |

### Backend Metering & Callbacks

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUKUNA_BACKEND_EVENTS_URL` | No | — | Webhook URL for metering/usage events |
| `SUKUNA_BACKEND_EVENTS_SECRET` | No | — | HMAC secret for webhook signatures |
| `SUKUNA_BACKEND_EVENTS_TIMEOUT_SECONDS` | No | `5` | Webhook request timeout |
| `SUKUNA_BACKEND_EVENTS_MAX_RETRIES` | No | `5` | Webhook retry attempts |
| `SUKUNA_BACKEND_EVENTS_BASE_BACKOFF_SECONDS` | No | `0.5` | Initial retry backoff |
| `SUKUNA_BACKEND_EVENTS_MAX_BACKOFF_SECONDS` | No | `30` | Maximum retry backoff |
| `SUKUNA_BACKEND_EVENTS_BATCH_SIZE` | No | `50` | Events per webhook batch |
| `SUKUNA_BACKEND_EVENTS_POLL_SECONDS` | No | `1.0` | Outbox poll interval |
| `SUKUNA_BACKEND_USAGE_FLUSH_SECONDS` | No | `5.0` | Usage data flush interval |
| `SUKUNA_BACKEND_USAGE_FLUSH_EVENTS` | No | `5` | Event count before usage flush |

### Tool-Specific Variables

These are set per-tool inside the sandbox. The agent server maps `MANAGED_*` Vault secrets to tool-specific env vars at startup.

**Workspace paths (shared across tools):**

| Variable | Default | Description |
|----------|---------|-------------|
| `SANDBOX_WORKSPACE_ROOT` | `"/home/user"` | Root workspace directory |
| `MIDSPHERE_WORKSPACE` | — | Workspace path used by download, vision, media_gen tools |
| `UPLOAD_DIR` | `"/tmp/workspace/uploads"` | Upload directory |
| `WORKSPACE` | `"./workspace"` | Working directory for web, mobile, search, media_gen tools |

**LLM configuration (per-tool, mapped from MANAGED_* vars):**

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_API_KEY` | — | LLM API key for the tool |
| `LLM_BASE_URL` | `""` | LLM base URL |
| `LLM_MODEL_NAME` | — | LLM model name |
| `LLM_MODEL_PROVIDER` | — | LLM provider (openai, azure_openai, gemini) |
| `LLM_MODEL_TEMPERATURE` | `0.7` (reasoning: `1.0`) | Model temperature |
| `LLM_MODEL_TRANSCRIPTION_NAME` | `"whisper-1"` | Audio transcription model |

**OpenAI-compatible (mapped from MANAGED_SUPER_*):**

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | Set from `MANAGED_SUPER_LLM_API_KEY` | OpenAI API key |
| `OPENAI_BASE_URL` | Set from `MANAGED_SUPER_LLM_BASE_URL` | OpenAI base URL |

**Azure OpenAI:**

| Variable | Default | Description |
|----------|---------|-------------|
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | — | Azure OpenAI endpoint |
| `AZURE_OPENAI_API_VERSION` | `"2024-12-01-preview"` | Azure API version |

**Google Cloud (mapped from MANAGED_* vars):**

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | Set from `MANAGED_GEMINI_API_KEY` | Gemini API key |
| `GOOGLE_CLOUD_PROJECT` | Set from `MANAGED_VERTEX_PROJECT_ID` | Google Cloud project ID |
| `GOOGLE_CLOUD_LOCATION` | Set from `MANAGED_VERTEX_PROJECT_LOCATION` | Google Cloud region |
| `GOOGLE_SERVICE_ACCOUNT_BASE64` | Set from `GOOGLE_SERVICE_ACCOUNT_B64` | Base64 service account JSON |

**Search & Browser tool:**

| Variable | Default | Description |
|----------|---------|-------------|
| `SERPER_API_KEY` | — | Serper API key for web/image/news/scholar search |
| `JINA_API_KEY` | — | Jina API key for Jina Reader web scraping |
| `CHROME_CDP_PORT` | `"9222"` | Chrome DevTools Protocol port |
| `COOKIES_FILE_PATH` | — | Browser cookies file path |
| `BROWSER_COOKIE_PATH` | Set from `COOKIES_FILE_PATH` | Browser cookies (alias) |

**Media generation tool:**

| Variable | Default | Description |
|----------|---------|-------------|
| `VIDEO_GENERATION_MODEL` | Set from `MANAGED_VIDEO_GENERATION_MODEL` | Video generation model |
| `IMAGE_GENERATION_MODEL` | Set from `MANAGED_IMAGE_GENERATION_MODEL` | Image generation model |
| `VERTEX_API_KEY` | Set from `MANAGED_VERTEX_API_KEY` | Vertex AI API key |
| `VERTEX_PROJECT_ID` | Set from `MANAGED_VERTEX_PROJECT_ID` | Vertex project ID |
| `VERTEX_PROJECT_LOCATION` | `"us-central1"` | Vertex region |

**Code tool:**

| Variable | Default | Description |
|----------|---------|-------------|
| `DEFAULT_TIMEOUT` | `1800` (30 min) | Shell/Python execution timeout (seconds) |

**Plan tool:**

| Variable | Default | Description |
|----------|---------|-------------|
| `CURRENT_SCHEDULED_TASKS_LENGTH` | `"0"` | Current number of scheduled tasks |
| `MAX_ALLOWED_SCHEDULED_TASKS` | `"10"` | Maximum allowed scheduled tasks |

**Slides tool:**

| Variable | Default | Description |
|----------|---------|-------------|
| `PRESENTATIONS_DIR` | `"/workspace/presentations"` | Presentation storage directory |
| `TEMPLATES_DIR` | `"/workspace/templates"` | Presentation template directory |

**Web/Mobile tools:**

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPLATE_BASE_PATH` | `"./templates"` | Web template base path |
| `MOBILE_TEMPLATE_PATH` | `"./templates"` | Mobile/Flutter template path |

**Source:** `packages/sandbox/agent_server/server.py`, `packages/sandbox/tools/*.py`

---

## Infrastructure / Docker

### Docker Compose Services

Variables set directly in docker-compose files (not from `.env`):

| Variable | Service | Local | Production | Description |
|----------|---------|-------|------------|-------------|
| `NODE_ENV` | web | `production` | `production` | Node.js environment |
| `PORT` | web | `3000` | `3000` | Frontend listen port |
| `ORIGIN` | web | `http://localhost` | `https://midsphere.ai` | SvelteKit origin URL |

Both compose files load `../packages/backend/.env` via `env_file` for Django, PostgreSQL, Redis, and Celery services.

**Source:** `infra/docker-compose.local.yml`, `infra/docker-compose.production.yml`

### Dockerfile Build-Time

| Variable | Dockerfile | Value | Description |
|----------|-----------|-------|-------------|
| `PYTHONUNBUFFERED` | django (local + prod) | `1` | Disable Python output buffering |
| `PYTHONDONTWRITEBYTECODE` | django (local + prod) | `1` | Don't write `.pyc` files |
| `BUILD_ENV` | django (prod) | `production` | Build environment flag |
| `UV_COMPILE_BYTECODE` | django (prod) | `1` | Compile bytecode with uv |
| `UV_LINK_MODE` | django (prod) | `copy` | uv package link mode |
| `UV_CACHE_DIR` | django (prod) | `/home/django/.cache/uv` | uv cache directory |
| `NODE_ENV` | frontend (local + prod) | `production` | Node.js environment |
| `PORT` | frontend (local + prod) | `3000` | Frontend port |

**Source:** `infra/compose/local/django/Dockerfile`, `infra/compose/production/django/Dockerfile`, `infra/compose/local/frontend/Dockerfile`, `infra/compose/production/frontend/Dockerfile`

### Gunicorn (Production Entrypoint)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GUNICORN_WORKERS` | No | `4` | Number of Gunicorn worker processes |
| `GUNICORN_TIMEOUT` | No | `120` | Worker timeout (seconds) |
| `DJANGO_SETTINGS_MODULE` | No | `"config.settings.production"` | Django settings module path |

**Source:** `infra/compose/production/django/start`, `infra/compose/production/django/entrypoint`

---

## Test-Only Variables

These are only used in test configuration and should not be set in production:

| Variable | Default | Description |
|----------|---------|-------------|
| `DJANGO_SETTINGS_MODULE` | `"config.settings.local"` | Django settings for test runs |
| `API_TEST_HOST` | `"localhost"` | API server host for integration tests |
| `API_TEST_PORT` | `"8000"` | API server port for integration tests |
| `AGENT_MODEL` | — | LLM model override in agent tests |
| `AGENT_MAX_STEPS` | — | Max steps override in agent tests |

**Source:** `apps/agents/tests/conftest.py`, `apps/agents/tests/test_models.py`
