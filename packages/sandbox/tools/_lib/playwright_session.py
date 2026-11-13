"""Playwright MCP session manager — persistent browser automation via Playwright MCP server.

Manages a Playwright MCP server subprocess (stdio transport) and provides:
- Lazy singleton lifecycle (start on first use, stop on browser_close)
- Tool invocation via MCP Python SDK
- Accessibility snapshot parsing with index→ref mapping
- Page state capture (snapshot + screenshot + metadata)
- Disk offloading for context compaction (page texts + screenshots)
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger("playwright_session")

# ── Directories for disk-offloaded content ───────────────────────────────────

_WORKSPACE = Path(
    os.getenv("WORKSPACE") or os.getenv("PROJECT_DIR") or os.getenv("SANDBOX_WORKSPACE_ROOT") or str(Path.home())
)
PAGE_TEXTS_DIR = _WORKSPACE / "page_texts"
SCREENSHOTS_DIR = _WORKSPACE / "screenshots"

# ── CDP ──────────────────────────────────────────────────────────────────────

CHROME_CDP_URL = os.getenv("CHROME_CDP_URL", "http://localhost:9222")


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class PageState:
    """Parsed state of the current browser page after an action."""

    title: str = ""
    url: str = ""
    screenshot_path: str = ""
    pixels_above: int = 0
    pixels_below: int = 0
    viewport_elements: str = ""  # formatted "index[:]info" block
    markdown_content: str = ""  # accessibility tree / page text
    page_text_path: str = ""
    char_count: int = 0


# ── Snapshot parsing ─────────────────────────────────────────────────────────

_REF_PATTERN = re.compile(r"\[ref=([\w]+)\]")


def parse_snapshot(snapshot_text: str) -> tuple[list[tuple[int, str]], dict[int, str]]:
    """Parse a Playwright MCP accessibility snapshot into indexed elements.

    Returns:
        (elements, ref_map) where:
        - elements is [(index, info_string), ...]
        - ref_map is {index: mcp_ref_string}
    """
    elements: list[tuple[int, str]] = []
    ref_map: dict[int, str] = {}
    index = 0

    for line in snapshot_text.splitlines():
        match = _REF_PATTERN.search(line)
        if not match:
            continue
        ref = match.group(1)
        # Strip tree indentation, bullets, and the [ref=...] tag
        info = line.strip().lstrip("- ")
        info = _REF_PATTERN.sub("", info).strip()
        if info:
            elements.append((index, info))
            ref_map[index] = ref
            index += 1

    return elements, ref_map


def format_elements(elements: list[tuple[int, str]]) -> str:
    """Format element list as 'index[:]info' lines for the spec response."""
    return "\n".join(f"{idx}[:]  {info}" for idx, info in elements)


# ── Snapshot header parsing ───────────────────────────────────────────────────

_URL_HEADER = re.compile(r"Page URL:\s*(.+)")
_TITLE_HEADER = re.compile(r"Page Title:\s*(.+)")


def parse_snapshot_header(snapshot_text: str) -> tuple[str, str]:
    """Extract title and URL from the Playwright MCP snapshot header.

    The snapshot text starts with a header block like:
        ### Page
        - Page URL: https://example.com/
        - Page Title: Example Domain
    """
    title = ""
    url = ""
    for line in snapshot_text.splitlines()[:15]:  # header is in first ~10 lines
        m = _TITLE_HEADER.search(line)
        if m:
            title = m.group(1).strip()
        m = _URL_HEADER.search(line)
        if m:
            url = m.group(1).strip()
        if title and url:
            break
    return title, url


def _extract_json_from_evaluate(text: str) -> dict:
    """Extract a JSON object from Playwright MCP's browser_evaluate response.

    The response is markdown-formatted like:
        ### Result
        "{\"scrollY\":0,\"scrollHeight\":800,\"viewportHeight\":600}"
        ### Ran Playwright code
        ...

    We need to find and parse the JSON within the quoted string.
    """
    for line in text.splitlines():
        line = line.strip().strip('"')
        if line.startswith("{"):
            try:
                return json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
    return {}


# ── Content extraction helpers ───────────────────────────────────────────────


def extract_text(content: list[Any]) -> str:
    """Extract the first text block from MCP tool result content."""
    for item in content:
        if getattr(item, "type", None) == "text":
            return item.text
    return ""


def extract_image_bytes(content: list[Any]) -> bytes | None:
    """Extract the first image as raw bytes from MCP tool result content."""
    for item in content:
        if getattr(item, "type", None) == "image":
            return base64.b64decode(item.data)
    return None


def extract_json(content: list[Any]) -> dict:
    """Extract JSON object from text content of an MCP tool result."""
    text = extract_text(content)
    if not text:
        return {}
    # Playwright MCP sometimes wraps the result — try to find JSON
    # The evaluate result may be just the JSON string directly
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try extracting JSON from within the text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


# ── Disk offloading ──────────────────────────────────────────────────────────


def _url_to_filename(url: str) -> str:
    """Convert a URL to a safe filename stem."""
    parsed = urlparse(url)
    domain = parsed.netloc.replace(":", "_").replace(".", "_") or "page"
    path_hash = hashlib.md5(url.encode()).hexdigest()[:8]
    return f"{domain}_{path_hash}"


def save_page_text(content: str, url: str) -> str:
    """Save page text to disk, return the file path."""
    PAGE_TEXTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{_url_to_filename(url)}.md"
    path = PAGE_TEXTS_DIR / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


def save_screenshot(data: bytes, name: str = "") -> str:
    """Save screenshot PNG to disk, return the file path."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = name or f"screenshot_{os.getpid()}"
    # Avoid collisions with a counter
    path = SCREENSHOTS_DIR / f"{stem}.png"
    counter = 1
    while path.exists():
        path = SCREENSHOTS_DIR / f"{stem}_{counter}.png"
        counter += 1
    path.write_bytes(data)
    return str(path)


# ── CDP availability check ───────────────────────────────────────────────────


def _is_cdp_available() -> bool:
    """Quick check whether Chrome CDP is reachable."""
    import urllib.error
    import urllib.request

    http_url = CHROME_CDP_URL.replace("ws://", "http://").replace("wss://", "https://")
    try:
        req = urllib.request.urlopen(f"{http_url}/json/version", timeout=2)
        req.close()
        return True
    except (urllib.error.URLError, OSError):
        return False


# ── Playwright browser discovery ──────────────────────────────────────────────


def _find_playwright_chromium() -> str | None:
    """Find the Playwright-bundled Chromium executable, if installed."""
    import glob

    cache_dir = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.isdir(cache_dir):
        return None

    # Look for chromium-*/chrome-linux64/chrome (Linux)
    candidates = glob.glob(os.path.join(cache_dir, "chromium-*/chrome-linux64/chrome"))
    if not candidates:
        # Fallback: headless shell
        candidates = glob.glob(os.path.join(cache_dir, "chromium_headless_shell-*/chrome-linux64/headless_shell"))
    if not candidates:
        return None

    # Return the newest version
    candidates.sort(reverse=True)
    path = candidates[0]
    return path if os.path.isfile(path) and os.access(path, os.X_OK) else None


# ── Playwright MCP Session ───────────────────────────────────────────────────


class PlaywrightMCPSession:
    """Singleton managing a Playwright MCP server subprocess.

    Lifecycle:
    - Lazy start on first ``ensure_started()`` call.
    - Persistent for the duration of the agent run.
    - Stopped explicitly via ``stop()`` (called by ``browser_close`` tool).

    **Chrome safety:** When connected via ``--cdp-endpoint``, the Playwright
    MCP server operates as a *client* of the existing Chrome instance.
    Stopping the MCP subprocess only tears down the MCP session and its
    Playwright browser context — it does NOT terminate the host Chrome
    process, which continues running for future sessions.

    The session communicates with the MCP server over stdio using the
    ``mcp`` Python SDK (``ClientSession`` + ``stdio_client``).
    """

    _instance: PlaywrightMCPSession | None = None

    def __init__(self) -> None:
        self._session: ClientSession | None = None
        self._started: bool = False
        self._ref_map: dict[int, str] = {}
        # Background task keeps stdio_client context alive in one task
        self._bg_task: asyncio.Task | None = None
        self._ready: asyncio.Event = asyncio.Event()
        self._shutdown: asyncio.Event = asyncio.Event()

    @classmethod
    def get(cls) -> PlaywrightMCPSession:
        """Return the singleton session, creating if needed."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Clear the singleton (testing / cleanup)."""
        cls._instance = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def ref_map(self) -> dict[int, str]:
        """Current index→ref mapping from the last snapshot parse."""
        return self._ref_map

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def ensure_started(self) -> ClientSession:
        """Start the MCP server if not already running, return session."""
        if self._started and self._session is not None:
            return self._session
        await self.start()
        assert self._session is not None
        return self._session

    async def _run_session(self, server_params: StdioServerParameters) -> None:
        """Background task: owns the stdio_client + ClientSession context.

        ``stdio_client`` uses anyio task groups internally and requires
        ``__aenter__`` / ``__aexit__`` to execute within the **same** async
        task.  This method satisfies that constraint by keeping both
        context managers open inside a single long-lived task.  External
        callers interact via ``self._session`` (set once ready) and signal
        shutdown via ``self._shutdown`` event.
        """
        try:
            async with stdio_client(server_params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    self._session = session
                    self._started = True
                    log.info("Playwright MCP server started successfully")
                    self._ready.set()
                    # Block until shutdown is requested
                    await self._shutdown.wait()
        except Exception as exc:
            log.error("Playwright MCP session crashed: %s", exc)
            self._session = None
            self._started = False
            self._ready.set()  # unblock waiters even on failure

    async def start(self) -> None:
        """Launch the Playwright MCP server subprocess."""
        if self._started:
            return

        args = [
            "@playwright/mcp@latest",
            "--headless",
            "--caps",
            "vision,devtools",
            "--no-sandbox",
        ]

        # Connect to existing Chrome via CDP if available
        if _is_cdp_available():
            ws_endpoint = CHROME_CDP_URL.replace("http://", "ws://")
            args.extend(["--cdp-endpoint", ws_endpoint])
            log.info("Playwright MCP: connecting to Chrome via CDP at %s", ws_endpoint)
        else:
            # No CDP — launch own browser.  Playwright MCP defaults to
            # Google Chrome which may not be installed.  Try to find
            # Playwright's bundled Chromium via --executable-path.
            chromium_path = _find_playwright_chromium()
            if chromium_path:
                args.extend(["--executable-path", chromium_path])
                log.info("Playwright MCP: using bundled Chromium at %s", chromium_path)
            else:
                log.info("Playwright MCP: launching with default browser (no CDP, no bundled Chromium)")

        server_params = StdioServerParameters(
            command="npx",
            args=args,
        )

        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._bg_task = asyncio.create_task(
            self._run_session(server_params),
            name="playwright-mcp-session",
        )

        # Wait for the session to be ready (or fail)
        await self._ready.wait()

        if not self._started:
            raise RuntimeError("Playwright MCP server failed to start")

    async def stop(self) -> None:
        """Stop the MCP server and clean up."""
        self._shutdown.set()
        if self._bg_task is not None:
            try:
                await asyncio.wait_for(self._bg_task, timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                self._bg_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._bg_task
            except Exception as exc:
                log.warning("Error stopping Playwright MCP: %s", exc)
            self._bg_task = None
        self._session = None
        self._started = False
        self._ref_map = {}
        PlaywrightMCPSession._instance = None
        log.info("Playwright MCP session stopped")

    # ── Tool invocation ──────────────────────────────────────────────────

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> list[Any]:
        """Call a Playwright MCP tool, return raw content items.

        Raises RuntimeError if the session is not started.
        """
        session = await self.ensure_started()
        result = await session.call_tool(name, arguments or {})
        if result.isError:
            error_text = extract_text(result.content)
            raise RuntimeError(f"Playwright MCP tool '{name}' failed: {error_text}")
        return result.content

    # ── Page state capture ───────────────────────────────────────────────

    async def get_page_state(self, snapshot_text: str | None = None) -> PageState:
        """Capture the full page state for a spec-format response.

        If ``snapshot_text`` is provided (from an action tool's response),
        it is reused instead of calling ``browser_snapshot`` again.

        Steps:
        1. Parse accessibility snapshot → elements + ref map
        2. Take screenshot → save to disk
        3. Get page metadata (title, URL, scroll) via JS evaluation
        4. Save page text to disk
        """
        # 1. Snapshot
        if snapshot_text is None:
            content = await self.call_tool("browser_snapshot")
            snapshot_text = extract_text(content)

        elements, ref_map = parse_snapshot(snapshot_text)
        self._ref_map = ref_map

        # 2. Screenshot
        try:
            ss_content = await self.call_tool("browser_take_screenshot", {"type": "png"})
            ss_bytes = extract_image_bytes(ss_content)
        except Exception as exc:
            log.warning("Screenshot failed: %s", exc)
            ss_bytes = None

        # 3. Page metadata — parse from snapshot header first, then JS for scroll
        title, url = parse_snapshot_header(snapshot_text)

        scroll_y = 0
        scroll_height = 0
        viewport_height = 0
        try:
            meta_content = await self.call_tool(
                "browser_evaluate",
                {
                    "function": (
                        "() => JSON.stringify({ "
                        "scrollY: Math.round(window.scrollY), "
                        "scrollHeight: document.documentElement.scrollHeight, "
                        "viewportHeight: window.innerHeight "
                        "})"
                    ),
                },
            )
            # browser_evaluate returns markdown-wrapped result — extract JSON from it
            meta_text = extract_text(meta_content)
            meta = _extract_json_from_evaluate(meta_text)
            scroll_y = meta.get("scrollY", 0)
            scroll_height = meta.get("scrollHeight", 0)
            viewport_height = meta.get("viewportHeight", 0)
        except Exception as exc:
            log.warning("Scroll metadata extraction failed: %s", exc)

        # 4. Save to disk (best-effort — never fail the page state capture)
        screenshot_path = ""
        if ss_bytes:
            try:
                screenshot_path = save_screenshot(ss_bytes, _url_to_filename(url))
            except OSError as exc:
                log.warning("Screenshot save failed: %s", exc)

        page_text_path = ""
        if snapshot_text.strip():
            try:
                page_text_path = save_page_text(snapshot_text, url)
            except OSError as exc:
                log.warning("Page text save failed: %s", exc)

        return PageState(
            title=title,
            url=url,
            screenshot_path=screenshot_path,
            pixels_above=scroll_y,
            pixels_below=max(0, scroll_height - scroll_y - viewport_height),
            viewport_elements=format_elements(elements),
            markdown_content=snapshot_text,
            page_text_path=page_text_path,
            char_count=len(snapshot_text),
        )

    # ── Convenience: ref lookup ──────────────────────────────────────────

    def ref_for_index(self, index: int) -> str | None:
        """Resolve a numeric element index to a Playwright MCP ref string."""
        return self._ref_map.get(index)
