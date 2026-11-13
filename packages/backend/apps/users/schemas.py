"""Schemas for the Developer API key management endpoints."""

from datetime import datetime
from typing import List, Optional

from ninja import Schema


class CreateAPIKeyRequest(Schema):
    """Request body for creating a new developer API key."""

    name: str
    scopes: List[str] = []
    expires_at: Optional[datetime] = None


class UpdateAPIKeyRequest(Schema):
    """Request body for updating a developer API key."""

    name: Optional[str] = None
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class APIKeyCreatedResponse(Schema):
    """Response returned when an API key is created (includes raw key once)."""

    id: str
    name: str
    key: str
    key_prefix: str
    scopes: List[str]
    expires_at: Optional[datetime] = None
    date_created: datetime


class APIKeySchema(Schema):
    """Schema for listing API keys (masked, no raw key)."""

    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    date_created: datetime
    date_updated: datetime


class APIKeyDeletedResponse(Schema):
    """Response returned when an API key is revoked."""

    message: str


class APIKeyUpdatedResponse(Schema):
    """Response returned when an API key is updated."""

    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    expires_at: Optional[datetime] = None
    date_created: datetime
    date_updated: datetime
