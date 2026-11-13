"""Toolkit resolver — port of the backend's skill/addon/MCP resolution chain.

Given a run's ``{user_id, project_id, skill_ids, addons}`` + the project's
``isolated_toolkit`` flag, this module materializes the merged toolkit the
sandbox will hand the agent: installed skills (marketplace + authored),
project skills, project MCP configs, and addon credit tiers.

Ported from ``packages/backend/apps/agents/sandbox.py`` so the sandbox can
own the full run lifecycle end-to-end without the backend fetching toolkit
state on its behalf.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async

log = logging.getLogger("agent_server.toolkit")


# ── Tool group → tool name map (mirrors apps/workspace/agent_policy.py) ──────

TOOL_GROUPS: dict[str, list[str]] = {
    "file": ["read_file", "write_file", "list_files", "edit_file", "create_file"],
    "shell": ["shell", "run_command", "terminal"],
    "browse": ["browse", "web_browse", "browser"],
    "search": ["web_search", "search"],
    "media_gen": ["image_gen", "generate_image", "text_to_speech"],
    "git_ops": ["git", "git_commit", "git_push", "git_pull", "git_clone"],
    "perception": ["screenshot", "screen_capture", "vision"],
}


# ── Skill fetchers ───────────────────────────────────────────────────────────


async def _get_installed_skills_for_user(user_id: int) -> list[dict[str, Any]]:
    """Fetch a user's installed marketplace skills.

    Returns dicts shaped like {slug, source_repo, source_path, skill_md_content, skill_files}
    — identical to the backend's ``_get_installed_skills_for_user``.
    """
    from agent_server.models import DjangoUserInstalledSkill

    rows = await sync_to_async(
        lambda: list(
            DjangoUserInstalledSkill.objects.filter(user_id=user_id)
            .select_related("skill")
            .values_list(
                "skill__slug",
                "skill__source_repo",
                "skill__source_path",
                "skill__skill_md_content",
                "skill__skill_files",
            )
        ),
        thread_sensitive=False,
    )()
    return [
        {
            "slug": slug or "",
            "source_repo": source_repo or "",
            "source_path": source_path or "",
            "skill_md_content": content or "",
            "skill_files": skill_files or {},
        }
        for slug, source_repo, source_path, content, skill_files in rows
    ]


async def _get_authored_skills_for_user(user_id: int) -> list[dict[str, Any]]:
    """Fetch a user's own authored skills (shaped identically to installed)."""
    from agent_server.models import DjangoUserSkill

    rows = await sync_to_async(
        lambda: list(
            DjangoUserSkill.objects.filter(owner_id=user_id).values_list(
                "slug",
                "skill_md_content",
                "skill_files",
                "source_url",
            )
        ),
        thread_sensitive=False,
    )()
    return [
        {
            "slug": slug or "",
            "source_repo": source_url or f"user:{user_id}",
            "source_path": "",
            "skill_md_content": content or "",
            "skill_files": skill_files or {},
        }
        for slug, content, skill_files, source_url in rows
    ]


def _union_authored_over_installed(
    installed: list[dict[str, Any]],
    authored: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Union authored skills onto marketplace-installed skills, authored wins on slug conflict."""
    if not authored:
        return installed
    authored_slugs = {s["slug"] for s in authored}
    return list(authored) + [s for s in installed if s["slug"] not in authored_slugs]


async def _get_project_skills(project_id: str) -> list[dict[str, Any]]:
    """Fetch project-scoped installed skills (same shape as user-installed)."""
    from agent_server.models import DjangoProjectSkill

    rows = await sync_to_async(
        lambda: list(
            DjangoProjectSkill.objects.filter(project_id=project_id)
            .select_related("skill")
            .values_list(
                "skill__slug",
                "skill__source_repo",
                "skill__source_path",
                "skill__skill_md_content",
                "skill__skill_files",
            )
        ),
        thread_sensitive=False,
    )()
    return [
        {
            "slug": slug or "",
            "source_repo": source_repo or "",
            "source_path": source_path or "",
            "skill_md_content": content or "",
            "skill_files": skill_files or {},
        }
        for slug, source_repo, source_path, content, skill_files in rows
    ]


async def _get_project_mcp_configs(project_id: str) -> list[dict[str, Any]]:
    """Fetch project-scoped MCP server configurations."""
    from agent_server.models import DjangoProjectMCPConfig

    rows = await sync_to_async(
        lambda: list(
            DjangoProjectMCPConfig.objects.filter(project_id=project_id).values(
                "id",
                "server_name",
                "server_type",
                "command",
                "arguments",
                "env",
                "url",
                "timeout",
                "sse_read_timeout",
                "client_session_timeout_seconds",
                "description",
            )
        ),
        thread_sensitive=False,
    )()
    return [
        {
            "id": str(row["id"]),
            "server_name": row["server_name"],
            "server_type": row["server_type"],
            "command": row["command"] or "",
            "arguments": row["arguments"] or "",
            "env": row["env"] or "",
            "url": row["url"] or "",
            "timeout": row["timeout"],
            "sse_read_timeout": row["sse_read_timeout"],
            "client_session_timeout_seconds": row["client_session_timeout_seconds"],
            "description": row["description"] or "",
        }
        for row in rows
    ]


async def _get_project_addon_ids(project_id: str) -> list[str]:
    """Fetch project-scoped addon IDs (UserMarketplaceAddons PKs)."""
    from agent_server.models import DjangoProjectAddon

    rows = await sync_to_async(
        lambda: list(DjangoProjectAddon.objects.filter(project_id=project_id).values_list("addon__id", flat=True)),
        thread_sensitive=False,
    )()
    return [str(pk) for pk in rows]


async def _get_project_isolated_flag(project_id: str) -> bool:
    """Return the project's ``isolated_toolkit`` flag (False if project missing)."""
    from agent_server.models import DjangoProject

    val = await sync_to_async(
        lambda: DjangoProject.objects.filter(id=project_id).values_list("isolated_toolkit", flat=True).first(),
        thread_sensitive=False,
    )()
    return bool(val)


def _filter_skills_by_slugs(skills: list[dict[str, Any]], selected: list[str] | None) -> list[dict[str, Any]]:
    """Keep only skills whose slug appears in ``selected``. Empty/None = all."""
    if not selected:
        return skills
    allow = set(selected)
    return [s for s in skills if s.get("slug") in allow]


def _merge_toolkits(
    *,
    user_skills: list[dict[str, Any]],
    project_skills: list[dict[str, Any]],
    user_addon_ids: list[str],
    project_addon_ids: list[str],
    project_mcp_configs: list[dict[str, Any]],
    isolated: bool,
) -> dict[str, Any]:
    """Merge user-level and project-level toolkit.

    When ``isolated`` is True, only project toolkit is used.  Otherwise,
    project items take precedence on slug/addon-id conflicts.
    """
    if isolated:
        return {
            "installed_skills": project_skills,
            "addon_ids": project_addon_ids,
            "project_mcp_configs": project_mcp_configs,
        }

    seen_slugs = {s["slug"] for s in project_skills}
    merged_skills = list(project_skills) + [s for s in user_skills if s["slug"] not in seen_slugs]

    seen_addon_ids = set(project_addon_ids)
    merged_addon_ids = list(project_addon_ids) + [a for a in user_addon_ids if a not in seen_addon_ids]

    return {
        "installed_skills": merged_skills,
        "addon_ids": merged_addon_ids,
        "project_mcp_configs": project_mcp_configs,
    }


async def _resolve_addon_credit_tiers(addon_ids: list[str]) -> dict[str, str]:
    """Resolve addon IDs → ``{addon_name_lower: credit_tier}`` for sandbox billing."""
    if not addon_ids:
        return {}
    from agent_server.models import DjangoUserMarketplaceAddons

    rows = await sync_to_async(
        lambda: list(
            DjangoUserMarketplaceAddons.objects.filter(id__in=addon_ids)
            .select_related("enabled_addon")
            .values_list("enabled_addon__name", "enabled_addon__credit_tier")
        ),
        thread_sensitive=False,
    )()
    return {name.lower(): tier for name, tier in rows if name}


# ── Agent policy (blocked tools + HITL requirements per org) ─────────────────


def _get_blocked_tool_names(blocked_tools: list[str], blocked_tool_groups: list[str]) -> set[str]:
    """Expand ``blocked_tools`` + ``blocked_tool_groups`` into one flat set."""
    blocked = set(blocked_tools or [])
    for group in blocked_tool_groups or []:
        blocked.update(TOOL_GROUPS.get(group, []))
    return blocked


async def _load_org_agent_policy(
    organization_id: str,
) -> dict[str, list[str]] | None:
    """Load the org's ``OrgAgentPolicy`` as raw lists, or None if absent."""
    from agent_server.models import DjangoOrgAgentPolicy

    row = await sync_to_async(
        lambda: DjangoOrgAgentPolicy.objects.filter(organization_id=organization_id)
        .values("blocked_tools", "blocked_tool_groups", "require_hitl_for")
        .first(),
        thread_sensitive=False,
    )()
    return row  # None if no policy row


async def apply_agent_policy_to_metadata(
    metadata: dict[str, Any],
    *,
    project_id: str | None,
) -> dict[str, Any]:
    """Apply org agent policy to run metadata.

    Filters blocked tools from ``metadata["addons"]`` and injects
    ``metadata["require_approval_tools"]`` for HITL tools.  Personal
    (non-org) projects are unaffected.
    """
    if not project_id:
        return metadata

    from agent_server.models import DjangoProject

    organization_id = await sync_to_async(
        lambda: DjangoProject.objects.filter(id=project_id).values_list("organization_id", flat=True).first(),
        thread_sensitive=False,
    )()
    if not organization_id:
        return metadata

    policy = await _load_org_agent_policy(str(organization_id))
    if policy is None:
        return metadata

    addons = metadata.get("addons")
    if addons:
        blocked = _get_blocked_tool_names(
            policy.get("blocked_tools") or [],
            policy.get("blocked_tool_groups") or [],
        )
        if blocked:
            filtered = [t for t in addons if t not in blocked]
            removed = set(addons) - set(filtered)
            if removed:
                log.info(
                    "Agent policy removed tools %s for org %s",
                    removed,
                    organization_id,
                )
            metadata["addons"] = filtered

    hitl_tools = list(policy.get("require_hitl_for") or [])
    if hitl_tools:
        metadata["require_approval_tools"] = hitl_tools

    return metadata


# ── Top-level resolver ───────────────────────────────────────────────────────


async def resolve_toolkit_for_run(
    *,
    user_id: int | None,
    project_id: str | None,
    selected_skill_slugs: list[str] | None,
    user_addon_ids: list[str] | None,
) -> dict[str, Any]:
    """Resolve the merged toolkit for a run.

    Returns::

        {
            "installed_skills": list[dict],       # slug/source_repo/source_path/skill_md_content/skill_files
            "addon_ids": list[str],               # merged user+project addon PKs
            "project_mcp_configs": list[dict],    # project-scoped MCP server configs
            "addon_credit_tiers": dict[str, str], # addon_name_lower → credit_tier
        }

    Mirrors the resolution order in the backend's ``start_run_directly``:
    1. Union authored skills over marketplace-installed for the user.
    2. Filter by ``selected_skill_slugs`` if provided (both user + project).
    3. If the project has ``isolated_toolkit=True``, drop user items entirely.
    4. Otherwise, project items take precedence on slug/addon-id conflicts.
    """
    user_skills: list[dict[str, Any]] = []
    if user_id is not None:
        installed = await _get_installed_skills_for_user(user_id)
        authored = await _get_authored_skills_for_user(user_id)
        user_skills = _union_authored_over_installed(installed, authored)

    user_skills = _filter_skills_by_slugs(user_skills, selected_skill_slugs)

    project_skills: list[dict[str, Any]] = []
    project_mcp_configs: list[dict[str, Any]] = []
    project_addon_ids: list[str] = []
    isolated = False
    if project_id:
        project_skills = await _get_project_skills(project_id)
        project_skills = _filter_skills_by_slugs(project_skills, selected_skill_slugs)
        project_mcp_configs = await _get_project_mcp_configs(project_id)
        project_addon_ids = await _get_project_addon_ids(project_id)
        isolated = await _get_project_isolated_flag(project_id)

    merged = _merge_toolkits(
        user_skills=user_skills,
        project_skills=project_skills,
        user_addon_ids=list(user_addon_ids or []),
        project_addon_ids=project_addon_ids,
        project_mcp_configs=project_mcp_configs,
        isolated=isolated,
    )

    addon_credit_tiers = await _resolve_addon_credit_tiers(merged["addon_ids"])
    merged["addon_credit_tiers"] = addon_credit_tiers
    return merged
