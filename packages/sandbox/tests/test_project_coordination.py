"""Tests for project-scoped agent coordination.

Covers:
- ``_build_project_sandbox_block`` in the planner/executor prompts
- ``make_project_coordination_hook`` ephemeral injection
- ``_seed_agents_md`` idempotent AGENTS.md seeding
"""

from __future__ import annotations

import threading

import pytest

from agent_server import config
from agent_server.config import _seed_agents_md
from agent_server.engine import hooks as hooks_module
from agent_server.engine import prompts


class _FakeAgent:
    def __init__(self) -> None:
        self.ephemeral_messages: list[str] = []

    def inject_ephemeral(self, content: str) -> None:
        self.ephemeral_messages.append(content)


# ---------------------------------------------------------------------------
# Prompt block
# ---------------------------------------------------------------------------


def test_project_sandbox_block_empty_when_not_project_run() -> None:
    assert prompts._build_project_sandbox_block(is_project_run=False, project_title="Demo", project_files=None) == ""


def test_project_sandbox_block_renders_title_and_files() -> None:
    block = prompts._build_project_sandbox_block(
        is_project_run=True,
        project_title="Demo Project",
        project_files=[
            {"filename": "notes.md", "sandbox_path": "/home/user/workspace/notes.md"},
            {"filename": "data.csv", "sandbox_path": "/home/user/workspace/data.csv"},
        ],
    )
    assert "<project_sandbox>" in block
    assert "</project_sandbox>" in block
    assert "Demo Project" in block
    assert "AGENTS.md" in block
    assert "git worktree add" in block
    assert "notes.md" in block
    assert "/home/user/workspace/notes.md" in block
    assert "data.csv" in block


def test_project_sandbox_block_handles_empty_file_list() -> None:
    block = prompts._build_project_sandbox_block(is_project_run=True, project_title="Solo", project_files=None)
    assert "(none)" in block
    assert "AGENTS.md" in block


def test_planner_instructions_omits_project_sandbox_when_flag_off() -> None:
    instructions = prompts.build_planner_instructions(is_project_run=False)
    assert "<project_sandbox>" not in instructions


def test_planner_instructions_includes_project_sandbox_when_flag_on() -> None:
    instructions = prompts.build_planner_instructions(
        is_project_run=True,
        project_title="Demo",
        project_files=[{"filename": "a.txt", "sandbox_path": "/w/a.txt"}],
    )
    assert "<project_sandbox>" in instructions
    assert "Demo" in instructions
    assert "/w/a.txt" in instructions


def test_executor_instructions_includes_project_sandbox_when_flag_on() -> None:
    instructions = prompts.build_executor_instructions(
        is_project_run=True,
        project_title="Demo",
        project_files=[{"filename": "a.txt", "sandbox_path": "/w/a.txt"}],
    )
    assert "<project_sandbox>" in instructions
    assert "git worktree add" in instructions


# ---------------------------------------------------------------------------
# Coordination hook
# ---------------------------------------------------------------------------


def test_project_coordination_instruction_mentions_agents_md_and_worktrees() -> None:
    msg = hooks_module._project_coordination_instruction()
    assert "AGENTS.md" in msg
    assert "git worktree add" in msg
    assert "concurrently" in msg


@pytest.mark.asyncio
async def test_project_coordination_hook_injects_ephemeral() -> None:
    agent = _FakeAgent()
    hook = hooks_module.make_project_coordination_hook()

    await hook(agent=agent)

    assert len(agent.ephemeral_messages) == 1
    msg = agent.ephemeral_messages[0]
    assert "AGENTS.md" in msg
    assert "git worktree add" in msg


# ---------------------------------------------------------------------------
# AGENTS.md seeding
# ---------------------------------------------------------------------------


def test_seed_agents_md_creates_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "SANDBOX_WORKSPACE_ROOT", str(tmp_path))

    wrote = _seed_agents_md(
        project_title="Demo",
        project_custom_instructions="Always write tests.",
        project_files=[{"filename": "a.txt", "sandbox_path": "/home/user/workspace/a.txt"}],
    )
    assert wrote is True

    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "# AGENTS.md" in body
    assert "Demo" in body
    assert "Always write tests." in body
    assert "a.txt" in body
    assert "git worktree" in body
    assert "Active worktrees" in body


def test_seed_agents_md_preserves_existing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    sentinel = "# pre-existing content — do not clobber\n"
    (tmp_path / "AGENTS.md").write_text(sentinel, encoding="utf-8")

    wrote = _seed_agents_md(
        project_title="Demo",
        project_custom_instructions="",
        project_files=None,
    )
    assert wrote is False
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == sentinel


def test_seed_agents_md_handles_empty_file_list(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    wrote = _seed_agents_md(project_title="Demo", project_custom_instructions="", project_files=None)
    assert wrote is True
    body = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "(none)" in body
    assert "(none provided)" in body


def test_seed_agents_md_race_safe(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "SANDBOX_WORKSPACE_ROOT", str(tmp_path))
    results: list[bool] = []
    barrier = threading.Barrier(4)

    def _seeder() -> None:
        barrier.wait()
        results.append(
            _seed_agents_md(
                project_title="Demo",
                project_custom_instructions="",
                project_files=None,
            )
        )

    threads = [threading.Thread(target=_seeder) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    assert results.count(False) == 3
    assert (tmp_path / "AGENTS.md").exists()
