"""Tests for planner/executor plan context communication reminders."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_plan_module():
    tools_dir = Path(__file__).resolve().parents[1] / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    return importlib.import_module("tools.plan")


plan_module = _load_plan_module()
hooks_module = importlib.import_module("agent_server.engine.hooks")


def _sample_plan() -> plan_module.Plan:
    return plan_module.Plan(
        goal="Ship feature X",
        phases=[
            plan_module.Phase(id=1, title="Research", status="completed"),
            plan_module.Phase(id=2, title="Implementation", status="in_progress"),
            plan_module.Phase(id=3, title="Validation", status="pending"),
        ],
        current_phase_id=2,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )


def test_planner_plan_context_includes_message_tool_communication_rule(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hooks_module, "_get_current_plan", lambda cid=None: _sample_plan())

    out = hooks_module.format_plan_markdown("conv-1")

    assert out is not None
    assert "I must use my message tool" in out
    assert "Raw assistant text is reserved for my internal thinking only" in out
    assert "max 200 words" in out
    assert "internal thoughts must stay concise too (max 100 words)" in out
    assert "periodically share task-completion status updates" in out
    assert "should not repeat content already delivered through the message tool" in out


def test_executor_plan_context_includes_message_tool_communication_rule(
    monkeypatch,
) -> None:
    monkeypatch.setattr(hooks_module, "_get_current_plan", lambda cid=None: _sample_plan())

    out = hooks_module.format_executor_plan_context("conv-1", task="implement endpoint")

    assert out is not None
    assert "I must use my message tool" in out
    assert "Raw assistant text is reserved for my internal thinking only" in out
    assert "max 200 words" in out
    assert "internal thoughts must stay concise too (max 100 words)" in out
    assert "periodically share task-completion status updates" in out
    assert "should not repeat content already delivered through the message tool" in out


@pytest.mark.asyncio
async def test_message_discipline_hook_injects_even_without_plan(monkeypatch) -> None:
    monkeypatch.setattr(hooks_module, "_get_current_plan", lambda cid=None: None)
    hook = hooks_module.make_message_discipline_hook()
    messages = [type("Msg", (), {"role": "system", "content": "sys"})()]

    await hook(messages=messages)

    assert any("message-discipline" in str(getattr(m, "content", "")) for m in messages)
    assert any(
        "should not repeat content already delivered through the message tool" in str(getattr(m, "content", ""))
        for m in messages
    )
    assert any("max 200 words" in str(getattr(m, "content", "")) for m in messages)
    assert any(
        "internal thoughts must stay concise too (max 100 words)" in str(getattr(m, "content", "")) for m in messages
    )


@pytest.mark.asyncio
async def test_message_discipline_hook_does_not_duplicate_with_plan_context(monkeypatch) -> None:
    monkeypatch.setattr(hooks_module, "_get_current_plan", lambda cid=None: _sample_plan())
    hook = hooks_module.make_message_discipline_hook()
    messages = [
        type("Msg", (), {"role": "system", "content": "sys"})(),
        type("Msg", (), {"role": "user", "content": hooks_module.format_plan_markdown("conv-1")})(),
    ]

    await hook(messages=messages)

    assert not any("message-discipline" in str(getattr(m, "content", "")) for m in messages)
