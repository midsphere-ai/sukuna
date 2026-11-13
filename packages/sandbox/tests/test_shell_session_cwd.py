"""Regression tests for shell foreground session cwd persistence."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

shell = importlib.import_module("shell")


@pytest.fixture(autouse=True)
def _reset_shell_sessions(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WORKSPACE", str(tmp_path))
    shell._SESSION_CWDS.clear()
    yield
    shell._SESSION_CWDS.clear()


@pytest.mark.asyncio
async def test_exec_session_persists_working_directory(tmp_path: Path) -> None:
    target = tmp_path / "workspace_a"
    target.mkdir()

    first = await shell._exec_shell(
        f'cd "{target}" && printf "hello" > file.txt',
        background=False,
        timeout=10,
        session="sess-a",
    )
    assert first["success"] is True
    assert first["exit_code"] == 0

    second = await shell._exec_shell(
        "pwd",
        background=False,
        timeout=10,
        session="sess-a",
    )
    assert second["success"] is True
    assert second["exit_code"] == 0
    assert second["stdout"].strip() == str(target)

    third = await shell._exec_shell(
        "cat file.txt",
        background=False,
        timeout=10,
        session="sess-a",
    )
    assert third["success"] is True
    assert third["exit_code"] == 0
    assert third["stdout"].strip() == "hello"


@pytest.mark.asyncio
async def test_exec_sessions_keep_independent_working_directories(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    await shell._exec_shell(
        f'cd "{dir_a}"',
        background=False,
        timeout=10,
        session="sess-a",
    )
    await shell._exec_shell(
        f'cd "{dir_b}"',
        background=False,
        timeout=10,
        session="sess-b",
    )

    out_a = await shell._exec_shell(
        "pwd",
        background=False,
        timeout=10,
        session="sess-a",
    )
    out_b = await shell._exec_shell(
        "pwd",
        background=False,
        timeout=10,
        session="sess-b",
    )

    assert out_a["success"] is True
    assert out_b["success"] is True
    assert out_a["stdout"].strip() == str(dir_a)
    assert out_b["stdout"].strip() == str(dir_b)
