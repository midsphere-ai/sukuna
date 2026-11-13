"""Tests for dynamic filesystem-first path injection."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_server.engine import hooks as hooks_module
from agent_server.infra import guards


class _FakeAgent:
    def __init__(self) -> None:
        self.ephemeral_messages: list[str] = []

    def inject_ephemeral(self, content: str) -> None:
        self.ephemeral_messages.append(content)


def test_filesystem_instruction_uses_workspace_root_env(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_WORKSPACE_ROOT", "/tmp/custom-workspace")
    msg = hooks_module._filesystem_first_instruction()
    assert "/tmp/custom-workspace/" in msg
    assert "/home/user/" not in msg
    assert "If I just wrote a file" in msg
    assert "If I viewed an image or PDF" in msg
    assert "If the browser returned data" in msg
    assert "If I am starting a new phase" in msg
    assert "If an error occurred" in msg
    assert "If I am resuming after a gap" in msg


@pytest.mark.asyncio
async def test_filesystem_first_hook_injects_dynamic_workspace_path(monkeypatch) -> None:
    monkeypatch.setenv("SANDBOX_WORKSPACE_ROOT", "/tmp/custom-workspace")
    agent = _FakeAgent()
    hook = hooks_module.make_filesystem_first_hook()

    await hook(agent=agent)

    assert len(agent.ephemeral_messages) == 1
    msg = agent.ephemeral_messages[0]
    assert "/tmp/custom-workspace/" in msg
    assert "/home/user/" not in msg


def _pre_tool_ctx(*, path: str, action: str = "write"):
    return SimpleNamespace(
        event=SimpleNamespace(value="pre_tool_call"),
        inputs=SimpleNamespace(
            tool_name="file",
            arguments={"action": action, "path": path},
        ),
    )


@pytest.mark.asyncio
async def test_markdown_storage_rail_blocks_non_markdown_in_context_dir() -> None:
    rail = guards.MarkdownContextStorageRail()
    blocked = await rail.handle(ctx=_pre_tool_ctx(path=str(guards.CONTEXT_DIR / "note.txt")))
    assert blocked == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_markdown_storage_rail_allows_markdown_in_context_dir() -> None:
    rail = guards.MarkdownContextStorageRail()
    allowed = await rail.handle(ctx=_pre_tool_ctx(path=str(guards.CONTEXT_DIR / "note.md")))
    assert allowed == guards.RailAction.CONTINUE


@pytest.mark.asyncio
async def test_markdown_storage_rail_allows_non_markdown_outside_context_dir() -> None:
    rail = guards.MarkdownContextStorageRail()
    allowed = await rail.handle(ctx=_pre_tool_ctx(path="/tmp/project/main.py"))
    assert allowed == guards.RailAction.CONTINUE
