"""BYOM (Bring Your Own Model) API — CRUD endpoints for user LLM provider configs.

Endpoints are gated by the ``use_custom_llm`` billing feature flag.

Routes (mounted at ``/api/v1/byom/``):
    GET    /providers              — list all provider configs (masked keys)
    POST   /providers              — create or update a provider config for a slot
    DELETE /providers/{tool_slot}   — remove a provider config for a slot
"""

import logging
from typing import Any, Dict, List

from ninja import NinjaAPI, Schema
from ninja.errors import HttpError

from apps.agents.models import UserProviderConfig
from apps.users.adapters import NinjaAuthAdapter
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

byom_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="byom")
register_error_handlers(byom_api)

# ── Allowed values ──────────────────────────────────────────────────────────

VALID_TOOL_SLOTS = {c.value for c in UserProviderConfig.ToolSlot}
VALID_PROVIDERS = {
    "openai",
    "anthropic",
    "azure_openai",
    "openrouter",
    "ollama",
}


# ── Schemas ─────────────────────────────────────────────────────────────────


class ProviderConfigInput(Schema):
    """Request body for creating / updating a provider config."""

    tool_slot: str
    provider_name: str
    model_name: str
    api_key: str
    base_url: str = ""
    extras: Dict[str, Any] = {}


class ProviderConfigResponse(Schema):
    """Response body for a single provider config (API key masked)."""

    id: str
    tool_slot: str
    provider_name: str
    model_name: str
    api_key_masked: str
    base_url: str
    extras: Dict[str, Any]
    is_active: bool
    date_created: str
    date_updated: str


class ProviderConfigDeleteResponse(Schema):
    """Response body for a delete operation."""

    message: str
    tool_slot: str


# ── Helpers ─────────────────────────────────────────────────────────────────


def _check_byom_permission(user) -> None:
    """Raise 403 if the user's subscription does not include ``use_custom_llm``."""
    from apps.billing.models import UserSubscription

    try:
        sub = UserSubscription.objects.select_related("plan").get(user=user)
    except UserSubscription.DoesNotExist:
        raise HttpError(
            403,
            "Custom LLM configuration requires an active subscription with this feature.",
        )

    if not sub.get_feature_info("use_custom_llm"):
        raise HttpError(
            403,
            "Custom LLM configuration is not available on your current plan.",
        )


def _config_to_response(cfg: UserProviderConfig) -> dict:
    """Serialize a ``UserProviderConfig`` to a response dict."""
    return {
        "id": str(cfg.id),
        "tool_slot": cfg.tool_slot,
        "provider_name": cfg.provider_name,
        "model_name": cfg.model_name,
        "api_key_masked": cfg.api_key_masked,
        "base_url": cfg.base_url,
        "extras": cfg.extras or {},
        "is_active": cfg.is_active,
        "date_created": cfg.date_created.isoformat(),
        "date_updated": cfg.date_updated.isoformat(),
    }


# ── Endpoints ───────────────────────────────────────────────────────────────


@byom_api.get("/providers", response=List[ProviderConfigResponse])
def list_providers(request):
    """List all BYOM provider configs for the authenticated user."""
    _check_byom_permission(request.auth)
    configs = UserProviderConfig.objects.filter(user=request.auth).order_by("tool_slot")
    return [_config_to_response(cfg) for cfg in configs]


@byom_api.post(
    "/providers", response={200: ProviderConfigResponse, 201: ProviderConfigResponse}
)
def upsert_provider(request, data: ProviderConfigInput):
    """Create or update a provider config for a tool slot (upsert by slot)."""
    _check_byom_permission(request.auth)

    # ── Validate inputs ──
    if data.tool_slot not in VALID_TOOL_SLOTS:
        raise HttpError(
            422,
            f"Invalid tool_slot '{data.tool_slot}'. Must be one of: {', '.join(sorted(VALID_TOOL_SLOTS))}",
        )
    if data.provider_name not in VALID_PROVIDERS:
        raise HttpError(
            422,
            f"Invalid provider_name '{data.provider_name}'. Must be one of: {', '.join(sorted(VALID_PROVIDERS))}",
        )
    if not data.api_key.strip():
        raise HttpError(422, "api_key must not be empty.")
    if not data.model_name.strip():
        raise HttpError(422, "model_name must not be empty.")

    # ── Upsert ──
    cfg, created = UserProviderConfig.objects.get_or_create(
        user=request.auth,
        tool_slot=data.tool_slot,
        defaults={
            "provider_name": data.provider_name,
            "model_name": data.model_name,
            "base_url": data.base_url,
            "extras": data.extras,
            "is_active": True,
        },
    )

    if not created:
        cfg.provider_name = data.provider_name
        cfg.model_name = data.model_name
        cfg.base_url = data.base_url
        cfg.extras = data.extras
        cfg.is_active = True

    # Always (re)encrypt the API key.
    cfg.set_api_key(data.api_key.strip())
    cfg.save()

    status = 201 if created else 200
    return status, _config_to_response(cfg)


@byom_api.delete("/providers/{tool_slot}", response=ProviderConfigDeleteResponse)
def delete_provider(request, tool_slot: str):
    """Remove a provider config for a tool slot."""
    _check_byom_permission(request.auth)

    if tool_slot not in VALID_TOOL_SLOTS:
        raise HttpError(
            422,
            f"Invalid tool_slot '{tool_slot}'. Must be one of: {', '.join(sorted(VALID_TOOL_SLOTS))}",
        )

    deleted_count, _ = UserProviderConfig.objects.filter(
        user=request.auth, tool_slot=tool_slot
    ).delete()

    if deleted_count == 0:
        raise HttpError(404, f"No provider config found for slot '{tool_slot}'.")

    return {"message": "Provider config deleted.", "tool_slot": tool_slot}
