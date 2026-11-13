"""Tests for planner plan-before-delegate enforcement."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_server.infra import guards


def _ctx(event: str, **inputs):
    return SimpleNamespace(
        event=SimpleNamespace(value=event),
        inputs=SimpleNamespace(**inputs),
    )


def _planner():
    return SimpleNamespace(name="planner", conversation_id="conv-test")


@pytest.mark.asyncio
async def test_blocks_delegate_for_medium_complex_without_plan(monkeypatch) -> None:
    monkeypatch.setattr(guards, "_planner_has_active_plan", lambda agent: False)
    rail = guards.PlannerPlanRequiredRail()
    agent = _planner()

    await rail.handle(
        _ctx(
            "start",
            agent=agent,
            input="Build a full-stack app with auth, database, API endpoints, and deployment.",
        )
    )
    decision = await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="delegate",
            arguments={"task": "implement api"},
        )
    )

    assert decision == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_allows_delegate_after_plan_tool_used(monkeypatch) -> None:
    monkeypatch.setattr(guards, "_planner_has_active_plan", lambda agent: False)
    rail = guards.PlannerPlanRequiredRail()
    agent = _planner()

    await rail.handle(
        _ctx(
            "start",
            agent=agent,
            input="Design and implement a multi-step migration plan for our backend services.",
        )
    )
    await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="plan",
            arguments={"action": "update"},
        )
    )
    decision = await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="delegate",
            arguments={"task": "run first migration phase"},
        )
    )

    assert decision == guards.RailAction.CONTINUE


@pytest.mark.asyncio
async def test_requires_plan_for_single_execution_request(monkeypatch) -> None:
    monkeypatch.setattr(guards, "_planner_has_active_plan", lambda agent: False)
    rail = guards.PlannerPlanRequiredRail()
    agent = _planner()

    await rail.handle(
        _ctx(
            "start",
            agent=agent,
            input="Implement authentication middleware for the backend API.",
        )
    )
    decision = await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="delegate",
            arguments={"task": "implement auth middleware"},
        )
    )

    assert decision == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_allows_delegate_for_simple_request(monkeypatch) -> None:
    monkeypatch.setattr(guards, "_planner_has_active_plan", lambda agent: False)
    rail = guards.PlannerPlanRequiredRail()
    agent = _planner()

    await rail.handle(_ctx("start", agent=agent, input="What is 2+2?"))
    decision = await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="delegate",
            arguments={"task": "answer arithmetic question"},
        )
    )

    assert decision == guards.RailAction.CONTINUE


@pytest.mark.asyncio
async def test_allows_delegate_when_plan_already_exists(monkeypatch) -> None:
    monkeypatch.setattr(guards, "_planner_has_active_plan", lambda agent: True)
    rail = guards.PlannerPlanRequiredRail()
    agent = _planner()

    await rail.handle(
        _ctx(
            "start",
            agent=agent,
            input="Refactor and deploy the entire platform with rollback safeguards.",
        )
    )
    decision = await rail.handle(
        _ctx(
            "pre_tool_call",
            agent=agent,
            tool_name="delegate",
            arguments={"task": "execute phase one"},
        )
    )

    assert decision == guards.RailAction.CONTINUE
