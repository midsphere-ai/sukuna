"""Unit tests for the component-level versioning system."""

from __future__ import annotations

import pytest

from agent_server.versioning import (
    HarnessManifest,
    _collect_tool_versions,
    _compute_hash,
    _get_exo_commit,
    build_manifest,
    diff_manifests,
)

# ---------------------------------------------------------------------------
# HarnessManifest dataclass
# ---------------------------------------------------------------------------


def _make_manifest(**overrides: object) -> HarnessManifest:
    defaults = {
        "agent_version": "0.1.0",
        "harness": "0.1.0",
        "prompts": "0.1.0",
        "context_engine": "0.1.0",
        "guardrails": "0.1.0",
        "tool_surface": "0.1.0",
        "knowledge_mgr": "0.1.0",
        "tools": {"shell": "0.1.0", "browse": "0.1.0"},
        "tools_hash": "aabbccddee00",
        "skills": {"webdev": "abc12345", "prd": "def67890"},
        "skills_hash": "112233445566",
        "exo_commit": "c54a1c2b",
    }
    defaults.update(overrides)
    return HarnessManifest(**defaults)


class TestHarnessManifest:
    def test_frozen(self) -> None:
        m = _make_manifest()
        with pytest.raises(AttributeError):
            m.harness = "0.2.0"  # type: ignore[misc]

    def test_to_dict_round_trip(self) -> None:
        m = _make_manifest()
        d = m.to_dict()
        assert isinstance(d, dict)
        m2 = HarnessManifest.from_dict(d)
        assert m == m2

    def test_to_dict_keys(self) -> None:
        d = _make_manifest().to_dict()
        expected = {
            "agent_version",
            "harness",
            "prompts",
            "context_engine",
            "guardrails",
            "tool_surface",
            "knowledge_mgr",
            "tools",
            "tools_hash",
            "skills",
            "skills_hash",
            "exo_commit",
        }
        assert set(d.keys()) == expected


# ---------------------------------------------------------------------------
# _compute_hash
# ---------------------------------------------------------------------------


class TestComputeHash:
    def test_deterministic(self) -> None:
        d = {"a": "1", "b": "2"}
        assert _compute_hash(d) == _compute_hash(d)

    def test_order_independent(self) -> None:
        assert _compute_hash({"a": "1", "b": "2"}) == _compute_hash({"b": "2", "a": "1"})

    def test_length(self) -> None:
        assert len(_compute_hash({"x": "y"})) == 12

    def test_empty(self) -> None:
        h = _compute_hash({})
        assert isinstance(h, str) and len(h) == 12

    def test_different_values_different_hash(self) -> None:
        assert _compute_hash({"a": "1"}) != _compute_hash({"a": "2"})


# ---------------------------------------------------------------------------
# _get_exo_commit
# ---------------------------------------------------------------------------


class TestGetExoCommit:
    def test_returns_string(self) -> None:
        commit = _get_exo_commit()
        assert isinstance(commit, str)

    def test_non_empty(self) -> None:
        """pyproject.toml should have a pinned exo-core rev."""
        commit = _get_exo_commit()
        assert len(commit) > 0, "Expected non-empty exo commit from pyproject.toml"


# ---------------------------------------------------------------------------
# _collect_tool_versions
# ---------------------------------------------------------------------------


class TestCollectToolVersions:
    def test_returns_dict(self) -> None:
        versions = _collect_tool_versions()
        assert isinstance(versions, dict)

    def test_has_core_tools(self) -> None:
        versions = _collect_tool_versions()
        for tool_name in ("shell", "browse", "plan", "find", "search"):
            assert tool_name in versions, f"Missing tool: {tool_name}"

    def test_versions_are_strings(self) -> None:
        versions = _collect_tool_versions()
        for name, ver in versions.items():
            assert isinstance(ver, str), f"Tool {name} version is not a string"


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------


class TestBuildManifest:
    def test_without_skill_registry(self) -> None:
        m = build_manifest(skill_registry=None)
        assert isinstance(m, HarnessManifest)
        assert m.skills == {}
        assert len(m.skills_hash) == 12

    def test_all_component_versions_populated(self) -> None:
        m = build_manifest()
        assert m.harness != ""
        assert m.prompts != ""
        assert m.context_engine != ""
        assert m.guardrails != ""
        assert m.tool_surface != ""
        assert m.knowledge_mgr != ""

    def test_tools_populated(self) -> None:
        m = build_manifest()
        assert len(m.tools) > 0
        assert len(m.tools_hash) == 12

    def test_exo_commit_populated(self) -> None:
        m = build_manifest()
        assert len(m.exo_commit) > 0


# ---------------------------------------------------------------------------
# diff_manifests
# ---------------------------------------------------------------------------


class TestDiffManifests:
    def test_identical_manifests(self) -> None:
        m = _make_manifest()
        assert diff_manifests(m, m) == {}

    def test_component_diff(self) -> None:
        a = _make_manifest(harness="0.1.0")
        b = _make_manifest(harness="0.2.0")
        diffs = diff_manifests(a, b)
        assert "harness" in diffs
        assert diffs["harness"] == ("0.1.0", "0.2.0")

    def test_tool_diff(self) -> None:
        a = _make_manifest(tools={"shell": "0.1.0", "browse": "0.1.0"})
        b = _make_manifest(tools={"shell": "0.2.0", "browse": "0.1.0"})
        diffs = diff_manifests(a, b)
        assert "tool:shell" in diffs
        assert "tool:browse" not in diffs

    def test_skill_diff(self) -> None:
        a = _make_manifest(skills={"webdev": "abc12345"})
        b = _make_manifest(skills={"webdev": "xyz99999"})
        diffs = diff_manifests(a, b)
        assert "skill:webdev" in diffs

    def test_absent_skill(self) -> None:
        a = _make_manifest(skills={"webdev": "abc12345"})
        b = _make_manifest(skills={})
        diffs = diff_manifests(a, b)
        assert "skill:webdev" in diffs
        assert diffs["skill:webdev"] == ("abc12345", "(absent)")

    def test_absent_tool(self) -> None:
        a = _make_manifest(tools={"shell": "0.1.0"})
        b = _make_manifest(tools={"shell": "0.1.0", "new_tool": "0.1.0"})
        diffs = diff_manifests(a, b)
        assert "tool:new_tool" in diffs
        assert diffs["tool:new_tool"] == ("(absent)", "0.1.0")

    def test_multiple_diffs(self) -> None:
        a = _make_manifest(prompts="0.1.0", guardrails="0.1.0")
        b = _make_manifest(prompts="0.2.0", guardrails="0.3.0")
        diffs = diff_manifests(a, b)
        assert "prompts" in diffs
        assert "guardrails" in diffs
