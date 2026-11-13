"""
Standardised API Success Response Patterns
==========================================

Every endpoint MUST use one of these three response patterns:

1. **Single Object** — returns a typed schema directly::

       @api.get("/items/{id}", response=ItemSchema)

2. **List (Paginated)** — paginated list of typed schemas::

       @api.get("/items", response=List[ItemSchema])
       @paginate(PageNumberPagination)

   Django Ninja pagination returns::

       {"items": [...], "count": 123}

3. **Action Result** — simple action confirmation::

       @api.post("/items/{id}/archive", response=ActionResponse)

   Returns ``{"message": "Item archived"}`` (subclass to add extra fields).

All error responses use ``ErrorResponseSchema`` from ``config.errors.handlers``.

Proxy endpoints that forward opaque JSON from external services (e.g. sandbox
agent server) may use ``response={200: dict, ...}`` — document why in a comment.
"""

from __future__ import annotations

from typing import Optional

from ninja import Schema


class ActionResponse(Schema):
    """Standard response for actions that don't return a domain object.

    Use this (or a subclass) for create/update/delete confirmations, toggles,
    and any endpoint whose primary output is "it worked" + a human message.
    """

    message: str


class DeleteActionResponse(ActionResponse):
    """Standard response for delete operations."""

    deleted_count: Optional[int] = None
