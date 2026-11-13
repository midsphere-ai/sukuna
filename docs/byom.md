# BYOM (Bring Your Own Model)

Feature implementation doc for user-configurable LLM providers.

## Overview

BYOM allows users on paid plans to configure their own LLM providers instead of using Midsphere's vault-managed defaults. Users can configure separate providers for:

| Tool Slot | What It Controls |
|-----------|------------------|
| `lead_agent` | The main agent model (exo Agent) |
| `vision` | Image/video analysis tools (`perception.py`) |
| `browser` | Web browsing/search tools (`search.py`) |
| `audio` | Audio transcription/processing tools (`perception.py`) |

## Architecture

```
                         HTTPS (private network)
Backend DB ──────────────> Sandbox /runs endpoint ──────────> _run_agent()
UserProviderConfig         metadata.user_preferences.         1. Lead agent: get_provider(**extras)
(Fernet-encrypted)         provider_overrides                 2. Tools: os.environ injection
                           (decrypted keys)                      → get_tool_env() picks up
```

### Data Flow

1. **User configures providers** via `POST /api/v1/byom/providers` — API key encrypted with Fernet, stored in `UserProviderConfig`
2. **User starts a run** — backend's `start_agent_run_background()` calls `_load_byom_overrides(user)`:
   - Checks `use_custom_llm` billing feature flag
   - Loads active `UserProviderConfig` rows
   - Decrypts API keys
   - Injects into `user_preferences.provider_overrides` in run metadata
   - Overrides `run_body["model"]` if `lead_agent` slot is configured
3. **Sandbox receives the run** — `start_run()` extracts `provider_overrides` from metadata, passes to `_run_agent()`
4. **`_run_agent()` applies overrides**:
   - **Lead agent**: `get_provider(model, api_key=..., base_url=..., **extras)` — extras are spread as kwargs (handles Vertex AI google_project, etc.)
   - **Tool slots**: Sets `MANAGED_*_LLM_*` env vars + provider-specific extras env vars + global API key env vars in `os.environ`
   - **Cleanup**: Restores all original env vars in `finally` block

### Provider Normalization

User-facing provider names don't always match what the system internally uses. Two mappings handle this:

**Lead agent model string** (`_EXO_PROVIDER_MAP` in `sandbox.py`):
The exo framework only knows `openai`, `anthropic`, `gemini`, `vertex`. OpenAI-compatible providers route through the `openai` exo provider with a custom `base_url`.

| User's `provider_name` | Exo model string prefix | Why |
|------------------------|------------------------|-----|
| `openai` | `openai` | Direct match |
| `anthropic` | `anthropic` | Direct match |
| `gemini` | `gemini` | Direct match |
| `vertex` | `vertex` | Direct match |
| `azure_openai` | `openai` | Azure uses OpenAI SDK with `base_url` |
| `openrouter` | `openai` | OpenAI-compatible, `base_url` routes to OpenRouter |
| `ollama` | `openai` | OpenAI-compatible, `base_url` routes to local Ollama |

**Tool env vars** (`_BYOM_TOOL_PROVIDER_MAP` in `server.py`):
Tool modules dispatch on the `MANAGED_*_LLM_PROVIDER` env var. Most tools understand `openai`/`anthropic`/`azure_openai`/`gemini`, but not `openrouter`/`ollama`/`vertex`.

| User's `provider_name` | Tool sees provider as | Why |
|------------------------|----------------------|-----|
| `openai` | `openai` | Direct match |
| `anthropic` | `anthropic` | Direct match |
| `gemini` | `gemini` | Direct match |
| `vertex` | `gemini` | perception.py only knows "gemini", not "vertex" |
| `azure_openai` | `azure_openai` | Tools handle Azure natively |
| `openrouter` | `openai` | Tools use OpenAI SDK with `OPENAI_BASE_URL` |
| `ollama` | `openai` | Tools use OpenAI SDK with `OPENAI_BASE_URL` |

**Global API key env vars**: For OpenAI-compatible providers, we also set `OPENAI_API_KEY` and `OPENAI_BASE_URL` because some tool code paths read those directly (e.g., `search.py` `get_llm()`). Similarly, `ANTHROPIC_API_KEY` is set for Anthropic, and `GEMINI_API_KEY` for Gemini/Vertex.

---

## API Endpoints

All endpoints require Bearer authentication and `use_custom_llm` billing feature.

Base path: `/api/v1/byom/`

### `GET /providers`

List all configured providers for the authenticated user.

**Response:** `200 OK`
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "tool_slot": "lead_agent",
    "provider_name": "openai",
    "model_name": "gpt-4o",
    "api_key_masked": "sk-p****Yz4w",
    "base_url": "",
    "extras": {},
    "is_active": true,
    "date_created": "2026-04-03T00:00:00+00:00",
    "date_updated": "2026-04-03T00:00:00+00:00"
  }
]
```

### `POST /providers`

Create or update (upsert by tool_slot) a provider config.

**Request:**
```json
{
  "tool_slot": "lead_agent",
  "provider_name": "openai",
  "model_name": "gpt-4o",
  "api_key": "sk-proj-...",
  "base_url": "",
  "extras": {}
}
```

**Response:** `201 Created` (new) or `200 OK` (updated) — same shape as GET response item.

**Validation errors:** `422` with message describing the invalid field.

### `DELETE /providers/{tool_slot}`

Remove a provider config for a slot.

**Response:** `200 OK`
```json
{
  "message": "Provider config deleted.",
  "tool_slot": "lead_agent"
}
```

**Not found:** `404` if no config exists for that slot.

### Error Responses

| Status | When |
|--------|------|
| `403` | User has no subscription or plan doesn't include `use_custom_llm` |
| `404` | DELETE on a slot that has no config |
| `422` | Invalid `tool_slot`, `provider_name`, empty `api_key`, or empty `model_name` |

---

## Supported Providers & Required Fields

Each provider requires different fields. The `api_key` and `model_name` fields are always required. Other fields depend on the provider:

### `openai`
Standard OpenAI API.
- **api_key**: OpenAI API key (`sk-...`)
- **model_name**: e.g. `gpt-4o`, `gpt-4o-mini`, `o1`
- **base_url**: Leave empty (default: `https://api.openai.com/v1`)
- **extras**: None needed

### `anthropic`
Anthropic Claude API.
- **api_key**: Anthropic API key (`sk-ant-...`)
- **model_name**: e.g. `claude-sonnet-4-20250514`, `claude-opus-4-20250514`
- **base_url**: Leave empty
- **extras**: None needed

### `gemini`
Google Gemini (public API, not Vertex).
- **api_key**: Google AI API key (`AIza...`)
- **model_name**: e.g. `gemini-2.0-flash`, `gemini-1.5-pro`
- **base_url**: Leave empty
- **extras**: `{"gemini_api_key": "<same key or separate>"}` — needed for tool slots that read `GEMINI_API_KEY`

### `vertex`
Google Vertex AI (GCP).
- **api_key**: Can be empty if using service account auth
- **model_name**: e.g. `gemini-2.5-pro`
- **base_url**: Leave empty
- **extras** (required):
  ```json
  {
    "google_project": "my-gcp-project",
    "google_location": "us-central1",
    "google_service_account_base64": "eyJ0eXBlIjoi..."
  }
  ```

### `azure_openai`
Azure-hosted OpenAI.
- **api_key**: Azure OpenAI API key
- **model_name**: The deployment name in Azure
- **base_url**: Azure endpoint URL (`https://your-resource.openai.azure.com`)
- **extras** (required):
  ```json
  {
    "azure_endpoint": "https://your-resource.openai.azure.com",
    "api_version": "2024-12-01-preview",
    "azure_deployment": "my-gpt4o-deployment"
  }
  ```

### `openrouter`
OpenRouter proxy (OpenAI-compatible).
- **api_key**: OpenRouter API key (`sk-or-...`)
- **model_name**: e.g. `openai/gpt-4o`, `anthropic/claude-3.5-sonnet`
- **base_url**: `https://openrouter.ai/api/v1`
- **extras**: None needed

### `ollama`
Local Ollama instance.
- **api_key**: Can be any non-empty string (e.g. `ollama`)
- **model_name**: e.g. `llama3`, `codellama`
- **base_url**: `http://localhost:11434/v1`
- **extras**: None needed

---

## Extras Field Reference

The `extras` JSON field stores provider-specific configuration. These keys are mapped to environment variables for tools, and passed as kwargs to `get_provider()` for the lead agent.

| Extras Key | Env Var Set | Used By | Description |
|-----------|-------------|---------|-------------|
| `azure_endpoint` | `AZURE_OPENAI_ENDPOINT` | Azure tools | Azure resource endpoint |
| `api_version` | `AZURE_OPENAI_API_VERSION` | Azure tools | Azure API version |
| `azure_deployment` | `AZURE_OPENAI_DEPLOYMENT_NAME` | Azure tools | Azure deployment name |
| `google_project` | `GOOGLE_CLOUD_PROJECT` | Vertex tools, lead agent | GCP project ID |
| `google_location` | `GOOGLE_CLOUD_LOCATION` | Vertex tools, lead agent | GCP region |
| `google_service_account_base64` | `GOOGLE_SERVICE_ACCOUNT_BASE64` | Vertex tools, lead agent | Base64-encoded service account JSON |
| `gemini_api_key` | `GEMINI_API_KEY` | Gemini tools | Gemini API key (if different from main api_key) |

---

## Billing

Gated by the `use_custom_llm` feature flag in `SubscriptionPlan.features`:

| Plan | `use_custom_llm` |
|------|-------------------|
| Free | `false` |
| Lite/Basic | `true` |
| Pro | `true` |

Checked at two layers:
1. **API layer**: CRUD endpoints return 403 if feature not available
2. **Run layer**: `_load_byom_overrides()` returns `None` if feature not available

---

## Frontend Implementation Guide

This section is for the agent implementing the UI. No frontend code exists yet — build it from scratch.

### Where to Add the UI

The BYOM settings should live in the **Settings** page, as a new tab/section alongside existing settings (appearance, profile, notifications, etc.). The `use_custom_llm` billing feature flag controls visibility.

### Recommended UX Flow

1. **Settings page** should show a "Custom Models" or "Bring Your Own Model" section
2. If user's plan doesn't include `use_custom_llm`, show an upgrade prompt instead of the form
3. Show a card/row for each **tool slot** (`lead_agent`, `vision`, `browser`, `audio`) with:
   - Current config status (configured/not configured)
   - Provider name + model name if configured
   - "Configure" / "Edit" / "Remove" actions
4. Clicking configure/edit opens a form with fields that adapt based on selected provider

### Form Fields by Provider

The form should dynamically show/hide fields based on the selected `provider_name`:

**Always shown:**
- Provider selector (dropdown of 7 providers)
- Model name (text input)
- API key (password input — show masked value from API, clear on edit)

**Conditionally shown:**

| Field | openai | anthropic | gemini | vertex | azure_openai | openrouter | ollama |
|-------|--------|-----------|--------|--------|--------------|------------|--------|
| Base URL | optional | optional | hidden | hidden | required | required | required |
| Azure Endpoint | | | | | required | | |
| Azure API Version | | | | | required | | |
| Azure Deployment | | | | | required | | |
| GCP Project | | | | required | | | |
| GCP Location | | | | required | | | |
| Service Account (base64) | | | | required | | | |

### How to Map Form Fields to API Payload

```typescript
// Example: building the POST /providers body from form state
const body = {
  tool_slot: selectedSlot,          // "lead_agent" | "vision" | "browser" | "audio"
  provider_name: selectedProvider,   // "openai" | "anthropic" | etc.
  model_name: modelName,
  api_key: apiKey,
  base_url: baseUrl || "",
  extras: {}
};

// Azure-specific extras
if (selectedProvider === "azure_openai") {
  body.extras = {
    azure_endpoint: azureEndpoint,
    api_version: apiVersion || "2024-12-01-preview",
    azure_deployment: azureDeployment
  };
}

// Vertex-specific extras
if (selectedProvider === "vertex") {
  body.extras = {
    google_project: gcpProject,
    google_location: gcpLocation || "us-central1",
    google_service_account_base64: serviceAccountBase64
  };
}

// Gemini — if user provides a separate Gemini API key for tools
if (selectedProvider === "gemini" && geminiApiKey) {
  body.extras = { gemini_api_key: geminiApiKey };
}
```

### Reading Current Config

Call `GET /api/v1/byom/providers` on page load. The response is an array — one item per configured slot. Empty array means nothing configured. Check `is_active` flag.

### Displaying the API Key

The API response includes `api_key_masked` (e.g., `sk-p****Yz4w`). Display this in the form when editing. The password field should be cleared when the user starts typing (the full key is never returned by the API).

### Tool Slot Labels for UI

| Slot Value | Display Label | Description for Users |
|-----------|---------------|----------------------|
| `lead_agent` | Main Agent | The primary AI model that powers your agent |
| `vision` | Vision & Image | Model used for analyzing images and videos |
| `browser` | Web Browsing | Model used for web browsing and search tasks |
| `audio` | Audio | Model used for audio transcription and processing |

### Billing Gate

Before rendering the BYOM section, check the user's subscription features. The billing API response includes `use_custom_llm` in the plan features. If `false`, show an upgrade CTA instead of the configuration form.

The existing billing plans page already displays `use_custom_llm` as "Custom LLM" in the feature comparison table (`packages/frontend/src/routes/(app)/billing/plans/+page.svelte:50`).

---

## Security

- **Encryption at rest**: API keys encrypted with Fernet symmetric encryption (`cryptography` package)
- **Encryption key**: `BYOM_ENCRYPTION_KEY` Django setting, loaded from vault
- **Decryption scope**: Keys decrypted only in `_load_byom_overrides()` when building run metadata
- **API responses**: Only masked keys returned (`sk-p****Yz4w`)
- **Transport**: Backend-to-sandbox over HTTPS within private network
- **No logging**: Provider overrides in run metadata are not logged at INFO level

## Database Model

`UserProviderConfig` in `apps.agents.models`:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `user` | FK(User) | Owner |
| `tool_slot` | CharField | `lead_agent`, `vision`, `browser`, `audio` |
| `provider_name` | CharField | Provider identifier |
| `model_name` | CharField | Model identifier |
| `api_key_encrypted` | BinaryField | Fernet-encrypted API key |
| `base_url` | URLField | Custom base URL (proxies, Azure endpoints) |
| `extras` | JSONField | Provider-specific config (see Extras Field Reference) |
| `is_active` | BooleanField | Soft disable without deleting |

Unique constraint: `(user, tool_slot)` — one config per slot per user.

## Fallback Behavior

When no BYOM config exists for a user (or their plan doesn't include `use_custom_llm`), the system falls back to vault-managed provider defaults — the same behavior as before this feature was added. No configuration changes are needed.

## Valid Values Reference

**tool_slot**: `lead_agent`, `vision`, `browser`, `audio`

**provider_name**: `openai`, `anthropic`, `gemini`, `vertex`, `azure_openai`, `openrouter`, `ollama`
