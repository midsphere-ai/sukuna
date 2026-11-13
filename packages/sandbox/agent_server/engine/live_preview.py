"""Live document preview for officecli-built artifacts.

Per-run background task that mtime-polls the sandbox workspace, converts
any modified office / pdf / markdown files to a render the frontend can
display, and pushes synthetic ``tool_result`` events through the run's
``_emit`` closure using a stable ``callId`` so the frontend's toolCalls
store updates a single card in place rather than creating new ones.

Triggered from ``agent_server/engine/run.py`` via exo ``HookPoint.START`` /
``HookPoint.FINISHED`` / ``HookPoint.ERROR`` so the loop lives exactly as
long as the run does.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_PKG_BIN_DIR = Path(__file__).resolve().parents[2] / "tools" / "bin"

_BINARY_BY_SUFFIX: dict[str, str] = {
    ".pptx": "exo-pptx-to-pdf",
    ".ppt": "exo-pptx-to-pdf",
    ".docx": "exo-doc-to-pdf",
    ".doc": "exo-doc-to-pdf",
    ".odt": "exo-doc-to-pdf",
    ".rtf": "exo-doc-to-pdf",
    ".xlsx": "exo-xlsx-to-pdf",
    ".xls": "exo-xlsx-to-pdf",
    ".ods": "exo-xlsx-to-pdf",
}

_OFFICE_EXTS = frozenset(_BINARY_BY_SUFFIX)
_MARKDOWN_EXTS = frozenset({".md", ".markdown"})
_PDF_EXTS = frozenset({".pdf"})
_SUPPORTED_EXTS = _OFFICE_EXTS | _MARKDOWN_EXTS | _PDF_EXTS

# Directories whose contents must never trigger a preview render — either
# because we write into them (.preview), or because the churn is not
# user-facing (.git, .agent, __pycache__).
_IGNORED_DIR_PARTS: frozenset[str] = frozenset({".preview", ".git", ".agent", "__pycache__", "node_modules"})

# Emission shape
_TOOL_NAME = "artifact"

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


class LivePreviewLoop:
    """Watches the workspace, renders changed docs, emits artifact events.

    One instance per run. ``start`` seeds the mtime snapshot and kicks off
    the polling task; ``stop`` cancels everything gracefully.
    """

    POLL_INTERVAL_S: float = 1.0
    DEBOUNCE_S: float = 0.5
    CONVERT_TIMEOUT_S: float = 20.0
    MAX_PDF_BYTES: int = 1_500_000
    MAX_MARKDOWN_BYTES: int = 200_000

    def __init__(
        self,
        *,
        run_id: str,
        workspace: str | os.PathLike[str],
        emit: EmitFn,
    ) -> None:
        self._run_id = run_id
        self._workspace = Path(workspace)
        self._emit = emit
        self._snapshot: dict[str, tuple[float, int]] = {}
        self._pending: dict[str, asyncio.Task[None]] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    # ── lifecycle ────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._task is not None:
            return
        if not self._workspace.is_dir():
            log.debug("live_preview: workspace %s not a dir, skipping", self._workspace)
            return
        self._snapshot = self._mtime_snapshot()
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"live-preview:{self._run_id}")
        log.info("live_preview: started run_id=%s workspace=%s", self._run_id, self._workspace)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        for t in list(self._pending.values()):
            t.cancel()
        self._pending.clear()
        log.info("live_preview: stopped run_id=%s", self._run_id)

    # ── polling loop ─────────────────────────────────────────────────────

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.POLL_INTERVAL_S)
                    break  # stop requested
                except TimeoutError:
                    pass  # normal tick
                try:
                    curr = await asyncio.to_thread(self._mtime_snapshot)
                except Exception:
                    log.debug("live_preview: snapshot failed", exc_info=True)
                    continue
                for rel, stamp in curr.items():
                    if self._snapshot.get(rel) != stamp:
                        self._schedule(rel)
                self._snapshot = curr
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("live_preview: loop crashed", exc_info=True)

    def _mtime_snapshot(self) -> dict[str, tuple[float, int]]:
        """Return ``{rel_path: (mtime, size)}`` for supported files only.

        Directories listed in ``_IGNORED_DIR_PARTS`` are pruned recursively.
        Size is included in the key so edit-in-place writes that keep the
        mtime-but-change-size are still detected.
        """
        snap: dict[str, tuple[float, int]] = {}
        root = self._workspace
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _IGNORED_DIR_PARTS]
            for name in filenames:
                ext = Path(name).suffix.lower()
                if ext not in _SUPPORTED_EXTS:
                    continue
                fp = Path(dirpath) / name
                try:
                    st = fp.stat()
                except OSError:
                    continue
                try:
                    rel = str(fp.relative_to(root))
                except ValueError:
                    continue
                snap[rel] = (st.st_mtime, st.st_size)
        return snap

    # ── per-file debounce ────────────────────────────────────────────────

    def _schedule(self, rel: str) -> None:
        prev = self._pending.get(rel)
        if prev is not None and not prev.done():
            prev.cancel()
        self._pending[rel] = asyncio.create_task(
            self._render_after_debounce(rel),
            name=f"live-preview-debounce:{rel}",
        )

    async def _render_after_debounce(self, rel: str) -> None:
        my_task = asyncio.current_task()
        try:
            await asyncio.sleep(self.DEBOUNCE_S)
            await self._render_and_emit(rel)
        except asyncio.CancelledError:
            return
        except Exception:
            log.warning("live_preview: render %s failed", rel, exc_info=True)
        finally:
            # Only pop if we're still the current pending task for this file.
            # A newer _schedule() may have replaced us between entry and finally.
            if self._pending.get(rel) is my_task:
                self._pending.pop(rel, None)

    # ── render + emit ────────────────────────────────────────────────────

    async def _render_and_emit(self, rel: str) -> None:
        abs_path = self._workspace / rel
        if not abs_path.is_file():
            return  # deleted during debounce
        suffix = abs_path.suffix.lower()

        if suffix in _MARKDOWN_EXTS:
            try:
                text = await asyncio.to_thread(abs_path.read_text, encoding="utf-8", errors="replace")
            except OSError:
                return
            if len(text) > self.MAX_MARKDOWN_BYTES:
                text = text[: self.MAX_MARKDOWN_BYTES] + "\n\n*(truncated for preview)*"
            await self._emit_artifact(rel, "markdown", text, title=rel)
            return

        if suffix in _PDF_EXTS:
            try:
                pdf_bytes = await asyncio.to_thread(abs_path.read_bytes)
            except OSError:
                return
        elif suffix in _OFFICE_EXTS:
            pdf_bytes = await self._convert_to_pdf(abs_path)
            if pdf_bytes is None:
                return
        else:
            return

        if len(pdf_bytes) > self.MAX_PDF_BYTES:
            notice = (
                f"**{rel}** — document too large to preview inline "
                f"({len(pdf_bytes) // 1024} KB, cap {self.MAX_PDF_BYTES // 1024} KB).  "
                "Preview paused; the final file will still be delivered as an attachment."
            )
            await self._emit_artifact(rel, "markdown", notice, title=rel)
            return

        b64 = base64.b64encode(pdf_bytes).decode("ascii")
        await self._emit_artifact(rel, "pdf", b64, title=rel)

    async def _convert_to_pdf(self, path: Path) -> bytes | None:
        binary = _BINARY_BY_SUFFIX.get(path.suffix.lower())
        if binary is None:
            return None

        out_dir = self._workspace / ".preview"
        try:
            await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
        except OSError:
            return None
        out_path = out_dir / (path.stem + ".pdf")
        cmd = self._resolve_binary_cmd(binary) + [str(path), str(out_path)]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.warning("live_preview: %s not found on PATH or in tools/bin", binary)
            return None

        try:
            _, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=self.CONVERT_TIMEOUT_S)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            log.warning("live_preview: %s timed out on %s", binary, path.name)
            return None

        if proc.returncode != 0:
            log.debug(
                "live_preview: %s failed (rc=%s) on %s: %s",
                binary,
                proc.returncode,
                path.name,
                (stderr_b or b"").decode(errors="replace")[:200],
            )
            return None

        try:
            return await asyncio.to_thread(out_path.read_bytes)
        except OSError:
            return None

    @staticmethod
    def _resolve_binary_cmd(name: str) -> list[str]:
        """Return argv prefix for invoking one of the exo-*-to-pdf helpers.

        Prefer a PATH-resident wrapper (how the sandbox image ships them).
        Fall back to executing the source script under the current Python,
        which is what matters for local dev and pytest.
        """
        on_path = shutil.which(name)
        if on_path:
            return [on_path]
        local = _PKG_BIN_DIR / name
        if local.is_file():
            return [sys.executable, str(local)]
        return [name]  # will raise FileNotFoundError, caller handles it

    # ── emission ─────────────────────────────────────────────────────────

    async def _emit_artifact(
        self,
        rel: str,
        artifact_type: str,
        content: str,
        *,
        title: str,
    ) -> None:
        """Push a synthetic ``tool_result`` event via the run's ``_emit``.

        We deliberately skip the ``tool_call`` half of the pair so the
        billing path in ``run.py:530`` never fires for previews.  The
        frontend's tool_result handler in ``services/sse.ts`` creates a
        new ``toolCalls`` store entry when none exists for the callId,
        then updates it in place on every subsequent event.
        """
        call_id = f"preview:{rel}"
        artifact_id = call_id
        result_payload: dict[str, Any] = {
            "success": True,
            "message": "Live preview updated",
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "title": title,
            "content": content,
            "version": 1,
        }
        event = {
            "type": "tool_result",
            "tool_name": _TOOL_NAME,
            "tool_call_id": call_id,
            "call_id": call_id,
            "success": True,
            "result": result_payload,
            "arguments": {
                "action": "update",
                "artifact_type": artifact_type,
                "title": title,
                "artifact_id": artifact_id,
            },
            "_live_preview": True,
        }
        try:
            await self._emit(event)
        except Exception:
            log.warning("live_preview: emit failed for %s", rel, exc_info=True)
