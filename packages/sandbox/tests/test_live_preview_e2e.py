"""Integration test: poll → debounce → render → emit end-to-end.

Exercises the full ``LivePreviewLoop.start()`` → background polling →
debouncer → ``_render_and_emit`` → synthetic SSE event chain, using a
stubbed ``_convert_to_pdf`` so libreoffice isn't required.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from agent_server.engine.live_preview import LivePreviewLoop


class FakeEmit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


async def _wait_for(predicate, *, timeout: float = 3.0, interval: float = 0.05) -> None:
    """Poll ``predicate`` until it returns truthy or the timeout elapses."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout}s")


@pytest.mark.asyncio
async def test_end_to_end_pptx_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """New .pptx in the workspace → background poll picks it up → emit."""
    fake_emit = FakeEmit()

    async def fake_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return b"%PDF-1.4\nconverted " + path.name.encode()

    # Tighten the poll / debounce windows so the test runs fast.
    monkeypatch.setattr(LivePreviewLoop, "POLL_INTERVAL_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", fake_convert)

    loop = LivePreviewLoop(run_id="it", workspace=str(tmp_path), emit=fake_emit)
    await loop.start()
    try:
        # Write a file AFTER the snapshot seed, so the loop sees a diff on the next poll.
        await asyncio.sleep(0.05)
        (tmp_path / "deck.pptx").write_bytes(b"slides v1")

        await _wait_for(lambda: len(fake_emit.events) >= 1, timeout=2.0)
    finally:
        await loop.stop()

    assert len(fake_emit.events) == 1
    event = fake_emit.events[0]
    assert event["type"] == "tool_result"
    assert event["tool_call_id"] == "preview:deck.pptx"
    assert event["result"]["artifact_type"] == "pdf"
    decoded = base64.b64decode(event["result"]["content"])
    assert decoded.startswith(b"%PDF-1.4")


@pytest.mark.asyncio
async def test_end_to_end_subsequent_modifications_reuse_call_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three edits of the same file → three events, all sharing the callId."""
    fake_emit = FakeEmit()
    version = 0

    async def fake_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return f"%PDF-1.4\nv={version} ".encode() + path.name.encode()

    monkeypatch.setattr(LivePreviewLoop, "POLL_INTERVAL_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", fake_convert)

    loop = LivePreviewLoop(run_id="it", workspace=str(tmp_path), emit=fake_emit)
    await loop.start()
    try:
        deck = tmp_path / "deck.pptx"

        for i in range(3):
            version = i + 1
            # Each write must change size so the snapshot tuple (mtime, size) differs
            # even on filesystems with coarse mtime resolution.
            deck.write_bytes(b"X" * (10 + i))
            await _wait_for(lambda n=i + 1: len(fake_emit.events) >= n, timeout=2.5)
            # Small pause between edits so the poll loop registers each one.
            await asyncio.sleep(0.25)
    finally:
        await loop.stop()

    assert len(fake_emit.events) >= 3
    call_ids = {e["tool_call_id"] for e in fake_emit.events}
    assert call_ids == {"preview:deck.pptx"}
    # Each event's content should be distinct (different version bytes)
    contents = [base64.b64decode(e["result"]["content"]) for e in fake_emit.events[:3]]
    assert contents[0] != contents[1]
    assert contents[1] != contents[2]


@pytest.mark.asyncio
async def test_end_to_end_parallel_files_get_distinct_call_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Writing two different docs in parallel yields two distinct cards."""
    fake_emit = FakeEmit()

    async def fake_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return b"%PDF-1.4\n" + path.name.encode()

    monkeypatch.setattr(LivePreviewLoop, "POLL_INTERVAL_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", fake_convert)

    loop = LivePreviewLoop(run_id="it", workspace=str(tmp_path), emit=fake_emit)
    await loop.start()
    try:
        await asyncio.sleep(0.05)
        (tmp_path / "deck.pptx").write_bytes(b"slides")
        (tmp_path / "brief.docx").write_bytes(b"doc")

        await _wait_for(lambda: len({e["tool_call_id"] for e in fake_emit.events}) >= 2, timeout=2.5)
    finally:
        await loop.stop()

    call_ids = {e["tool_call_id"] for e in fake_emit.events}
    assert "preview:deck.pptx" in call_ids
    assert "preview:brief.docx" in call_ids


@pytest.mark.asyncio
async def test_end_to_end_stop_halts_further_events(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """After ``stop()``, writes to the workspace no longer produce events."""
    fake_emit = FakeEmit()

    async def fake_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return b"%PDF-1.4\nfake"

    monkeypatch.setattr(LivePreviewLoop, "POLL_INTERVAL_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", fake_convert)

    loop = LivePreviewLoop(run_id="it", workspace=str(tmp_path), emit=fake_emit)
    await loop.start()
    await asyncio.sleep(0.05)
    (tmp_path / "deck.pptx").write_bytes(b"before")
    await _wait_for(lambda: len(fake_emit.events) >= 1, timeout=2.0)
    events_at_stop = len(fake_emit.events)

    await loop.stop()

    # Mutate again after stop; there must be no new events.
    (tmp_path / "deck.pptx").write_bytes(b"after-stop-should-be-ignored")
    await asyncio.sleep(0.4)

    assert len(fake_emit.events) == events_at_stop
