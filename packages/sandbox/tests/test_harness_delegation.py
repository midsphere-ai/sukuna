"""Unit tests for the OrchestratorHarness delegation robustness fixes.

Regression coverage for the bug where the planner called ``delegate`` but the
orchestrator logged ``delegations=0`` because an exception after the delegate
tool call caused the harness to break out of the loop before checking the
delegation signal.

Also covers:
- Re-entrance guard on the ``delegate`` tool (duplicate calls rejected)
- Empty-task guard on the ``delegate`` tool
- Early-exit on delegation signal
- ``planner_error`` path when no delegation was recorded
- ``repr(exc)``-based error logging for exceptions with empty ``__str__``
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from exo.hooks import HookPoint
from exo.rail import RailAbortError

from agent_server.engine.harness import (
    _PLANNER_FRESH_MESSAGE_ACK_THOUGHT,
    DelegationSignal,
    OrchestratorHarness,
    _build_delegate_tool,
)

# ═══════════════════════════════════════════════════════════════════════════════
# delegate tool — re-entrance & validation guards
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_delegate_tool_records_signal() -> None:
    signal = DelegationSignal()
    tool = _build_delegate_tool(signal)

    result = await tool.execute(task="build a website", context="use react", use_history=True)

    assert "accepted" in result.lower()
    assert signal.task == "build a website"
    assert signal.context == "use react"
    assert signal.use_history is True


@pytest.mark.asyncio
async def test_delegate_tool_rejects_reentrance() -> None:
    """A second delegate call must NOT overwrite the first task."""
    signal = DelegationSignal()
    tool = _build_delegate_tool(signal)

    first = await tool.execute(task="first task")
    second = await tool.execute(task="second task")

    assert "accepted" in first.lower()
    assert "ERROR" in second
    assert "already" in second.lower()
    # Crucially: the first task is preserved, not clobbered.
    assert signal.task == "first task"


@pytest.mark.asyncio
async def test_delegate_tool_rejects_empty_task() -> None:
    signal = DelegationSignal()
    tool = _build_delegate_tool(signal)

    result = await tool.execute(task="   ")

    assert "ERROR" in result
    assert signal.task is None


@pytest.mark.asyncio
async def test_delegate_signal_reset_allows_new_delegation() -> None:
    """After ``signal.reset()`` (next iteration), delegation works again."""
    signal = DelegationSignal()
    tool = _build_delegate_tool(signal)

    await tool.execute(task="iter 1 task")
    signal.reset()
    result = await tool.execute(task="iter 2 task")

    assert "accepted" in result.lower()
    assert signal.task == "iter 2 task"


@pytest.mark.asyncio
async def test_planner_start_hook_injects_fresh_message_acknowledgement() -> None:
    harness = _make_harness(memory_store=None)
    planner = harness._build_planner(_build_delegate_tool(DelegationSignal()))

    assert planner.hook_manager.has_hooks(HookPoint.START) is True

    await planner.hook_manager.run(HookPoint.START, agent=planner, input="new user message")
    injected = planner._ephemeral_messages.get_nowait()
    assert getattr(injected, "content", "") == _PLANNER_FRESH_MESSAGE_ACK_THOUGHT


# ═══════════════════════════════════════════════════════════════════════════════
# OrchestratorHarness.execute — orchestration control flow
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class _FakeEvent:
    """Minimal stand-in for exo StreamEvent."""

    type: str
    status: str | None = None
    agent_name: str = ""
    text: str = ""


class _FakeHarnessContext:
    """Minimal HarnessContext stub — just enough for OrchestratorHarness.execute.

    Scripts are lists-of-lists: one inner list per ``stream_agent`` call.
    Calls that exhaust the script list yield nothing (i.e., an empty stream
    with no tool calls — the harness will treat this as a direct response).
    """

    def __init__(
        self,
        *,
        input_text: str,
        planner_scripts: list[list] | None = None,
        executor_scripts: list[list] | None = None,
    ) -> None:
        self.input = input_text
        self.messages: list[Any] = []
        self._planner_scripts = list(planner_scripts or [])
        self._executor_scripts = list(executor_scripts or [])
        self.emitted: list[dict] = []
        self.stream_agent_calls: list[str] = []

    def emit(self, kind: str, **data: Any) -> dict:
        ev = {"kind": kind, **data}
        self.emitted.append(ev)
        return ev

    async def stream_agent(self, agent: Any, input: Any, **kwargs: Any):
        name = getattr(agent, "name", "unknown")
        self.stream_agent_calls.append(name)

        if name == "planner":
            script = self._planner_scripts.pop(0) if self._planner_scripts else []
        else:
            script = self._executor_scripts.pop(0) if self._executor_scripts else []

        for item in script:
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                # Side-effect callable: run it; if it returns an event, yield.
                result = item()
                if result is not None:
                    yield result
            else:
                yield item
            await asyncio.sleep(0)  # cooperative yield


def _make_harness(**overrides: Any) -> OrchestratorHarness:
    """Build an OrchestratorHarness with minimal stubs."""
    defaults: dict[str, Any] = {
        "name": "test-orchestrator",
        "planner_model": "test/model",
        "planner_instructions": "test planner",
        "planner_tools": [],
        "executor_tools": [],
        "memory_store": MagicMock(),
        "run_id": "run-test",
        "conversation_id": "conv-test",
        "provider": MagicMock(),
    }
    defaults.update(overrides)
    return OrchestratorHarness(**defaults)


def _stub_agent(name: str) -> MagicMock:
    agent = MagicMock()
    agent.name = name
    return agent


def _step_completed() -> _FakeEvent:
    return _FakeEvent(type="step", status="completed")


def _status_completed(agent_name: str) -> _FakeEvent:
    return _FakeEvent(type="status", status="completed", agent_name=agent_name)


async def _drain(agen) -> list[Any]:
    return [ev async for ev in agen]


# -- Planner input formatting -----------------------------------------------


def test_format_planner_input_includes_result_files_and_questions() -> None:
    out = OrchestratorHarness._format_planner_input(
        "Ship the feature",
        [
            {
                "task": "Implement backend endpoint",
                "result": "Endpoint implemented successfully.",
                "result_files": ["/tmp/executor/result.md"],
                "planner_questions": ["Should we expose this behind a feature flag?"],
                "messages_sent": ["Shared progress update with user."],
            }
        ],
    )

    assert "Executor result files:" in out
    assert "/tmp/executor/result.md" in out
    assert "Questions the executor wants you to ask the user:" in out
    assert "Should we expose this behind a feature flag?" in out
    assert "Messages already sent to user by executor:" in out


# -- Happy path: planner delegates once, executor runs ------------------------


@pytest.mark.asyncio
async def test_planner_delegates_then_executor_runs(monkeypatch) -> None:
    harness = _make_harness()

    # Capture the signal so the planner script can set it mid-stream.
    captured: dict[str, DelegationSignal] = {}

    real_build_planner = harness._build_planner

    def fake_build_planner(delegate_tool):
        # Pull the signal out of the closure by inspecting the tool's fn.
        # (_build_delegate_tool defines delegate() closing over ``signal``.)
        fn = delegate_tool._fn if hasattr(delegate_tool, "_fn") else delegate_tool.function
        sig = fn.__closure__[0].cell_contents  # type: ignore[union-attr]
        captured["signal"] = sig
        return _stub_agent("planner")

    monkeypatch.setattr(harness, "_build_planner", fake_build_planner)
    monkeypatch.setattr(harness, "_build_executor", lambda sig: _stub_agent("executor_abc12345"))

    def set_signal_from_capture():
        captured["signal"].task = "do the work"
        return _step_completed()

    ctx = _FakeHarnessContext(
        input_text="hi",
        planner_scripts=[
            # Iteration 1: delegate fires → executor runs.
            [
                _FakeEvent(type="text", text="thinking..."),
                set_signal_from_capture,  # sets signal.task, returns step
            ],
            # Iteration 2: no delegation → planner responds directly.
            [
                _FakeEvent(type="text", text="here is the result"),
                _step_completed(),
            ],
        ],
        executor_scripts=[
            [
                _FakeEvent(type="text", text="work done", agent_name="executor_abc12345"),
                _status_completed("executor_abc12345"),
            ],
        ],
    )

    # Patch KM extraction (we don't want DB calls in unit tests).
    async def noop_km(*a, **k):
        from agent_server.engine.knowledge import KMOutput

        return KMOutput(nothing_to_do=True)

    monkeypatch.setattr("agent_server.engine.harness.run_km", noop_km)
    monkeypatch.setattr("agent_server.engine.harness.should_run_km", lambda *a, **k: False)

    events = await _drain(harness.execute(ctx))

    # Planner was streamed once, then executor, then planner again (direct response).
    assert ctx.stream_agent_calls[0] == "planner"
    assert ctx.stream_agent_calls[1] == "executor_abc12345"

    # orchestrator_completed should report 1 delegation.
    final = [e for e in ctx.emitted if e["kind"] == "orchestrator_completed"]
    assert len(final) == 1
    assert final[0]["delegations"] == 1
    assert final[0]["stop_reason"] == "planner_direct_response"


# -- REGRESSION: planner errors AFTER delegate → executor must still run ------


@pytest.mark.asyncio
async def test_planner_error_after_delegate_still_spawns_executor(monkeypatch) -> None:
    """The core regression: if the planner raises AFTER delegate() sets the
    signal, the old code broke out of the loop and dropped the delegation.
    The new code must still run the executor.
    """
    harness = _make_harness()
    captured: dict[str, DelegationSignal] = {}

    def fake_build_planner(delegate_tool):
        fn = delegate_tool._fn if hasattr(delegate_tool, "_fn") else delegate_tool.function
        sig = fn.__closure__[0].cell_contents  # type: ignore[union-attr]
        captured["signal"] = sig
        return _stub_agent("planner")

    monkeypatch.setattr(harness, "_build_planner", fake_build_planner)
    monkeypatch.setattr(harness, "_build_executor", lambda sig: _stub_agent("executor_post_err"))

    async def noop_km(*a, **k):
        from agent_server.engine.knowledge import KMOutput

        return KMOutput(nothing_to_do=True)

    monkeypatch.setattr("agent_server.engine.harness.run_km", noop_km)
    monkeypatch.setattr("agent_server.engine.harness.should_run_km", lambda *a, **k: False)

    def fire_delegate_no_step():
        # Set the signal WITHOUT emitting a step-completed event.
        # This simulates the delegate tool firing mid-step — the
        # early-exit check only triggers on ``step/completed``, so the
        # only way the executor still runs is via the exception-path
        # recovery logic that the fix introduced.
        captured["signal"].task = "the work"
        return None  # no event yielded

    # Exception with empty __str__ — reproduces the "Planner streaming
    # failed on iteration 0: " production log.
    class EmptyStrError(Exception):
        def __str__(self) -> str:
            return ""

    ctx = _FakeHarnessContext(
        input_text="go",
        planner_scripts=[
            # Iteration 1: delegate fires (signal set), then planner
            # stream raises BEFORE a step/completed event is yielded.
            # Old code would ``break`` and drop the delegation; the fix
            # must still spawn the executor.
            [
                _FakeEvent(type="text", text="thinking..."),
                fire_delegate_no_step,
                EmptyStrError(),
            ],
            # Iteration 2: planner responds directly (no delegation).
            [_FakeEvent(type="text", text="done"), _step_completed()],
        ],
        executor_scripts=[
            [_status_completed("executor_post_err")],
        ],
    )

    events = await _drain(harness.execute(ctx))

    # REGRESSION ASSERTION: executor MUST have been spawned even though
    # the planner raised an exception after setting the delegation signal.
    assert "executor_post_err" in ctx.stream_agent_calls, (
        "Executor should have been spawned after successful delegation, "
        "even when the planner stream subsequently raised an exception"
    )

    # planner_error was emitted with a useful error string.
    planner_err_evs = [e for e in ctx.emitted if e["kind"] == "planner_error"]
    assert len(planner_err_evs) == 1
    assert "EmptyStrError" in planner_err_evs[0]["error"]

    # orchestrator_completed should report 1 delegation (the recovered one).
    final = [e for e in ctx.emitted if e["kind"] == "orchestrator_completed"][0]
    assert final["delegations"] == 1, (
        f"Expected 1 delegation, got {final['delegations']}. "
        "The fix must recover the delegation signal after planner error."
    )


@pytest.mark.asyncio
async def test_planner_error_before_delegate_stops_orchestrator(monkeypatch) -> None:
    """If the planner errors BEFORE delegate() was called, stop with planner_error."""
    harness = _make_harness()

    monkeypatch.setattr(harness, "_build_planner", lambda tool: _stub_agent("planner"))
    monkeypatch.setattr(harness, "_build_executor", lambda sig: _stub_agent("executor_never"))

    async def noop_km(*a, **k):
        from agent_server.engine.knowledge import KMOutput

        return KMOutput(nothing_to_do=True)

    monkeypatch.setattr("agent_server.engine.harness.run_km", noop_km)
    monkeypatch.setattr("agent_server.engine.harness.should_run_km", lambda *a, **k: False)

    # Exception with empty __str__ — reproduces the "Planner streaming
    # failed on iteration 0: " log.
    class EmptyStrError(Exception):
        def __str__(self) -> str:
            return ""

    ctx = _FakeHarnessContext(
        input_text="go",
        planner_scripts=[[EmptyStrError()]],
    )

    events = await _drain(harness.execute(ctx))

    # Executor should NOT have been spawned.
    assert "executor_never" not in ctx.stream_agent_calls

    # planner_error event should contain a non-empty error field (repr includes type).
    planner_err_evs = [e for e in ctx.emitted if e["kind"] == "planner_error"]
    assert len(planner_err_evs) == 1
    assert planner_err_evs[0]["error"]  # non-empty
    assert "EmptyStrError" in planner_err_evs[0]["error"]
    assert planner_err_evs[0]["error_type"] == "EmptyStrError"

    # orchestrator_completed should report 0 delegations and planner_error.
    final = [e for e in ctx.emitted if e["kind"] == "orchestrator_completed"][0]
    assert final["delegations"] == 0
    assert final["stop_reason"] == "planner_error"


@pytest.mark.asyncio
async def test_planner_direct_response_stops_orchestrator(monkeypatch) -> None:
    """If the planner never delegates, stop with planner_direct_response."""
    harness = _make_harness()

    monkeypatch.setattr(harness, "_build_planner", lambda tool: _stub_agent("planner"))
    monkeypatch.setattr(harness, "_build_executor", lambda sig: _stub_agent("executor_never"))

    async def noop_km(*a, **k):
        from agent_server.engine.knowledge import KMOutput

        return KMOutput(nothing_to_do=True)

    monkeypatch.setattr("agent_server.engine.harness.run_km", noop_km)
    monkeypatch.setattr("agent_server.engine.harness.should_run_km", lambda *a, **k: False)

    ctx = _FakeHarnessContext(
        input_text="hi",
        planner_scripts=[
            [
                _FakeEvent(type="text", text="hello back"),
                _step_completed(),
            ],
        ],
    )

    events = await _drain(harness.execute(ctx))

    assert "executor_never" not in ctx.stream_agent_calls
    final = [e for e in ctx.emitted if e["kind"] == "orchestrator_completed"][0]
    assert final["delegations"] == 0
    assert final["stop_reason"] == "planner_direct_response"


@pytest.mark.asyncio
async def test_executor_rail_abort_is_normalized_from_exception_group(monkeypatch) -> None:
    """Executor rail aborts wrapped by TaskGroup should be handled cleanly."""
    harness = _make_harness()
    captured: dict[str, DelegationSignal] = {}

    def fake_build_planner(delegate_tool):
        fn = delegate_tool._fn if hasattr(delegate_tool, "_fn") else delegate_tool.function
        sig = fn.__closure__[0].cell_contents  # type: ignore[union-attr]
        captured["signal"] = sig
        return _stub_agent("planner")

    monkeypatch.setattr(harness, "_build_planner", fake_build_planner)
    monkeypatch.setattr(harness, "_build_executor", lambda sig: _stub_agent("executor_blocked"))

    async def noop_km(*a, **k):
        from agent_server.engine.knowledge import KMOutput

        return KMOutput(nothing_to_do=True)

    monkeypatch.setattr("agent_server.engine.harness.run_km", noop_km)
    monkeypatch.setattr("agent_server.engine.harness.should_run_km", lambda *a, **k: False)

    def set_signal_from_capture():
        captured["signal"].task = "perform guarded action"
        return _step_completed()

    grouped_abort = ExceptionGroup(
        "unhandled errors in a TaskGroup (1 sub-exception)",
        [RailAbortError("RailManager", reason="Rail aborted at pre_tool_call")],
    )

    ctx = _FakeHarnessContext(
        input_text="hi",
        planner_scripts=[
            [_FakeEvent(type="text", text="delegating"), set_signal_from_capture],
            [_FakeEvent(type="text", text="done"), _step_completed()],
        ],
        executor_scripts=[[grouped_abort]],
    )

    await _drain(harness.execute(ctx))

    executor_err_evs = [e for e in ctx.emitted if e["kind"] == "executor_error"]
    assert len(executor_err_evs) == 1
    assert executor_err_evs[0]["error_type"] == "RailAbortError"
    assert executor_err_evs[0]["blocked_by_guardrail"] is True
    assert "pre_tool_call" in executor_err_evs[0]["error"]
    assert "TaskGroup" not in executor_err_evs[0]["error"]
