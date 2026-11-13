"""Browser automation tools — 15 individual Playwright MCP-backed tools for PTC mode.

Each tool wraps one or more Playwright MCP server calls and returns a
compaction-friendly response.

Context compaction design:
- Tier 1 (immediate): Full page content saved to disk, result includes path reference.
- Tier 2 (compact): ``COMPACT_REGISTRY`` keeps essential args; pointer builder
  replaces the full output with a restorable reference.
- Tier 3 (summarize): Compact pointers feed naturally into trajectory summaries.

All tools return ``{"success": bool, "output": str, ...}`` where ``output``
matches the spec format.  On failure, ``hint`` provides actionable guidance
to the agent for recovery.

NOTE: The ``brief`` parameter from the spec is handled by the exo framework's
injected tool args (``brief``), so it is NOT declared on any tool signature
here.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Annotated, Literal

__version__ = "0.1.0"

# Silence noisy third-party loggers without reconfiguring the root logger
# (force=True was nuking root handlers and setting level=WARNING, which
# swallowed INFO messages from agent_server and other top-level loggers).
logging.getLogger("playwright").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

from _lib.playwright_session import (
    PlaywrightMCPSession,
    extract_image_bytes,
    extract_text,
    parse_snapshot_header,
)
from _lib.utils import error_result, success_result
from exo import tool

log = logging.getLogger("browse")

# ── Timeout for individual MCP calls (seconds) ──────────────────────────────
_MCP_CALL_TIMEOUT = 30
_NAVIGATE_TIMEOUT = 60

# ── Default browser viewport (matches --viewport-size in session start) ──────
_DEFAULT_VP_WIDTH = 1280
_DEFAULT_VP_HEIGHT = 800


# ── Shared helpers ───────────────────────────────────────────────────────────


def _session() -> PlaywrightMCPSession:
    """Return the singleton Playwright MCP session."""
    return PlaywrightMCPSession.get()


def _workspace_root() -> str:
    return os.getenv("WORKSPACE") or os.getenv("PROJECT_DIR") or os.getenv("SANDBOX_WORKSPACE_ROOT") or str(Path.home())


async def _safe_call(name: str, args: dict | None = None, timeout: int = _MCP_CALL_TIMEOUT) -> list:
    """Call a Playwright MCP tool with timeout and auto-recovery."""
    import asyncio

    session = _session()
    try:
        return await asyncio.wait_for(
            session.call_tool(name, args),
            timeout=timeout,
        )
    except TimeoutError:
        raise RuntimeError(f"Playwright MCP call '{name}' timed out after {timeout}s")
    except (ConnectionError, BrokenPipeError, OSError) as exc:
        log.warning("MCP session appears dead (%s), attempting restart...", exc)
        await session.stop()
        PlaywrightMCPSession.reset()
        session = _session()
        return await asyncio.wait_for(
            session.call_tool(name, args),
            timeout=timeout,
        )


def _normalize_coords(
    x: float,
    y: float,
    viewport_width: float | None,
    viewport_height: float | None,
) -> tuple[float, float]:
    """Scale agent-provided coordinates to the actual browser viewport.

    The agent may report coordinates relative to a viewport of
    (viewport_width × viewport_height).  If the actual browser viewport
    differs, we scale proportionally.
    """
    vw = viewport_width or _DEFAULT_VP_WIDTH
    vh = viewport_height or _DEFAULT_VP_HEIGHT
    scale_x = _DEFAULT_VP_WIDTH / vw
    scale_y = _DEFAULT_VP_HEIGHT / vh
    return round(x * scale_x, 1), round(y * scale_y, 1)


async def _page_state_output(action_summary: str, snapshot_text: str | None = None) -> dict:
    """Run a full page state capture and format the spec response."""
    try:
        state = await _session().get_page_state(snapshot_text=snapshot_text)
    except Exception as exc:
        log.warning("Page state capture failed: %s", exc)
        return success_result(
            action_summary,
            output=f"{action_summary}\n[Warning: Could not capture page state: {exc}]",
            hint="The browser action succeeded but page state could not be read. Try browser_view to refresh.",
        )

    saved_notice = ""
    if state.page_text_path:
        saved_notice = (
            f"\n\nFull markdown content with {state.char_count} chars of this page "
            f"has been saved to {state.page_text_path}, prefer to read it if it's "
            f"a text based webpage."
        )

    inline_md = state.markdown_content
    if len(inline_md) > 4000:
        inline_md = inline_md[:4000] + "\n... [truncated, read full content from file]"

    output = (
        f"{action_summary}{saved_notice}\n"
        f"---\n"
        f"Title: {state.title}\n"
        f"URL: {state.url}\n"
        f"Clean screenshot path: {state.screenshot_path}\n"
        f"Pixels above viewport: {state.pixels_above}\n"
        f"Pixels below viewport: {state.pixels_below}\n"
        f"---\n"
        f"Viewport elements (index[:]info):\n"
        f"{state.viewport_elements}\n"
        f"---\n"
        f"Extracted page content in markdown:\n"
        f"{inline_md}"
    )
    return success_result(action_summary, output=output)


def _validate_url(url: str) -> str | None:
    if not url or not url.strip():
        return "URL cannot be empty."
    if not url.startswith(("http://", "https://", "file://")):
        return "URL must include a protocol prefix (http://, https://, or file://)."
    return None


def _resolve_ref(index: int) -> tuple[str | None, dict | None]:
    session = _session()
    ref = session.ref_for_index(index)
    if ref is None:
        return None, error_result(
            f"Element index {index} not found in current viewport snapshot.",
            hint=(
                f"Index {index} is not in the current snapshot. "
                "Call browser_view first to refresh the element list, then use "
                "a valid index from the 'Viewport elements' section."
            ),
        )
    return ref, None


# ── 1. browser (gateway — triggers injection of all other browser tools) ─────


@tool(name="browser")
async def browser(
    url: Annotated[str, "The URL to navigate to. Must include protocol prefix (e.g., https:// or file://)."],
    intent: Annotated[
        Literal["navigational", "informational", "transactional"],
        "The purpose of visiting this URL. Helps to determine how to handle the page.",
    ],
    focus: Annotated[
        str | None,
        "(Required if intent is informational) Specific topic, section, or question to focus on when visiting the page. Helps guide reading and extraction efforts toward the most relevant content.",
    ] = None,
) -> dict:
    """Navigate the browser to a specified URL to begin web browsing session.

    <instructions>
    - Use this tool to start browser interactions and navigate to web pages.
    - After starting browser, you'll have access to more browser-related tools.
    - MUST use browser tools to access and interpret all URLs provided directly by the user.
    - From search results, MUST access multiple URLs that appear relevant to the task.
    - The browser maintains login state across tasks, MUST open the corresponding webpage first to check login status before assuming authentication state.
    </instructions>

    <recommended_usage>
    - Use when URLs are provided directly by the user.
    - Use to navigate to search results from search tools.
    - Use to visit specific web pages for information gathering.
    - Use to access web applications or services.
    </recommended_usage>
    """
    url_err = _validate_url(url)
    if url_err:
        return error_result(url_err, hint="Provide a full URL including the scheme, e.g. 'https://example.com'.")

    try:
        await _safe_call("browser_navigate", {"url": url}, timeout=_NAVIGATE_TIMEOUT)
        return await _page_state_output(f"Navigated to {url}")
    except RuntimeError as exc:
        return error_result(
            f"Navigation to {url} failed: {exc}",
            hint="The page may be unreachable, or the URL may be incorrect. "
            "Verify the URL is valid and the server is responsive. "
            "If the Playwright MCP server crashed, try again — it auto-restarts.",
        )
    except Exception as exc:
        return error_result(
            f"Navigation to {url} failed: {exc}", hint="An unexpected error occurred. Check the URL and try again."
        )


# ── 2. browser_view ──────────────────────────────────────────────────────────


@tool(name="browser_view")
async def browser_view() -> dict:
    """View the current content of the browser page.

    <instructions>
    - Page content is automatically provided after navigation to a URL, no need to use this tool specifically.
    - This tool is primarily for checking the updated state of previously opened pages after some time.
    - Can be used repeatedly to wait and monitor completion status of operations in web applications.
    - When opening large pages or PDFs, use this tool to wait for complete loading if blank content is encountered.
    </instructions>

    <recommended_usage>
    - Use when waiting for pages to fully load.
    - Use when checking the latest state of previously opened pages.
    - Use when monitoring progress of operations.
    - Use before using other tools that require element index numbers.
    </recommended_usage>
    """
    try:
        content = await _safe_call("browser_snapshot")
        snapshot_text = extract_text(content)
        _title, url = parse_snapshot_header(snapshot_text)
        return await _page_state_output(
            f"Attempted to view browser at {url or 'unknown'}",
            snapshot_text=snapshot_text,
        )
    except RuntimeError as exc:
        return error_result(
            f"Failed to capture page state: {exc}",
            hint="The browser may not have a page loaded. Use browser first to open a URL, then call browser_view.",
        )
    except Exception as exc:
        return error_result(
            f"Failed to capture page state: {exc}", hint="Try browser to navigate to a URL first if no page is loaded."
        )


# ── 3. browser_click ─────────────────────────────────────────────────────────


@tool(name="browser_click")
async def browser_click(
    index: Annotated[int | None, "(Required if using element index) Index number of the element to click."] = None,
    coordinate_x: Annotated[
        float | None,
        "(Required if using coordinates) Horizontal coordinate of click position, relative to the left edge of the viewport.",
    ] = None,
    coordinate_y: Annotated[
        float | None,
        "(Required if using coordinates) Vertical coordinate of click position, relative to the top edge of the viewport.",
    ] = None,
    viewport_width: Annotated[
        float | None,
        "(Required if using coordinates) Horizontal size (width) of the viewport as perceived from the rendered screenshot.",
    ] = None,
    viewport_height: Annotated[
        float | None,
        "(Required if using coordinates) Vertical size (height) of the viewport as perceived from the rendered screenshot.",
    ] = None,
) -> dict:
    """Click an element on the browser page.

    <instructions>
    - Ensure target element is visible and clickable before clicking.
    - Must provide either element index or coordinates.
    - Prefer using element index over coordinates when available.
    </instructions>

    <recommended_usage>
    - Use when clicking page elements is needed.
    - Use when triggering page interactions.
    - Use when submitting forms.
    </recommended_usage>
    """
    if index is None and (coordinate_x is None or coordinate_y is None):
        return error_result(
            "Missing click target: provide either 'index' or both 'coordinate_x' and 'coordinate_y'.",
            hint="Use 'index' from browser_view's element list, or provide x/y coordinates.",
        )

    try:
        if index is not None:
            ref, err = _resolve_ref(index)
            if err:
                return err
            content = await _safe_call("browser_click", {"ref": ref})
            snapshot = extract_text(content)
            return await _page_state_output(f"Attempted to click element {index}", snapshot_text=snapshot or None)
        else:
            nx, ny = _normalize_coords(coordinate_x, coordinate_y, viewport_width, viewport_height)
            content = await _safe_call("browser_mouse_click_xy", {"x": nx, "y": ny})
            snapshot = extract_text(content)
            return await _page_state_output(
                f"Attempted to click at ({coordinate_x}, {coordinate_y})", snapshot_text=snapshot or None
            )
    except RuntimeError as exc:
        target = f"element {index}" if index is not None else f"({coordinate_x}, {coordinate_y})"
        return error_result(
            f"Click on {target} failed: {exc}",
            hint="The element may have moved or is no longer in the viewport. Call browser_view to refresh the snapshot, then retry with the updated index.",
        )
    except Exception as exc:
        return error_result(f"Click failed: {exc}", hint="Try browser_view to refresh element indices, then retry.")


# ── 4. browser_input ─────────────────────────────────────────────────────────


@tool(name="browser_input")
async def browser_input(
    text: Annotated[
        str, "Full text content to input into the target element. This will overwrite any existing content."
    ],
    press_enter: Annotated[bool, "Whether to simulate pressing the Enter key after input."],
    index: Annotated[
        int | None, "(Required if using element index) Index number of the element to clear and input text into."
    ] = None,
    coordinate_x: Annotated[
        float | None,
        "(Required if using coordinates) Horizontal coordinate of the element to clear and input text into, relative to the left edge of the viewport.",
    ] = None,
    coordinate_y: Annotated[
        float | None,
        "(Required if using coordinates) Vertical coordinate of the element to clear and input text into, relative to the top edge of the viewport.",
    ] = None,
    viewport_width: Annotated[
        float | None,
        "(Required if using coordinates) Horizontal size (width) of the viewport as perceived from the rendered screenshot.",
    ] = None,
    viewport_height: Annotated[
        float | None,
        "(Required if using coordinates) Vertical size (height) of the viewport as perceived from the rendered screenshot.",
    ] = None,
) -> dict:
    """Overwrite text in an editable field on the browser page.

    <instructions>
    - This tool first clears existing text in target element, then inputs new text.
    - Ensure target element is editable.
    - Must provide either element index or coordinates.
    - Prefer using element index over coordinates when available.
    - Decide whether to press Enter key based on needs.
    </instructions>

    <recommended_usage>
    - Use when filling content in input fields.
    - Use when updating form fields.
    </recommended_usage>
    """
    if index is None and (coordinate_x is None or coordinate_y is None):
        return error_result(
            "Missing input target: provide either 'index' or both 'coordinate_x' and 'coordinate_y'.",
            hint="Use 'index' from browser_view's element list for text inputs, or provide x/y coordinates.",
        )

    try:
        if index is not None:
            ref, err = _resolve_ref(index)
            if err:
                return err
            content = await _safe_call("browser_type", {"ref": ref, "text": text, "submit": press_enter})
        else:
            nx, ny = _normalize_coords(coordinate_x, coordinate_y, viewport_width, viewport_height)
            await _safe_call("browser_mouse_click_xy", {"x": nx, "y": ny})
            content = await _safe_call("browser_type", {"ref": "", "text": text, "submit": press_enter})

        target = f"element {index}" if index is not None else f"({coordinate_x}, {coordinate_y})"
        enter_note = " and pressed Enter" if press_enter else ""
        snapshot = extract_text(content)
        return await _page_state_output(
            f'Attempted to input "{text}" into {target}{enter_note}', snapshot_text=snapshot or None
        )
    except RuntimeError as exc:
        return error_result(
            f"Input failed: {exc}",
            hint="The target element may not be editable or may have moved. Call browser_view to refresh, then use the correct index for a text input or textarea.",
        )
    except Exception as exc:
        return error_result(
            f"Input failed: {exc}",
            hint="Verify the target is an editable field. Use browser_view to check available elements.",
        )


# ── 5. browser_scroll ────────────────────────────────────────────────────────


@tool(name="browser_scroll")
async def browser_scroll(
    target: Annotated[
        Literal["page", "container"],
        "The target to scroll. 'page' for the entire page, 'container' for a specific scrollable element at the given coordinates.",
    ],
    direction: Annotated[Literal["up", "down", "left", "right"], "The direction to scroll."],
    to_end: Annotated[
        bool,
        "Whether to scroll to the end (top/bottom/leftmost/rightmost) of the target instead of 1x viewport/container size. Defaults to false.",
    ] = False,
    coordinate_x: Annotated[
        float | None,
        "(Required if target is container) Horizontal coordinate of the container element to scroll, relative to the left edge of the viewport.",
    ] = None,
    coordinate_y: Annotated[
        float | None,
        "(Required if target is container) Vertical coordinate of the container element to scroll, relative to the top edge of the viewport.",
    ] = None,
    viewport_width: Annotated[
        float | None,
        "(Required if target is container) Horizontal size (width) of the viewport as perceived from the rendered screenshot.",
    ] = None,
    viewport_height: Annotated[
        float | None,
        "(Required if target is container) Vertical size (height) of the viewport as perceived from the rendered screenshot.",
    ] = None,
) -> dict:
    """Scroll the browser page or a specific container element.

    <instructions>
    - `direction` refers to the content viewing direction: `down` scrolls to view content below the current viewport.
    - By default, scrolls 1x viewport/container size; use `to_end` to scroll directly to the top/bottom/leftmost/rightmost.
    - When specifying a container element, coordinates can be any point within the element, center point recommended.
    - MUST actively save key information to text files after every two scroll operations, especially information from images and tables.
    - Multiple scrolls may be needed to gather sufficient information if markdown extraction is incomplete or page contains rich visual elements.
    </instructions>

    <recommended_usage>
    - Use when needing to view off-screen content.
    - Use when markdown extraction is incomplete or page has rich visual elements.
    - Use when dealing with pages that have dynamic loading.
    </recommended_usage>
    """
    if target == "container" and (coordinate_x is None or coordinate_y is None):
        return error_result(
            "Container scroll requires 'coordinate_x' and 'coordinate_y' to identify the container.",
            hint="Provide the x/y coordinates of the scrollable container element.",
        )

    try:
        delta_map = {"up": (0, -600), "down": (0, 600), "left": (-600, 0), "right": (600, 0)}
        dx, dy = delta_map[direction]

        if to_end:
            dx = dx * 100 if dx else 0
            dy = dy * 100 if dy else 0

        if target == "container" and coordinate_x is not None and coordinate_y is not None:
            nx, ny = _normalize_coords(coordinate_x, coordinate_y, viewport_width, viewport_height)
            await _safe_call("browser_mouse_move_xy", {"x": nx, "y": ny})

        await _safe_call("browser_mouse_wheel", {"deltaX": dx, "deltaY": dy})

        target_type = "html" if target == "page" else "container"
        return await _page_state_output(
            f"Attempted to scroll {direction} one viewport on {target_type} (target={target}, direction={direction})",
        )
    except RuntimeError as exc:
        return error_result(
            f"Scroll failed: {exc}", hint="The page may not be scrollable or the browser may not have a page loaded."
        )
    except Exception as exc:
        return error_result(f"Scroll failed: {exc}", hint="Ensure a page is loaded with browser before scrolling.")


# ── 6. browser_move_mouse ────────────────────────────────────────────────────


@tool(name="browser_move_mouse")
async def browser_move_mouse(
    coordinate_x: Annotated[
        float,
        "Horizontal coordinate of target cursor position, relative to the left edge of the viewport. Must be between 0 and viewport_width.",
    ],
    coordinate_y: Annotated[
        float,
        "Vertical coordinate of target cursor position, relative to the top edge of the viewport. Must be between 0 and viewport_height.",
    ],
    viewport_width: Annotated[
        float,
        "Horizontal size (width) of the viewport as perceived from the rendered screenshot. Used to normalize horizontal coordinates.",
    ],
    viewport_height: Annotated[
        float,
        "Vertical size (height) of the viewport as perceived from the rendered screenshot. Used to normalize vertical coordinates.",
    ],
) -> dict:
    """Move the cursor to a specified position on the browser page.

    <instructions>
    - For clicking, use `browser_click` tool directly without moving cursor first.
    - Use coordinates to specify the exact cursor position.
    </instructions>

    <recommended_usage>
    - Use when simulating user mouse movement.
    - Use when triggering hover effects.
    </recommended_usage>
    """
    try:
        nx, ny = _normalize_coords(coordinate_x, coordinate_y, viewport_width, viewport_height)
        await _safe_call("browser_mouse_move_xy", {"x": nx, "y": ny})
        return success_result(
            f"Mouse moved to X: {coordinate_x}, Y: {coordinate_y}",
            output=f"Mouse moved to X: {coordinate_x}, Y: {coordinate_y}",
        )
    except RuntimeError as exc:
        return error_result(
            f"Mouse move failed: {exc}",
            hint="Ensure the browser has a page loaded. Coordinates must be within the viewport.",
        )
    except Exception as exc:
        return error_result(
            f"Mouse move failed: {exc}", hint="Check that coordinates are valid numbers within the viewport dimensions."
        )


# ── 7. browser_press_key ─────────────────────────────────────────────────────


@tool(name="browser_press_key")
async def browser_press_key(
    key: Annotated[
        str,
        'Name of the key to simulate. Use standard key names (e.g., "Enter", "Tab", "ArrowUp"). To simulate key combinations, use "+" (e.g., "Control+Enter", "Shift+Tab").',
    ],
) -> dict:
    """Simulate a key press on the browser page.

    <instructions>
    - Use standard key names.
    - Use plus sign to connect combination keys.
    </instructions>

    <recommended_usage>
    - Use when specific keyboard operations are needed.
    - Use when keyboard shortcuts need to be triggered.
    </recommended_usage>
    """
    if not key or not key.strip():
        return error_result(
            "Key name cannot be empty.",
            hint="Provide a valid key name: 'Enter', 'Tab', 'Escape', 'Control+a', 'ArrowDown', etc.",
        )

    try:
        content = await _safe_call("browser_press_key", {"key": key})
        snapshot = extract_text(content)
        return await _page_state_output(f"Attempted to press key: {key}", snapshot_text=snapshot or None)
    except RuntimeError as exc:
        return error_result(
            f"Key press '{key}' failed: {exc}",
            hint=f"Key '{key}' may not be a valid key name. Use standard key names: Enter, Tab, Escape, Backspace, ArrowUp, ArrowDown, Control+c, Shift+Tab, etc.",
        )
    except Exception as exc:
        return error_result(f"Key press failed: {exc}", hint="Ensure a page is loaded and try a standard key name.")


# ── 8. browser_select_option ─────────────────────────────────────────────────


@tool(name="browser_select_option")
async def browser_select_option(
    index: Annotated[int, "Index number of the dropdown element to operate on."],
    option_index: Annotated[int, "Index of the option to select within the dropdown list, starting from 0."],
) -> dict:
    """Select an option from a dropdown menu on the browser page.

    <instructions>
    - Ensure dropdown list is interactive and visible.
    - Use the dropdown element index and option index to make selections.
    </instructions>

    <recommended_usage>
    - Use when selecting dropdown menu options.
    - Use when setting form select fields.
    </recommended_usage>
    """
    ref, err = _resolve_ref(index)
    if err:
        return err

    try:
        content = await _safe_call("browser_select_option", {"ref": ref, "values": [str(option_index)]})
        snapshot = extract_text(content)
        return await _page_state_output(
            f"Attempted to select option {option_index} from element {index}", snapshot_text=snapshot or None
        )
    except RuntimeError as exc:
        return error_result(
            f"Select option failed: {exc}",
            hint=f"Element {index} may not be a <select> dropdown, or option index {option_index} may be out of range. Call browser_view to inspect the element.",
        )
    except Exception as exc:
        return error_result(
            f"Select option failed: {exc}", hint="Verify the element is a dropdown and the option index is valid."
        )


# ── 9. browser_save_image ────────────────────────────────────────────────────


@tool(name="browser_save_image")
async def browser_save_image(
    save_dir: Annotated[str, "Absolute path to the local directory where the image will be saved."],
    base_name: Annotated[
        str,
        'Base name (stem) for the image file, without extension. e.g., "apollo_11_landing_site", "albert_einstein_portrait". The final file name will automatically include the appropriate extension based on image format.',
    ],
    coordinate_x: Annotated[
        float,
        "Horizontal coordinate of the image element to be saved, relative to the left edge of the viewport. Must be between 0 and viewport_width.",
    ],
    coordinate_y: Annotated[
        float,
        "Vertical coordinate of the image element to be saved, relative to the top edge of the viewport. Must be between 0 and viewport_height.",
    ],
    viewport_width: Annotated[
        float,
        "Horizontal size (width) of the viewport as perceived from the rendered screenshot. Used to normalize horizontal coordinates.",
    ],
    viewport_height: Annotated[
        float,
        "Vertical size (height) of the viewport as perceived from the rendered screenshot. Used to normalize vertical coordinates.",
    ],
) -> dict:
    """Save an image from the browser page to a local file.

    <instructions>
    - Coordinates can be any point within the image element, center point recommended.
    - Set save directory to corresponding working directory when saving images as assets to avoid extra copying.
    - Base name should be semantic and human-readable, avoid special characters or spaces.
    - Extension will be added automatically based on image format, no need to include in base name.
    - Final save path is determined by `save_dir`, `base_name`, and image format, will be returned in result.
    </instructions>

    <recommended_usage>
    - Use when downloading images from web pages.
    - Use when saving assets for websites, documents, or presentations.
    - Use when saving references for image or video generation.
    </recommended_usage>
    """
    if not save_dir or not save_dir.strip():
        return error_result(
            "save_dir cannot be empty.",
            hint=f"Provide an absolute path for the output directory, e.g. '{_workspace_root()}/images'.",
        )
    if not base_name or not base_name.strip():
        return error_result(
            "base_name cannot be empty.", hint="Provide a filename stem without extension, e.g. 'screenshot_1'."
        )

    try:
        import io
        from pathlib import Path as _Path

        from PIL import Image

        nx, ny = _normalize_coords(coordinate_x, coordinate_y, viewport_width, viewport_height)

        # Try element-specific screenshot via JS element detection
        ss_bytes = None
        try:
            # Find the nearest interactive/visual element at the coordinates
            # and get its ref from the snapshot for an element-specific screenshot
            eval_content = await _safe_call(
                "browser_evaluate",
                {
                    "function": (
                        f"() => JSON.stringify((() => {{"
                        f"  const el = document.elementFromPoint({nx}, {ny});"
                        f"  if (!el) return null;"
                        f"  const rect = el.getBoundingClientRect();"
                        f"  return {{ tag: el.tagName, w: Math.round(rect.width), h: Math.round(rect.height) }};"
                        f"}})())"
                    ),
                },
            )
            elem_info = extract_text(eval_content)
            # If element found, take a targeted screenshot at those coordinates
            if elem_info and "null" not in elem_info:
                ss_content = await _safe_call(
                    "browser_take_screenshot",
                    {
                        "type": "png",
                        "element": f"element at ({nx}, {ny})",
                    },
                )
                ss_bytes = extract_image_bytes(ss_content)
        except Exception:
            pass  # Fall back to full viewport

        if not ss_bytes:
            ss_content = await _safe_call("browser_take_screenshot", {"type": "png"})
            ss_bytes = extract_image_bytes(ss_content)

        if not ss_bytes:
            return error_result(
                "Failed to capture screenshot.",
                hint="The browser may not have a visible page. Navigate to a URL first.",
            )

        img = Image.open(io.BytesIO(ss_bytes))
        width, height = img.size

        save_path = _Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        png_path = save_path / f"{base_name}.png"
        png_path.write_bytes(ss_bytes)

        webp_path = save_path / f"{base_name}.webp"
        img.save(str(webp_path), format="WEBP", quality=85)

        return success_result(
            f"Image saved to {png_path}",
            output=f"Attempted to save image to {png_path} ({width}x{height}), WebP version saved to {webp_path}",
        )
    except RuntimeError as exc:
        return error_result(
            f"Save image failed: {exc}",
            hint="Ensure the page is loaded and the coordinates point to a visible element.",
        )
    except Exception as exc:
        return error_result(
            f"Save image failed: {exc}", hint="Check that save_dir is writable and coordinates are valid."
        )


# ── 10. browser_upload_file ──────────────────────────────────────────────────


@tool(name="browser_upload_file")
async def browser_upload_file(
    files: Annotated[
        list[dict],
        'List of files to upload. Each item is an object with "index" (index of the file input element) and "path" (full absolute path to the file).',
    ],
) -> dict:
    """Upload files to a file input element on the browser page.

    <instructions>
    - Ensure file paths are valid and accessible.
    - Support multiple file uploads when needed.
    - Target file input elements using their index numbers.
    </instructions>

    <recommended_usage>
    - Use when uploading files to web forms.
    - Use when submitting documents or media files.
    </recommended_usage>
    """
    if not files:
        return error_result(
            "No files specified for upload.",
            hint='Provide a list of {"index": <element_index>, "path": "<file_path>"} dicts.',
        )

    all_paths: list[str] = []
    element_index = None
    for entry in files:
        path = entry.get("path", "")
        if not path:
            return error_result(
                "File entry missing 'path' field.",
                hint='Each entry needs {"index": <int>, "path": "<absolute_file_path>"}.',
            )
        if not os.path.exists(path):
            return error_result(
                f"File not found: {path}", hint=f"Verify the file exists at '{path}'. Use an absolute path."
            )
        all_paths.append(path)
        if element_index is None:
            element_index = entry.get("index")

    try:
        if element_index is not None:
            ref, err = _resolve_ref(element_index)
            if err:
                return err
            await _safe_call("browser_click", {"ref": ref})

        content = await _safe_call("browser_file_upload", {"paths": all_paths})
        snapshot = extract_text(content)
        return await _page_state_output(
            f"Attempted to upload {len(all_paths)} files to element {element_index}", snapshot_text=snapshot or None
        )
    except RuntimeError as exc:
        return error_result(
            f"File upload failed: {exc}", hint="The target element may not be a file input. Check with browser_view."
        )
    except Exception as exc:
        return error_result(
            f"File upload failed: {exc}",
            hint="Ensure the target is a <input type='file'> element and file paths are valid.",
        )


# ── 11. browser_find_keyword ─────────────────────────────────────────────────


@tool(name="browser_find_keyword")
async def browser_find_keyword(
    keyword: Annotated[str, "The keyword or text to search for on the page."],
) -> dict:
    """Find a keyword on the browser page.

    <instructions>
    - Use this tool to search for specific text content on the current page.
    - This tool will return the matching text and the surrounding context.
    - Consider partial matches and case sensitivity.
    </instructions>

    <recommended_usage>
    - Use when searching for specific text content on the page.
    - Use when verifying the presence of certain keywords.
    </recommended_usage>
    """
    if not keyword or not keyword.strip():
        return error_result("Keyword cannot be empty.", hint="Provide a non-empty search term.")

    try:
        content = await _safe_call("browser_snapshot")
        snapshot_text = extract_text(content)

        lower_snapshot = snapshot_text.lower()
        lower_keyword = keyword.lower()
        count = lower_snapshot.count(lower_keyword)

        snippets: list[str] = []
        search_start = 0
        while len(snippets) < 10:
            pos = lower_snapshot.find(lower_keyword, search_start)
            if pos == -1:
                break
            start = max(0, pos - 80)
            end = min(len(snapshot_text), pos + len(keyword) + 80)
            snippet = snapshot_text[start:end].strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(snapshot_text):
                snippet = snippet + "..."
            snippets.append(snippet)
            search_start = pos + len(keyword)

        search_results = "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(snippets))

        state = await _session().get_page_state(snapshot_text=snapshot_text)

        inline_md = state.markdown_content
        if len(inline_md) > 4000:
            inline_md = inline_md[:4000] + "\n... [truncated]"

        output = (
            f'Attempted to find keyword, found {count} occurrences of "{keyword}"\n'
            f"Search results:\n{search_results}\n"
            f"---\n"
            f"Title: {state.title}\n"
            f"URL: {state.url}\n"
            f"Clean screenshot path: {state.screenshot_path}\n"
            f"Pixels above viewport: {state.pixels_above}\n"
            f"Pixels below viewport: {state.pixels_below}\n"
            f"---\n"
            f"Viewport elements (index[:]info):\n"
            f"{state.viewport_elements}\n"
            f"---\n"
            f"Extracted page content in markdown:\n"
            f"{inline_md}"
        )
        return success_result(f'Found {count} occurrences of "{keyword}"', output=output)
    except RuntimeError as exc:
        return error_result(
            f"Keyword search failed: {exc}", hint="Ensure a page is loaded with browser before searching."
        )
    except Exception as exc:
        return error_result(f"Keyword search failed: {exc}", hint="Navigate to a page first, then search for keywords.")


# ── 12. browser_fill_form ────────────────────────────────────────────────────


@tool(name="browser_fill_form")
async def browser_fill_form(
    fields: Annotated[
        list[dict],
        'List of form fields to fill. Each item is an object with "index" (index of the form field element) and "value" (value to input).',
    ],
) -> dict:
    """Fill out multiple form fields at once on the browser page.

    <instructions>
    - Use this tool to efficiently fill multiple form fields in a single operation.
    - Ensure all form fields are visible and interactive before filling.
    - Use field indices to accurately target each input.
    - Provide appropriate values for each field type.
    </instructions>

    <recommended_usage>
    - Use when completing forms with multiple input fields.
    </recommended_usage>
    """
    if not fields:
        return error_result("No fields specified.", hint='Provide a list of {"index": <int>, "value": "<text>"} dicts.')

    session = _session()
    mcp_fields: list[dict] = []
    for f in fields:
        idx = f.get("index")
        value = f.get("value", "")
        if idx is None:
            return error_result(
                "Field entry missing 'index'.", hint='Each entry needs {"index": <int>, "value": "<text>"}.'
            )
        ref = session.ref_for_index(idx)
        if ref is None:
            return error_result(
                f"Element index {idx} not found in current viewport snapshot.",
                hint=f"Index {idx} is invalid. Call browser_view to refresh the element list.",
            )
        mcp_fields.append({"ref": ref, "value": value})

    try:
        content = await _safe_call("browser_fill_form", {"fields": mcp_fields})
        snapshot = extract_text(content)
        return await _page_state_output(
            f"Attempted to fill form with {len(fields)} fields", snapshot_text=snapshot or None
        )
    except RuntimeError as exc:
        return error_result(
            f"Form fill failed: {exc}",
            hint="Some fields may not be editable. Call browser_view to verify element types.",
        )
    except Exception as exc:
        return error_result(f"Form fill failed: {exc}", hint="Verify all target indices are editable form fields.")


# ── 13. browser_console_exec ─────────────────────────────────────────────────


@tool(name="browser_console_exec")
async def browser_console_exec(
    javascript: Annotated[
        str,
        "JavaScript code to execute in the current page's context via the browser console. The return value (if any) will be captured.",
    ],
) -> dict:
    """Execute JavaScript in the browser console.

    <instructions>
    - Ensure code is safe and controlled.
    - Wait for asynchronous operations when necessary.
    - The return value (if any) will be captured and returned.
    </instructions>

    <recommended_usage>
    - Use when custom scripts need to be executed.
    - Use when page element data needs to be retrieved.
    - Use when debugging page functionality or manipulating DOM.
    </recommended_usage>
    """
    if not javascript or not javascript.strip():
        return error_result(
            "JavaScript code cannot be empty.", hint="Provide a valid JavaScript expression or function to execute."
        )

    try:
        content = await _safe_call("browser_evaluate", {"function": javascript})
        result_text = extract_text(content)

        workspace = _workspace_root()
        output_path = os.path.join(workspace, "console_output.txt")
        try:
            with open(output_path, "a", encoding="utf-8") as fp:
                fp.write(f"> {javascript}\n< {result_text}\n\n")
        except OSError:
            output_path = "(save failed)"

        output = (
            f"Attempted to execute JavaScript.\n"
            f"[Console output during execution]:\n"
            f"> {javascript}\n"
            f"< {result_text}\n"
            f"---\n"
            f"Execution result also saved to {output_path}"
        )
        return success_result("JavaScript executed", output=output)
    except RuntimeError as exc:
        return error_result(
            f"JavaScript execution failed: {exc}",
            hint="The code may contain a syntax error or the page context may be unavailable. Wrap your code in an arrow function: '() => { ... }' for multi-statement blocks.",
        )
    except Exception as exc:
        return error_result(
            f"JavaScript execution failed: {exc}",
            hint="Ensure the page is loaded and the JavaScript is syntactically valid.",
        )


# ── 14. browser_console_view ─────────────────────────────────────────────────


@tool(name="browser_console_view")
async def browser_console_view(
    max_lines: Annotated[
        int | None,
        "Optional maximum number of console output lines to return. Defaults to the last 100 lines if not specified.",
    ] = None,
) -> dict:
    """View the content of the browser console.

    <instructions>
    - Set reasonable line limit to avoid overwhelming output.
    </instructions>

    <recommended_usage>
    - Use when verifying script execution results.
    - Use when debugging page errors.
    </recommended_usage>
    """
    try:
        args: dict = {"level": "info"}
        if max_lines is not None:
            args["all"] = True

        content = await _safe_call("browser_console_messages", args)
        console_text = extract_text(content)

        if max_lines is not None:
            lines = console_text.splitlines()
            if len(lines) > max_lines:
                console_text = "\n".join(lines[:max_lines])

        workspace = _workspace_root()
        output_path = os.path.join(workspace, "console_output.txt")
        try:
            with open(output_path, "a", encoding="utf-8") as fp:
                fp.write(console_text + "\n")
        except OSError:
            output_path = "(save failed)"

        output = f"[Last console output]:\n{console_text}\n---\nConsole output also saved to {output_path}"
        return success_result("Console messages retrieved", output=output)
    except RuntimeError as exc:
        return error_result(
            f"Console view failed: {exc}", hint="The browser may not have a page loaded. Navigate to a URL first."
        )
    except Exception as exc:
        return error_result(
            f"Console view failed: {exc}", hint="Ensure a page is loaded with browser before viewing console."
        )


# ── 15. browser_close ────────────────────────────────────────────────────────


@tool(name="browser_close")
async def browser_close() -> dict:
    """Close the browser window.

    <instructions>
    - This tool ends the current browsing session.
    - Only use when browser operations are completely finished.
    </instructions>

    <recommended_usage>
    - Use when the browser is no longer needed.
    - Use to clean up resources after completing web-based tasks.
    </recommended_usage>
    """
    try:
        session = _session()
        if session.started:
            with contextlib.suppress(Exception):
                await session.call_tool("browser_close")
            await session.stop()
        return success_result("Browser session closed", output="Browser closed")
    except Exception as exc:
        PlaywrightMCPSession.reset()
        return error_result(
            f"Browser close encountered an error: {exc}",
            hint="The session has been reset. You can start fresh with browser.",
        )


# ── Export ───────────────────────────────────────────────────────────────────

# Gateway tool — the only browser tool initially visible to the executor.
# Calling it triggers injection of all gated tools via tool_gate.
BROWSER_TOOL = browser

# Gated tools — injected after the gateway tool fires.
BROWSER_GATED_TOOLS = [
    browser_view,
    browser_click,
    browser_input,
    browser_scroll,
    browser_move_mouse,
    browser_press_key,
    browser_select_option,
    browser_save_image,
    browser_upload_file,
    browser_find_keyword,
    browser_fill_form,
    browser_console_exec,
    browser_console_view,
    browser_close,
]
