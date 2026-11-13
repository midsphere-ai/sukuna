"""Unit tests for the sandbox-side toolkit resolver (``agent_server.infra.toolkit``).

Covers:
- ``_union_authored_over_installed`` — authored wins on slug conflict, empty cases.
- ``_filter_skills_by_slugs`` — None/empty selection = all, slug allowlist.
- ``_merge_toolkits`` — isolated vs non-isolated, project-over-user precedence.
- ``_get_blocked_tool_names`` — individual tools + expanded tool groups.
- ``resolve_toolkit_for_run`` — orchestrates the fetch + merge (DB mocked).
- ``apply_agent_policy_to_metadata`` — blocked-tool filter + HITL flag injection
  for org projects; no-op for personal projects.

The shadow ORMs (UserInstalledSkill, UserSkill, ProjectSkill, ProjectAddon,
ProjectMCPConfig, UserMarketplaceAddons, OrgAgentPolicy, Project) are
managed=False, so we avoid requiring backend migrations in the test DB by
patching the module's async fetchers directly.  The pure-Python helpers are
exercised with real dicts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agent_server.infra import toolkit

# ═════════════════════════════════════════════════════════════════════════════
# Pure-Python helpers
# ═════════════════════════════════════════════════════════════════════════════


def test_union_authored_over_installed_authored_wins_on_slug_conflict() -> None:
    installed = [
        {"slug": "tdd", "skill_md_content": "market", "source_repo": "m", "source_path": "", "skill_files": {}},
        {"slug": "ralph", "skill_md_content": "market", "source_repo": "m", "source_path": "", "skill_files": {}},
    ]
    authored = [
        {"slug": "tdd", "skill_md_content": "mine", "source_repo": "u", "source_path": "", "skill_files": {}},
    ]
    merged = toolkit._union_authored_over_installed(installed, authored)
    # Authored "tdd" replaces marketplace "tdd"; marketplace "ralph" survives.
    assert [s["slug"] for s in merged] == ["tdd", "ralph"]
    tdd = next(s for s in merged if s["slug"] == "tdd")
    assert tdd["skill_md_content"] == "mine"


def test_union_authored_over_installed_empty_authored_returns_installed() -> None:
    installed = [{"slug": "only", "skill_md_content": "x", "source_repo": "", "source_path": "", "skill_files": {}}]
    assert toolkit._union_authored_over_installed(installed, []) is installed


def test_filter_skills_by_slugs_empty_selection_is_all() -> None:
    skills = [{"slug": "a"}, {"slug": "b"}]
    assert toolkit._filter_skills_by_slugs(skills, None) == skills
    assert toolkit._filter_skills_by_slugs(skills, []) == skills


def test_filter_skills_by_slugs_keeps_only_listed_slugs() -> None:
    skills = [{"slug": "a"}, {"slug": "b"}, {"slug": "c"}]
    assert [s["slug"] for s in toolkit._filter_skills_by_slugs(skills, ["a", "c"])] == ["a", "c"]


def test_merge_toolkits_isolated_drops_user_items() -> None:
    merged = toolkit._merge_toolkits(
        user_skills=[
            {"slug": "user-only", "skill_md_content": "", "source_repo": "", "source_path": "", "skill_files": {}}
        ],
        project_skills=[
            {"slug": "proj", "skill_md_content": "", "source_repo": "", "source_path": "", "skill_files": {}}
        ],
        user_addon_ids=["u1"],
        project_addon_ids=["p1"],
        project_mcp_configs=[{"server_name": "pm", "id": "x"}],
        isolated=True,
    )
    assert [s["slug"] for s in merged["installed_skills"]] == ["proj"]
    assert merged["addon_ids"] == ["p1"]
    assert merged["project_mcp_configs"] == [{"server_name": "pm", "id": "x"}]


def test_merge_toolkits_non_isolated_project_wins_on_slug_conflict() -> None:
    merged = toolkit._merge_toolkits(
        user_skills=[
            {"slug": "shared", "skill_md_content": "u", "source_repo": "", "source_path": "", "skill_files": {}},
            {"slug": "user-only", "skill_md_content": "u", "source_repo": "", "source_path": "", "skill_files": {}},
        ],
        project_skills=[
            {"slug": "shared", "skill_md_content": "p", "source_repo": "", "source_path": "", "skill_files": {}},
        ],
        user_addon_ids=["a1", "a2"],
        project_addon_ids=["a2", "a3"],  # a2 duplicated — should appear once
        project_mcp_configs=[],
        isolated=False,
    )
    slugs = [s["slug"] for s in merged["installed_skills"]]
    assert slugs == ["shared", "user-only"]
    # Project's version of "shared" wins on precedence.
    shared = next(s for s in merged["installed_skills"] if s["slug"] == "shared")
    assert shared["skill_md_content"] == "p"
    # Addon IDs: project first, user's a1 appended, a2 not duplicated.
    assert merged["addon_ids"] == ["a2", "a3", "a1"]


def test_get_blocked_tool_names_expands_groups() -> None:
    blocked = toolkit._get_blocked_tool_names(["custom_tool"], ["shell", "browse"])
    assert "custom_tool" in blocked
    for name in toolkit.TOOL_GROUPS["shell"]:
        assert name in blocked
    for name in toolkit.TOOL_GROUPS["browse"]:
        assert name in blocked


def test_get_blocked_tool_names_unknown_group_is_ignored() -> None:
    blocked = toolkit._get_blocked_tool_names([], ["not_a_real_group"])
    assert blocked == set()


# ═════════════════════════════════════════════════════════════════════════════
# resolve_toolkit_for_run (DB calls mocked)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_resolve_toolkit_no_user_no_project_returns_empty() -> None:
    merged = await toolkit.resolve_toolkit_for_run(
        user_id=None,
        project_id=None,
        selected_skill_slugs=None,
        user_addon_ids=None,
    )
    assert merged["installed_skills"] == []
    assert merged["addon_ids"] == []
    assert merged["project_mcp_configs"] == []
    assert merged["addon_credit_tiers"] == {}


@pytest.mark.asyncio
async def test_resolve_toolkit_user_only_unions_authored_over_installed() -> None:
    installed = [
        {"slug": "market", "skill_md_content": "m", "source_repo": "", "source_path": "", "skill_files": {}},
        {"slug": "override-me", "skill_md_content": "old", "source_repo": "", "source_path": "", "skill_files": {}},
    ]
    authored = [
        {"slug": "override-me", "skill_md_content": "new", "source_repo": "", "source_path": "", "skill_files": {}},
    ]
    with (
        patch.object(toolkit, "_get_installed_skills_for_user", AsyncMock(return_value=installed)),
        patch.object(toolkit, "_get_authored_skills_for_user", AsyncMock(return_value=authored)),
        patch.object(toolkit, "_resolve_addon_credit_tiers", AsyncMock(return_value={})),
    ):
        merged = await toolkit.resolve_toolkit_for_run(
            user_id=42,
            project_id=None,
            selected_skill_slugs=None,
            user_addon_ids=["addonA"],
        )
    slugs = [s["slug"] for s in merged["installed_skills"]]
    assert slugs == ["override-me", "market"]
    assert next(s for s in merged["installed_skills"] if s["slug"] == "override-me")["skill_md_content"] == "new"
    assert merged["addon_ids"] == ["addonA"]
    assert merged["project_mcp_configs"] == []


@pytest.mark.asyncio
async def test_resolve_toolkit_applies_selected_slug_filter_to_user_and_project() -> None:
    with (
        patch.object(
            toolkit,
            "_get_installed_skills_for_user",
            AsyncMock(
                return_value=[
                    {"slug": "keep", "skill_md_content": "", "source_repo": "", "source_path": "", "skill_files": {}},
                    {"slug": "drop", "skill_md_content": "", "source_repo": "", "source_path": "", "skill_files": {}},
                ]
            ),
        ),
        patch.object(toolkit, "_get_authored_skills_for_user", AsyncMock(return_value=[])),
        patch.object(
            toolkit,
            "_get_project_skills",
            AsyncMock(
                return_value=[
                    {"slug": "keep", "skill_md_content": "p", "source_repo": "", "source_path": "", "skill_files": {}},
                    {
                        "slug": "drop-too",
                        "skill_md_content": "",
                        "source_repo": "",
                        "source_path": "",
                        "skill_files": {},
                    },
                ]
            ),
        ),
        patch.object(toolkit, "_get_project_mcp_configs", AsyncMock(return_value=[])),
        patch.object(toolkit, "_get_project_addon_ids", AsyncMock(return_value=[])),
        patch.object(toolkit, "_get_project_isolated_flag", AsyncMock(return_value=False)),
        patch.object(toolkit, "_resolve_addon_credit_tiers", AsyncMock(return_value={})),
    ):
        merged = await toolkit.resolve_toolkit_for_run(
            user_id=7,
            project_id="project-x",
            selected_skill_slugs=["keep"],
            user_addon_ids=[],
        )
    slugs = [s["slug"] for s in merged["installed_skills"]]
    assert slugs == ["keep"]
    # Project's "keep" (content="p") wins over user's.
    assert merged["installed_skills"][0]["skill_md_content"] == "p"


@pytest.mark.asyncio
async def test_resolve_toolkit_isolated_project_excludes_user_toolkit() -> None:
    with (
        patch.object(
            toolkit,
            "_get_installed_skills_for_user",
            AsyncMock(
                return_value=[
                    {
                        "slug": "user-skill",
                        "skill_md_content": "",
                        "source_repo": "",
                        "source_path": "",
                        "skill_files": {},
                    },
                ]
            ),
        ),
        patch.object(toolkit, "_get_authored_skills_for_user", AsyncMock(return_value=[])),
        patch.object(
            toolkit,
            "_get_project_skills",
            AsyncMock(
                return_value=[
                    {
                        "slug": "proj-skill",
                        "skill_md_content": "",
                        "source_repo": "",
                        "source_path": "",
                        "skill_files": {},
                    },
                ]
            ),
        ),
        patch.object(toolkit, "_get_project_mcp_configs", AsyncMock(return_value=[{"server_name": "pm", "id": "x"}])),
        patch.object(toolkit, "_get_project_addon_ids", AsyncMock(return_value=["proj-addon"])),
        patch.object(toolkit, "_get_project_isolated_flag", AsyncMock(return_value=True)),
        patch.object(toolkit, "_resolve_addon_credit_tiers", AsyncMock(return_value={})),
    ):
        merged = await toolkit.resolve_toolkit_for_run(
            user_id=7,
            project_id="project-x",
            selected_skill_slugs=None,
            user_addon_ids=["user-addon"],  # isolated → ignored
        )
    assert [s["slug"] for s in merged["installed_skills"]] == ["proj-skill"]
    assert merged["addon_ids"] == ["proj-addon"]
    assert merged["project_mcp_configs"] == [{"server_name": "pm", "id": "x"}]


@pytest.mark.asyncio
async def test_resolve_toolkit_populates_addon_credit_tiers() -> None:
    with (
        patch.object(toolkit, "_get_installed_skills_for_user", AsyncMock(return_value=[])),
        patch.object(toolkit, "_get_authored_skills_for_user", AsyncMock(return_value=[])),
        patch.object(
            toolkit,
            "_resolve_addon_credit_tiers",
            AsyncMock(return_value={"github": "standard", "stripe": "premium"}),
        ),
    ):
        merged = await toolkit.resolve_toolkit_for_run(
            user_id=1,
            project_id=None,
            selected_skill_slugs=None,
            user_addon_ids=["addon-1", "addon-2"],
        )
    assert merged["addon_credit_tiers"] == {"github": "standard", "stripe": "premium"}


# ═════════════════════════════════════════════════════════════════════════════
# apply_agent_policy_to_metadata (DB calls mocked)
# ═════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_apply_agent_policy_noop_for_personal_project_none() -> None:
    metadata = {"addons": ["shell", "browse"], "other": "kept"}
    out = await toolkit.apply_agent_policy_to_metadata(metadata, project_id=None)
    assert out == {"addons": ["shell", "browse"], "other": "kept"}
    assert "require_approval_tools" not in out


@pytest.mark.asyncio
async def test_apply_agent_policy_noop_when_project_has_no_org() -> None:
    from agent_server.models import DjangoProject

    class _QS:
        def filter(self, **kw):
            return self

        def values_list(self, *a, **kw):
            return self

        def first(self):
            return None

    with patch.object(DjangoProject, "objects", _QS()):
        out = await toolkit.apply_agent_policy_to_metadata({"addons": ["shell"]}, project_id="proj-personal")
    assert out == {"addons": ["shell"]}


@pytest.mark.asyncio
async def test_apply_agent_policy_filters_blocked_and_injects_hitl() -> None:
    from agent_server.models import DjangoProject

    class _QS:
        def filter(self, **kw):
            return self

        def values_list(self, *a, **kw):
            return self

        def first(self):
            return "00000000-0000-0000-0000-000000000001"

    policy_row = {
        "blocked_tools": ["terminal"],
        "blocked_tool_groups": ["shell"],  # adds shell,run_command,terminal
        "require_hitl_for": ["git_push", "stripe.charge"],
    }
    with (
        patch.object(DjangoProject, "objects", _QS()),
        patch.object(toolkit, "_load_org_agent_policy", AsyncMock(return_value=policy_row)),
    ):
        out = await toolkit.apply_agent_policy_to_metadata(
            {
                "addons": ["shell", "run_command", "terminal", "git_push", "browse"],
                "extra": True,
            },
            project_id="proj-org",
        )
    # shell group expanded (shell, run_command, terminal) + explicit blocked "terminal"
    assert "shell" not in out["addons"]
    assert "run_command" not in out["addons"]
    assert "terminal" not in out["addons"]
    # git_push + browse survive filtering (they're not in blocked)
    assert "git_push" in out["addons"]
    assert "browse" in out["addons"]
    # HITL tools injected
    assert out["require_approval_tools"] == ["git_push", "stripe.charge"]
    # Other metadata untouched
    assert out["extra"] is True


@pytest.mark.asyncio
async def test_apply_agent_policy_absent_policy_row_is_noop() -> None:
    from agent_server.models import DjangoProject

    class _QS:
        def filter(self, **kw):
            return self

        def values_list(self, *a, **kw):
            return self

        def first(self):
            return "00000000-0000-0000-0000-000000000002"

    with (
        patch.object(DjangoProject, "objects", _QS()),
        patch.object(toolkit, "_load_org_agent_policy", AsyncMock(return_value=None)),
    ):
        out = await toolkit.apply_agent_policy_to_metadata(
            {"addons": ["shell", "browse"]},
            project_id="proj-org-no-policy",
        )
    assert out == {"addons": ["shell", "browse"]}
    assert "require_approval_tools" not in out
