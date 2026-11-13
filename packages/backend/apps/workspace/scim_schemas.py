"""Request/response schemas for SCIM 2.0 provisioning endpoints (RFC 7644)."""

from datetime import datetime
from typing import Optional

from ninja import Schema

# ── SCIM User Schemas ─────────────────────────────────────────────────────


class SCIMName(Schema):
    """SCIM name sub-attribute."""

    givenName: Optional[str] = None
    familyName: Optional[str] = None


class SCIMMeta(Schema):
    """SCIM meta sub-attribute (RFC 7643 Section 3.1)."""

    resourceType: str = "User"
    created: Optional[datetime] = None
    lastModified: Optional[datetime] = None
    location: Optional[str] = None


class SCIMUserResource(Schema):
    """SCIM User resource (RFC 7643 Section 4.1)."""

    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    id: str
    userName: str
    name: Optional[SCIMName] = None
    active: bool = True
    meta: Optional[SCIMMeta] = None


class SCIMListResponse(Schema):
    """SCIM ListResponse (RFC 7644 Section 3.4.2)."""

    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:ListResponse"]
    totalResults: int
    startIndex: int = 1
    itemsPerPage: int = 100
    Resources: list[SCIMUserResource] = []


class SCIMError(Schema):
    """SCIM Error response (RFC 7644 Section 3.12)."""

    schemas: list[str] = ["urn:ietf:params:scim:api:messages:2.0:Error"]
    detail: str
    status: str


class CreateSCIMUserRequest(Schema):
    """Request body for SCIM POST /Users."""

    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    userName: str
    name: Optional[SCIMName] = None
    active: bool = True


class ReplaceSCIMUserRequest(Schema):
    """Request body for SCIM PUT /Users/{id} (full replace)."""

    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:User"]
    userName: str
    name: Optional[SCIMName] = None
    active: bool = True


class PatchOperation(Schema):
    """A single SCIM PATCH operation (RFC 7644 Section 3.5.2)."""

    op: str  # add, replace, remove
    path: Optional[str] = None
    value: Optional[dict | str | bool | list] = None


class PatchSCIMUserRequest(Schema):
    """Request body for SCIM PATCH /Users/{id}."""

    schemas: list[str] = ["urn:ietf:params:scim:schemas:core:2.0:PatchOp"]
    Operations: list[PatchOperation] = []
