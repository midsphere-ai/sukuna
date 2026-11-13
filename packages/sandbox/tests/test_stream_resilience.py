from __future__ import annotations

import asyncio
import uuid

import pytest
from django.test import RequestFactory

from agent_server.api import runs as runs_api
from agent_server.api.runs import stream_run
from agent_server.models import SandboxRun


def _chunk_text(chunk: bytes | str) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8", errors="replace")
    return chunk


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_stream_keeps_polling_when_channel_missing(monkeypatch) -> None:
    """A missing in-memory channel must not close a non-terminal run stream."""
    run_id = str(uuid.uuid4())
    SandboxRun.objects.create(
        id=run_id,
        task="hello",
        status="running",
        model="test-model",
        conversation_id=run_id,
    )

    runs_api._run_channels.pop(run_id, None)

    status_sequence = iter(["running", "completed"])

    async def _fake_status(_run_id: str) -> str:
        return next(status_sequence, "completed")

    async def _fake_fetch(_run_id: str, _after_seq: int, limit: int = 100):
        return []

    monkeypatch.setattr(runs_api, "_get_run_status", _fake_status)
    monkeypatch.setattr(runs_api, "_fetch_events_after", _fake_fetch)
    monkeypatch.setattr(runs_api, "RUN_STREAM_KEEPALIVE_SECONDS", 0.01)

    request = RequestFactory().get(f"/runs/{run_id}/stream")
    response = await stream_run(request, run_id)
    gen = response.streaming_content

    first = _chunk_text(await asyncio.wait_for(anext(gen), timeout=1.0))
    second = _chunk_text(await asyncio.wait_for(anext(gen), timeout=1.0))

    assert first.startswith(": connected")
    assert second.startswith(": keepalive")

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(gen), timeout=1.0)
