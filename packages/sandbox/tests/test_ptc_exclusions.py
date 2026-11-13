"""Regression tests for tool-level PTC exclusions."""

from __future__ import annotations

import sys
from pathlib import Path

from agent_server.infra.registry import populate_registry, registry

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


def _all_registered_and_gated_tools() -> dict[str, object]:
    tools: dict[str, object] = {t.name: t for t in registry.all_tools()}
    for gated in registry.get_tool_gates().values():
        for tool in gated:
            tools[tool.name] = tool
    return tools


def test_registry_marks_requested_tools_as_ptc_excluded():
    """Selected tools should stay direct even when agent ``ptc=True``."""
    populate_registry()
    tools = _all_registered_and_gated_tools()

    expected_excluded = {
        "file",
        "shell",
        "match",
        "schedule",
        "search",
        "browser",
        "web_init",
        "mobile_init",
        "expose",
    }

    for name in expected_excluded:
        tool = tools[name]
        assert getattr(tool, "_ptc_exclude", False) is True


def test_browser_gated_tools_remain_ptc_eligible_by_default():
    """Only the gateway ``browser`` tool is excluded, not every browser tool."""
    populate_registry()
    tools = _all_registered_and_gated_tools()
    assert getattr(tools["browser_view"], "_ptc_exclude", False) is False
