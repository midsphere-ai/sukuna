"""Django Ninja API views for developer API key management."""

import logging
from typing import List

from django.core.handlers.wsgi import WSGIRequest
from ninja import NinjaAPI
from ninja.errors import HttpError

from apps.users.adapters import NinjaAuthAdapter
from apps.users.models import DeveloperAPIKey
from apps.users.schemas import (
    APIKeyCreatedResponse,
    APIKeyDeletedResponse,
    APIKeySchema,
    APIKeyUpdatedResponse,
    CreateAPIKeyRequest,
    UpdateAPIKeyRequest,
)
from config.errors.handlers import register_error_handlers

logger = logging.getLogger(__name__)

developer_api = NinjaAPI(auth=NinjaAuthAdapter(), urls_namespace="developer")

register_error_handlers(developer_api)


@developer_api.post("/api-keys", response=APIKeyCreatedResponse)
def create_api_key(request: WSGIRequest, data: CreateAPIKeyRequest):
    """Create a new developer API key. The raw key is returned only once."""
    raw_key = DeveloperAPIKey.generate_key()
    key_hash = DeveloperAPIKey.hash_key(raw_key)
    prefix_len = len(DeveloperAPIKey.PREFIX) + 4
    key_prefix = raw_key[:prefix_len]

    api_key = DeveloperAPIKey.objects.create(
        name=data.name,
        key_hash=key_hash,
        key_prefix=key_prefix,
        user=request.auth,
        scopes=data.scopes,
        expires_at=data.expires_at,
    )

    return APIKeyCreatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key=raw_key,
        key_prefix=key_prefix,
        scopes=api_key.scopes,
        expires_at=api_key.expires_at,
        date_created=api_key.date_created,
    )


@developer_api.get("/api-keys", response=List[APIKeySchema])
def list_api_keys(request: WSGIRequest):
    """List all API keys for the authenticated user (masked, last 4 chars visible)."""
    keys = DeveloperAPIKey.objects.filter(user=request.auth)
    return [
        APIKeySchema(
            id=str(k.id),
            name=k.name,
            key_prefix=k.key_prefix,
            scopes=k.scopes,
            is_active=k.is_active,
            last_used_at=k.last_used_at,
            expires_at=k.expires_at,
            date_created=k.date_created,
            date_updated=k.date_updated,
        )
        for k in keys
    ]


@developer_api.delete("/api-keys/{key_id}", response=APIKeyDeletedResponse)
def revoke_api_key(request: WSGIRequest, key_id: str):
    """Revoke (deactivate) an API key."""
    try:
        api_key = DeveloperAPIKey.objects.get(id=key_id, user=request.auth)
    except DeveloperAPIKey.DoesNotExist:
        raise HttpError(404, "API key not found")

    api_key.is_active = False
    api_key.save(update_fields=["is_active", "date_updated"])

    return APIKeyDeletedResponse(message="API key revoked successfully")


@developer_api.patch("/api-keys/{key_id}", response=APIKeyUpdatedResponse)
def update_api_key(request: WSGIRequest, key_id: str, data: UpdateAPIKeyRequest):
    """Update an API key's name, scopes, or expiry."""
    try:
        api_key = DeveloperAPIKey.objects.get(id=key_id, user=request.auth)
    except DeveloperAPIKey.DoesNotExist:
        raise HttpError(404, "API key not found")

    update_fields = ["date_updated"]
    if data.name is not None:
        api_key.name = data.name
        update_fields.append("name")
    if data.scopes is not None:
        api_key.scopes = data.scopes
        update_fields.append("scopes")
    if data.expires_at is not None:
        api_key.expires_at = data.expires_at
        update_fields.append("expires_at")

    api_key.save(update_fields=update_fields)

    return APIKeyUpdatedResponse(
        id=str(api_key.id),
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        scopes=api_key.scopes,
        is_active=api_key.is_active,
        expires_at=api_key.expires_at,
        date_created=api_key.date_created,
        date_updated=api_key.date_updated,
    )
