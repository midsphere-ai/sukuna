from __future__ import annotations

import uuid

import pytest

from agent_server.api import runs as runs_api
from agent_server.models import SandboxEvent, SandboxRun


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_mark_run_task_crashed_sets_failed_and_emits_terminal_event() -> None:
    run_id = str(uuid.uuid4())
    SandboxRun.objects.create(
        id=run_id,
        task="test crash path",
        status="running",
        model="test-model",
        conversation_id=run_id,
    )

    await runs_api._mark_run_task_crashed(run_id, RuntimeError("boom"))

    run = SandboxRun.objects.get(id=run_id)
    assert run.status == "failed"
    assert run.error == "run_task_crashed"

    events = list(SandboxEvent.objects.filter(run_id=run_id).order_by("sequence"))
    assert len(events) == 1
    assert events[0].event_type == "run_failed"
    assert events[0].data["error_code"] == "run_task_crashed"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_mark_run_task_crashed_is_noop_for_terminal_runs() -> None:
    run_id = str(uuid.uuid4())
    SandboxRun.objects.create(
        id=run_id,
        task="already terminal",
        status="completed",
        model="test-model",
        conversation_id=run_id,
    )

    await runs_api._mark_run_task_crashed(run_id, RuntimeError("boom"))

    run = SandboxRun.objects.get(id=run_id)
    assert run.status == "completed"
    assert run.error in ("", None)
    assert SandboxEvent.objects.filter(run_id=run_id).count() == 0
