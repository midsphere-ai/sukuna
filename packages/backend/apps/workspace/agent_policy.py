"""Org-level agent policy enforcement.

Provides tool group → individual tool mapping and functions to filter
blocked tools from the addons list sent to the sandbox, and to flag
tools requiring HITL approval.
"""

import logging

logger = logging.getLogger(__name__)

# Mapping of tool group names to the individual tool names they contain.
# These match the sandbox agent server's tool registry.
TOOL_GROUPS = {
    "file": ["read_file", "write_file", "list_files", "edit_file", "create_file"],
    "shell": ["shell", "run_command", "terminal"],
    "browse": ["browse", "web_browse", "browser"],
    "search": ["web_search", "search"],
    "media_gen": ["image_gen", "generate_image", "text_to_speech"],
    "git_ops": ["git", "git_commit", "git_push", "git_pull", "git_clone"],
    "perception": ["screenshot", "screen_capture", "vision"],
}


def _get_blocked_tool_names(policy) -> set[str]:
    """Expand blocked_tools and blocked_tool_groups into a flat set of tool names."""
    blocked = set(policy.blocked_tools or [])
    for group in policy.blocked_tool_groups or []:
        blocked.update(TOOL_GROUPS.get(group, []))
    return blocked


def get_org_agent_policy(conv):
    """Return the OrgAgentPolicy for a conversation's org, or None.

    Personal projects (no project or no org) return None.
    """
    project = getattr(conv, "project", None)
    if project is None:
        return None

    org = getattr(project, "organization", None)
    if org is None:
        return None

    from apps.workspace.models import OrgAgentPolicy

    try:
        return org.agent_policy
    except OrgAgentPolicy.DoesNotExist:
        return None


def filter_tools_for_policy(addons: list[str] | None, policy) -> list[str]:
    """Remove blocked tools from the addons list.

    Returns the filtered list. If addons is None/empty, returns empty list.
    """
    if not addons:
        return addons or []

    blocked = _get_blocked_tool_names(policy)
    if not blocked:
        return addons

    filtered = [t for t in addons if t not in blocked]
    removed = set(addons) - set(filtered)
    if removed:
        logger.info(
            "Agent policy removed tools %s for org %s",
            removed,
            policy.organization_id,
        )
    return filtered


def get_hitl_tools(policy) -> list[str]:
    """Return list of tool names that require HITL approval."""
    return list(policy.require_hitl_for or [])


def apply_agent_policy_to_metadata(metadata: dict, conv) -> dict:
    """Apply org agent policy to run metadata.

    Filters blocked tools from addons and injects require_approval flags
    for HITL tools. Returns the (possibly modified) metadata dict.
    Personal projects are never affected.
    """
    policy = get_org_agent_policy(conv)
    if policy is None:
        return metadata

    # Filter blocked tools from addons
    if "addons" in metadata:
        metadata["addons"] = filter_tools_for_policy(metadata["addons"], policy)

    # Inject HITL requirement
    hitl_tools = get_hitl_tools(policy)
    if hitl_tools:
        metadata["require_approval_tools"] = hitl_tools

    return metadata
