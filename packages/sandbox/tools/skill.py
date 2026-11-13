"""Skill tool — discover and load reusable skill modules on demand."""

from __future__ import annotations

__version__ = "0.1.0"

import logging
import os
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool

logger = logging.getLogger(__name__)

# ── Skill directories (same constants as server.py) ──────────────────────────
_BUNDLED_SKILLS_DIR = str(Path(__file__).resolve().parent.parent / "skills")


def _workspace_root() -> str:
    return (
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(Path.home())
    )


_USER_SKILLS_DIR = os.path.join(_workspace_root(), "skills")

_SKILL_FILENAMES = {"skill.md", "SKILL.md"}


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter and return (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw_fm = text[3:end].strip()
    body = text[end + 4 :].strip()
    try:
        meta = yaml.safe_load(raw_fm) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, body


def _scan_skills() -> dict[str, dict[str, Any]]:
    """Scan bundled and user skill directories, returning {name: info}."""
    skills: dict[str, dict[str, Any]] = {}

    for source_dir in (_BUNDLED_SKILLS_DIR, _USER_SKILLS_DIR):
        root = Path(source_dir)
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            skill_file = None
            for fname in _SKILL_FILENAMES:
                candidate = child / fname
                if candidate.is_file():
                    skill_file = candidate
                    break
            if skill_file is None:
                continue
            try:
                text = skill_file.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, body = _parse_frontmatter(text)
            name = meta.get("name") or child.name
            active = str(meta.get("active", "true")).lower() == "true"
            if not active:
                continue
            # User skills override bundled (scanned second)
            skills[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "path": str(skill_file),
                "body": body,
            }

    return skills


_SKILL_ALIASES: dict[str, str] = {
    "list": "view",
    "ls": "view",
    "show": "view",
    "display": "view",
    "available": "view",
    "discover": "view",
    "browse": "view",
    "load": "get",
    "read": "get",
    "fetch": "get",
    "retrieve": "get",
    "use": "get",
    "obtain": "get",
}


@tool(name="skill")
def skill_tool(
    action: Annotated[
        Literal["view", "get"],
        "The action to perform. Supported values: view, get.",
    ],
    name: Annotated[
        str | None,
        "Skill name to load. Required for get action.",
    ] = None,
) -> dict:
    """Discover and load reusable skill modules for specialized tasks.

    <instructions>
    - Use `view` to discover what skills are available before attempting to load one.
    - Use `get` to load a skill's full instructions when you need specialized guidance for a task.
    - Skills provide domain-specific knowledge and best practices that improve task execution quality.
    - DO NOT guess skill names; always use `view` first to see available skills.
    - Loaded skill instructions should be followed carefully during the relevant phase of work.
    </instructions>

    <recommended_usage>
    - Use `view` to list all available skills at the start of a complex task.
    - Use `get` to load specialized instructions before entering a phase that requires domain expertise.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _SKILL_ALIASES)

    try:
        if action == "view":
            return alias_hint(_view_skills(), _alias, action)
        elif action == "get":
            return alias_hint(_get_skill(name), _alias, action)
        else:
            return error_result(
                f"Unknown action '{action}'.",
                hint="Valid actions: 'view', 'get'.",
            )
    except Exception as e:
        return error_result(f"Skill operation failed: {e}", hint="An unexpected error occurred while accessing skills.")


def _view_skills() -> dict:
    """List all available skills."""
    skills = _scan_skills()
    listing = [{"name": s["name"], "description": s["description"]} for s in skills.values()]
    return success_result(
        f"Found {len(listing)} available skill(s).",
        skills=listing,
    )


def _get_skill(name: str | None) -> dict:
    """Load a specific skill by name."""
    if not name or not name.strip():
        return error_result(
            "name is required for 'get' action.",
            hint="Use action='view' to see available skill names.",
        )
    skills = _scan_skills()
    skill = skills.get(name.strip())
    if skill is None:
        available = ", ".join(sorted(skills.keys()))
        return error_result(
            f"Skill '{name}' not found.",
            hint=f"Available skills: {available}",
        )
    return success_result(
        f"Loaded skill '{name}'.",
        name=skill["name"],
        body=skill["body"],
    )


SKILL_TOOLS = [skill_tool]
