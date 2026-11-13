"""Ninja/Pydantic schemas for UserCustomMCPConfig API serialization."""

from typing import Optional

from ninja.orm import ModelSchema
from pydantic import BaseModel

from apps.agents.models import (
    UserCustomMCPConfig,
)

# Schemas for UserCustomMCPConfig


class UserCustomMCPConfigSchema(ModelSchema):
    """Schema for returning UserCustomMCPConfig details."""

    class Meta:
        """Meta options binding this schema to UserCustomMCPConfig."""

        model = UserCustomMCPConfig
        fields = "__all__"


class UserCustomMCPConfigInputSchema(BaseModel):
    """Schema for creating or updating a UserCustomMCPConfig."""

    server_name: str
    command: Optional[str] = None
    arguments: Optional[str] = None
    env: Optional[str] = None
    description: Optional[str] = None
    server_type: Optional[str] = "stdio"
    url: Optional[str] = None
    timeout: Optional[int] = None
    sse_read_timeout: Optional[int] = None
    client_session_timeout_seconds: Optional[float] = None


class MCPConfigResultSchema(BaseModel):
    """Result schema for MCP config operations."""

    id: str


class MCPConfigDeletionResultSchema(BaseModel):
    """Result schema for MCP config deletion operations."""

    id: str
    deleted: bool
