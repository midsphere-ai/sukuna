"""Unit tests for LivePreviewLoop.

Covers the render/emit path and the polling-loop plumbing without
actually spawning subprocess calls to the ``exo-*-to-pdf`` helpers — the
``_convert_to_pdf`` method is monkey-patched to return fake PDF bytes so
tests run fast and don't depend on libreoffice being installed.
"""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from agent_server.engine.live_preview import LivePreviewLoop


class FakeEmit:
    """Async-callable that records every event pushed through it."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)


@pytest.fixture
def fake_emit() -> FakeEmit:
    return FakeEmit()


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def loop(workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch) -> LivePreviewLoop:
    """A loop wired to the tmp workspace, with PDF conversion stubbed."""

    async def fake_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return b"%PDF-1.4\nfake " + path.name.encode()

    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", fake_convert)
    return LivePreviewLoop(run_id="test-run", workspace=str(workspace), emit=fake_emit)


# ────────────────────────────────────────────────────────────────────────
# Render / emit
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emits_pdf_artifact_for_pptx(loop: LivePreviewLoop, workspace: Path, fake_emit: FakeEmit) -> None:
    (workspace / "deck.pptx").write_bytes(b"fake pptx bytes")
    await loop._render_and_emit("deck.pptx")

    assert len(fake_emit.events) == 1
    event = fake_emit.events[0]
    assert event["type"] == "tool_result"
    assert event["tool_name"] == "artifact"
    assert event["tool_call_id"] == "preview:deck.pptx"
    assert event["call_id"] == "preview:deck.pptx"
    assert event["_live_preview"] is True
    result = event["result"]
    assert result["artifact_type"] == "pdf"
    assert result["artifact_id"] == "preview:deck.pptx"
    assert result["title"] == "deck.pptx"
    # Content must be valid base64 encoding of our fake PDF
    decoded = base64.b64decode(result["content"])
    assert decoded.startswith(b"%PDF-1.4")


@pytest.mark.asyncio
async def test_stable_call_id_across_updates(loop: LivePreviewLoop, workspace: Path, fake_emit: FakeEmit) -> None:
    (workspace / "deck.pptx").write_bytes(b"v1")
    await loop._render_and_emit("deck.pptx")
    await loop._render_and_emit("deck.pptx")
    await loop._render_and_emit("deck.pptx")

    call_ids = {e["tool_call_id"] for e in fake_emit.events}
    assert call_ids == {"preview:deck.pptx"}
    assert len(fake_emit.events) == 3


@pytest.mark.asyncio
async def test_markdown_file_emits_markdown_artifact(
    loop: LivePreviewLoop, workspace: Path, fake_emit: FakeEmit
) -> None:
    (workspace / "notes.md").write_text("# Hello\n\nbody text", encoding="utf-8")
    await loop._render_and_emit("notes.md")

    assert len(fake_emit.events) == 1
    result = fake_emit.events[0]["result"]
    assert result["artifact_type"] == "markdown"
    assert "# Hello" in result["content"]
    assert fake_emit.events[0]["tool_call_id"] == "preview:notes.md"


@pytest.mark.asyncio
async def test_pdf_file_is_served_directly(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A raw .pdf dropped into the workspace should bypass conversion."""

    async def _should_not_call(self: LivePreviewLoop, path: Path) -> bytes | None:
        raise AssertionError("_convert_to_pdf should not be called for .pdf files")

    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", _should_not_call)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)
    (workspace / "final.pdf").write_bytes(b"%PDF-1.4\nreal pdf")
    await loop._render_and_emit("final.pdf")

    assert len(fake_emit.events) == 1
    result = fake_emit.events[0]["result"]
    assert result["artifact_type"] == "pdf"
    assert base64.b64decode(result["content"]).startswith(b"%PDF-1.4")


@pytest.mark.asyncio
async def test_over_cap_emits_markdown_notice(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def big_convert(self: LivePreviewLoop, path: Path) -> bytes:
        return b"X" * (LivePreviewLoop.MAX_PDF_BYTES + 1)

    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", big_convert)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)
    (workspace / "huge.pptx").write_bytes(b"fake")

    await loop._render_and_emit("huge.pptx")

    assert len(fake_emit.events) == 1
    result = fake_emit.events[0]["result"]
    assert result["artifact_type"] == "markdown"
    assert "too large" in result["content"].lower()
    # Stable call id even for the over-cap fallback
    assert fake_emit.events[0]["tool_call_id"] == "preview:huge.pptx"


@pytest.mark.asyncio
async def test_render_skips_missing_file(loop: LivePreviewLoop, fake_emit: FakeEmit) -> None:
    # File was deleted during debounce window
    await loop._render_and_emit("gone.pptx")
    assert fake_emit.events == []


@pytest.mark.asyncio
async def test_convert_returns_none_emits_nothing(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_convert(self: LivePreviewLoop, path: Path) -> bytes | None:
        return None

    monkeypatch.setattr(LivePreviewLoop, "_convert_to_pdf", failing_convert)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)
    (workspace / "deck.pptx").write_bytes(b"fake")

    await loop._render_and_emit("deck.pptx")
    assert fake_emit.events == []


# ────────────────────────────────────────────────────────────────────────
# Snapshot filtering
# ────────────────────────────────────────────────────────────────────────


def test_snapshot_includes_supported_extensions(loop: LivePreviewLoop, workspace: Path) -> None:
    (workspace / "deck.pptx").write_bytes(b"a")
    (workspace / "brief.docx").write_bytes(b"a")
    (workspace / "model.xlsx").write_bytes(b"a")
    (workspace / "final.pdf").write_bytes(b"a")
    (workspace / "notes.md").write_text("a")

    snap = loop._mtime_snapshot()
    names = set(snap.keys())
    assert "deck.pptx" in names
    assert "brief.docx" in names
    assert "model.xlsx" in names
    assert "final.pdf" in names
    assert "notes.md" in names


def test_snapshot_excludes_unsupported_extensions(loop: LivePreviewLoop, workspace: Path) -> None:
    (workspace / "random.txt").write_text("noise")
    (workspace / "script.py").write_text("x = 1")
    (workspace / "image.png").write_bytes(b"\x89PNG")

    snap = loop._mtime_snapshot()
    assert snap == {}


def test_snapshot_ignores_shadow_preview_dir(loop: LivePreviewLoop, workspace: Path) -> None:
    shadow = workspace / ".preview"
    shadow.mkdir()
    (shadow / "cached.pdf").write_bytes(b"%PDF-1.4")
    (workspace / "real.pptx").write_bytes(b"real")

    snap = loop._mtime_snapshot()
    assert "real.pptx" in snap
    assert not any(rel.startswith(".preview") for rel in snap)


def test_snapshot_ignores_git_and_agent_dirs(loop: LivePreviewLoop, workspace: Path) -> None:
    (workspace / ".git").mkdir()
    (workspace / ".git" / "cached.md").write_text("secret")
    (workspace / ".agent").mkdir()
    (workspace / ".agent" / "context.md").write_text("agent note")

    snap = loop._mtime_snapshot()
    assert snap == {}


# ────────────────────────────────────────────────────────────────────────
# Debounce coalescing
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_debounce_coalesces_rapid_schedules(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    render_count = 0

    async def counted(self: LivePreviewLoop, rel: str) -> None:
        nonlocal render_count
        render_count += 1

    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.1)
    monkeypatch.setattr(LivePreviewLoop, "_render_and_emit", counted)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)

    # Schedule 5 rapid changes, each 10 ms apart — well under the 100 ms debounce
    for _ in range(5):
        loop._schedule("deck.pptx")
        await asyncio.sleep(0.01)
    # Wait for the debounce to settle
    await asyncio.sleep(0.2)

    assert render_count == 1
    # No leftover pending tasks
    assert loop._pending == {}


@pytest.mark.asyncio
async def test_debounce_separates_distinct_files(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    renders: list[str] = []

    async def track(self: LivePreviewLoop, rel: str) -> None:
        renders.append(rel)

    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.05)
    monkeypatch.setattr(LivePreviewLoop, "_render_and_emit", track)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)

    loop._schedule("a.pptx")
    loop._schedule("b.docx")
    loop._schedule("c.xlsx")
    await asyncio.sleep(0.15)

    assert sorted(renders) == ["a.pptx", "b.docx", "c.xlsx"]


# ────────────────────────────────────────────────────────────────────────
# Lifecycle
# ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stop_cancels_pending_debouncers(
    workspace: Path, fake_emit: FakeEmit, monkeypatch: pytest.MonkeyPatch
) -> None:
    renders: list[str] = []

    async def track(self: LivePreviewLoop, rel: str) -> None:
        renders.append(rel)

    monkeypatch.setattr(LivePreviewLoop, "DEBOUNCE_S", 0.5)
    monkeypatch.setattr(LivePreviewLoop, "_render_and_emit", track)
    loop = LivePreviewLoop(run_id="t", workspace=str(workspace), emit=fake_emit)

    loop._schedule("a.pptx")
    await asyncio.sleep(0.05)  # still inside debounce
    await loop.stop()
    await asyncio.sleep(0.6)  # would have fired if not cancelled

    assert renders == []
    assert loop._pending == {}


@pytest.mark.asyncio
async def test_start_on_missing_workspace_is_noop(tmp_path: Path, fake_emit: FakeEmit) -> None:
    missing = tmp_path / "does-not-exist"
    loop = LivePreviewLoop(run_id="t", workspace=str(missing), emit=fake_emit)
    await loop.start()
    assert loop._task is None
    await loop.stop()
