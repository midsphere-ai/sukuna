"""Tests for executor-specific communication and result-file rails."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_server.infra import guards


def _ctx(event: str, **inputs):
    return SimpleNamespace(
        event=SimpleNamespace(value=event),
        inputs=SimpleNamespace(**inputs),
    )


def _pre_message_ctx(msg_type: str, text: str = "status"):
    return _ctx(
        "pre_tool_call",
        tool_name="message",
        arguments={"type": msg_type, "text": text},
    )


def _finished_ctx(result):
    return _ctx("finished", result=result)


def _words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


@pytest.mark.asyncio
async def test_executor_message_mode_blocks_ask_and_result() -> None:
    rail = guards.ExecutorMessageModeRail()

    blocked_ask = await rail.handle(_pre_message_ctx("ask", "Need user input"))
    blocked_result = await rail.handle(_pre_message_ctx("result", "Final delivery"))

    assert blocked_ask == guards.RailAction.ABORT
    assert blocked_result == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_executor_message_mode_allows_info_aliases() -> None:
    rail = guards.ExecutorMessageModeRail()

    allowed_info = await rail.handle(_pre_message_ctx("info", "Working on it"))
    allowed_notify = await rail.handle(_pre_message_ctx("notify", "Progress update"))

    assert allowed_info == guards.RailAction.CONTINUE
    assert allowed_notify == guards.RailAction.CONTINUE


@pytest.mark.asyncio
async def test_executor_message_mode_blocks_oversized_info() -> None:
    rail = guards.ExecutorMessageModeRail()

    blocked = await rail.handle(_pre_message_ctx("info", _words(guards._EXECUTOR_INFO_MAX_WORDS + 1)))

    assert blocked == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_executor_result_file_rail_blocks_success_without_result_files() -> None:
    rail = guards.ExecutorResultFileRail()

    decision = await rail.handle(_finished_ctx({"success": True, "result": "done", "result_files": []}))

    assert decision == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_executor_result_file_rail_blocks_non_markdown_files() -> None:
    rail = guards.ExecutorResultFileRail()

    decision = await rail.handle(
        _finished_ctx(
            {
                "success": True,
                "result": "done",
                "result_files": ["/tmp/report.json"],
            }
        )
    )

    assert decision == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_executor_result_file_rail_blocks_missing_markdown_file() -> None:
    rail = guards.ExecutorResultFileRail()

    decision = await rail.handle(
        _finished_ctx(
            {
                "success": True,
                "result": "done",
                "result_files": ["/tmp/missing-report.md"],
            }
        )
    )

    assert decision == guards.RailAction.ABORT


@pytest.mark.asyncio
async def test_executor_result_file_rail_allows_success_with_markdown_file(tmp_path) -> None:
    rail = guards.ExecutorResultFileRail()
    report = tmp_path / "report.md"
    report.write_text("# result\n", encoding="utf-8")

    decision = await rail.handle(
        _finished_ctx(
            {
                "success": True,
                "result": "summary",
                "result_files": [str(report.resolve())],
            }
        )
    )

    assert decision == guards.RailAction.CONTINUE


@pytest.mark.asyncio
async def test_executor_result_file_rail_allows_failure_without_result_files() -> None:
    rail = guards.ExecutorResultFileRail()

    decision = await rail.handle(_finished_ctx({"success": False, "error": "tool failed", "result_files": []}))

    assert decision == guards.RailAction.CONTINUE
