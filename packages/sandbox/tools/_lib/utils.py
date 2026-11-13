"""Shared tool utilities — consistent result formatting."""

from __future__ import annotations

from typing import Any

# ── Standardised result helpers ────────────────────────────────────────────────


def success_result(message: str, **kwargs: Any) -> dict[str, Any]:
    """Return a consistent success dict from any MCP tool."""
    return {"success": True, "message": message, **kwargs}


def error_result(message: str, **kwargs: Any) -> dict[str, Any]:
    """Return a consistent error dict from any MCP tool."""
    return {"success": False, "message": message, **kwargs}


# ── Action alias resolution ──────────────────────────────────────────────────


def resolve_alias(value: str, aliases: dict[str, str]) -> tuple[str, str | None]:
    """Resolve a tool action/type alias to its canonical name.

    Returns ``(canonical_value, original_alias_or_None)``.  When *value*
    is already canonical the second element is ``None``.
    """
    canonical = aliases.get(value)
    if canonical is not None:
        return canonical, value
    return value, None


def alias_hint(
    result: dict[str, Any], alias_used: str | None, canonical: str, param_name: str = "action"
) -> dict[str, Any]:
    """If an alias was used, inject hint fields into the tool result dict."""
    if alias_used is not None:
        result["_alias_used"] = alias_used
        result["_canonical_action"] = canonical
        result["_alias_hint"] = (
            f"Note: '{alias_used}' is an alias for '{canonical}'. Use {param_name}='{canonical}' directly next time."
        )
    return result
