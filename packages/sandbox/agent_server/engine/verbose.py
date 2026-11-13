"""Color-coded verbose logging for agent execution.

Gated by ``AGENT_VERBOSE=1`` environment variable.  When disabled, every
public function is a no-op with zero overhead.

Each agent type gets a distinct color:
  - Planner  → Blue
  - Executor → Green
  - KM       → Magenta
  - Ralph    → Yellow
  - Harness  → Cyan

Usage in ``run.py`` / ``harness.py``::

    from agent_server.engine.verbose import log_event, log_harness

    log_event(payload)                              # stream events
    log_harness("delegation_detected", task=...)    # orchestration flow
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

VERBOSE_ENABLED: bool = os.environ.get("AGENT_VERBOSE", "").lower() in ("1", "true", "yes")

log = logging.getLogger("agent_server.verbose")

# ---------------------------------------------------------------------------
# ANSI escape codes
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_AGENT_COLORS: dict[str, str] = {
    "planner": "\033[34m",  # Blue
    "executor": "\033[32m",  # Green
    "km": "\033[35m",  # Magenta
    "ralph": "\033[33m",  # Yellow
    "harness": "\033[36m",  # Cyan
}


# ---------------------------------------------------------------------------
# Agent name → color category
# ---------------------------------------------------------------------------


def _classify(agent_name: str) -> str:
    if not agent_name:
        return "harness"
    if agent_name == "planner":
        return "planner"
    if agent_name.startswith("executor_"):
        return "executor"
    if agent_name.startswith("ralph-worker"):
        return "ralph"
    if "km" in agent_name.lower() or "knowledge" in agent_name.lower():
        return "km"
    return "harness"


def _color(agent_name: str) -> str:
    return _AGENT_COLORS.get(_classify(agent_name), _AGENT_COLORS["harness"])


# ---------------------------------------------------------------------------
# Text buffer — accumulate LLM text tokens, flush in readable chunks
# ---------------------------------------------------------------------------

_TEXT_FLUSH_THRESHOLD = 200  # characters


class _TextBuffer:
    """Per-agent text accumulator.  Thread-safe."""

    def __init__(self) -> None:
        self._buffers: dict[str, str] = {}
        self._lock = threading.Lock()

    def append(self, agent_name: str, text: str) -> str | None:
        """Append text.  Returns accumulated text if threshold reached."""
        with self._lock:
            buf = self._buffers.get(agent_name, "") + text
            if len(buf) >= _TEXT_FLUSH_THRESHOLD:
                self._buffers[agent_name] = ""
                return buf
            self._buffers[agent_name] = buf
            return None

    def flush(self, agent_name: str) -> str | None:
        """Force-flush remaining buffer for an agent."""
        with self._lock:
            buf = self._buffers.pop(agent_name, "")
            return buf if buf else None


_text_buf = _TextBuffer()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _truncate(s: str, max_len: int = 200) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s


def _fmt(agent_name: str, symbol: str, message: str) -> str:
    """Build a color-coded log line."""
    c = _color(agent_name)
    ts = time.strftime("%H:%M:%S")
    tag = agent_name or _classify(agent_name)
    return f"{_DIM}{ts}{_RESET} {c}{_BOLD}[{tag}]{_RESET} {c}{symbol}{_RESET} {message}"


def _display_text(text: str, max_len: int = 300) -> str:
    """Collapse newlines and truncate for single-line display."""
    display = text.replace("\n", " ").strip()
    if len(display) > max_len:
        display = display[:max_len] + "..."
    return display


# ---------------------------------------------------------------------------
# Stream event logging — called from _stream_agent() in run.py
# ---------------------------------------------------------------------------


def log_event(payload: dict[str, Any]) -> None:
    """Log a stream event payload (dict from ``event.model_dump()``)."""
    if not VERBOSE_ENABLED:
        return

    event_type = payload.get("type", "")
    agent_name = payload.get("agent_name", "")

    if event_type == "text":
        _on_text(agent_name, payload.get("text", ""))
    elif event_type == "tool_call":
        _on_tool_call(agent_name, payload)
    elif event_type == "tool_result":
        _on_tool_result(agent_name, payload)
    elif event_type == "step":
        _on_step(agent_name, payload)
    elif event_type == "status":
        _on_status(agent_name, payload)
    elif event_type == "error":
        _on_error(agent_name, payload)
    elif event_type == "context":
        _on_context(agent_name, payload)
    elif event_type == "reasoning":
        _on_reasoning(agent_name, payload.get("text", ""))


def _on_text(agent_name: str, text: str) -> None:
    flushed = _text_buf.append(agent_name, text)
    if flushed:
        log.info(_fmt(agent_name, ">>", _display_text(flushed)))


def _on_reasoning(agent_name: str, text: str) -> None:
    flushed = _text_buf.append(f"_reasoning_{agent_name}", text)
    if flushed:
        log.info(_fmt(agent_name, "~~", f"(thinking) {_display_text(flushed)}"))


def _on_tool_call(agent_name: str, payload: dict) -> None:
    tool_name = payload.get("tool_name", "?")
    args = _truncate(payload.get("arguments", ""), 120)
    log.info(_fmt(agent_name, "->", f"{tool_name}({args})"))


def _on_tool_result(agent_name: str, payload: dict) -> None:
    tool_name = payload.get("tool_name", "?")
    success = payload.get("success", True)
    duration = payload.get("duration_ms", 0)
    error = payload.get("error")

    if success:
        result = _truncate(str(payload.get("result", "")), 150)
        msg = f"{tool_name} OK ({duration:.0f}ms) -> {result}"
    else:
        msg = f"{tool_name} FAIL ({duration:.0f}ms) err={error}"

    log.info(_fmt(agent_name, "<-" if success else "!!", msg))


def _on_step(agent_name: str, payload: dict) -> None:
    status = payload.get("status", "")
    step_num = payload.get("step_number", 0)

    if status == "started":
        log.info(_fmt(agent_name, "##", f"step {step_num} started"))
    elif status == "completed":
        # Flush any remaining text for this agent
        for prefix in ("", "_reasoning_"):
            remaining = _text_buf.flush(f"{prefix}{agent_name}")
            if remaining:
                sym = ">>" if not prefix else "~~"
                label = "" if not prefix else "(thinking) "
                log.info(_fmt(agent_name, sym, f"{label}{_display_text(remaining)}"))

        usage = payload.get("usage")
        usage_str = ""
        if usage and isinstance(usage, dict):
            tokens = usage.get("total_tokens", "?")
            usage_str = f" (tokens: {tokens})"
        log.info(_fmt(agent_name, "##", f"step {step_num} completed{usage_str}"))


def _on_status(agent_name: str, payload: dict) -> None:
    status = payload.get("status", "")
    message = payload.get("message", "")
    msg = f"status: {status}"
    if message:
        msg += f" — {message}"
    log.info(_fmt(agent_name, "**", msg))


def _on_error(agent_name: str, payload: dict) -> None:
    error = payload.get("error", "")
    error_type = payload.get("error_type", "")
    log.warning(_fmt(agent_name, "!!", f"ERROR [{error_type}]: {error}"))


def _on_context(agent_name: str, payload: dict) -> None:
    action = payload.get("action", "")
    before = payload.get("before_count", 0)
    after = payload.get("after_count", 0)
    log.info(_fmt(agent_name, "**", f"context {action}: {before} -> {after} messages"))


# ---------------------------------------------------------------------------
# Harness flow logging — called from harness.py and run.py
# ---------------------------------------------------------------------------


def log_harness(event_name: str, **kw: Any) -> None:
    """Log an orchestration flow event."""
    if not VERBOSE_ENABLED:
        return

    _FORMATTERS: dict[str, Any] = {
        "orchestrator_started": lambda: "Orchestrator started (run_id={})".format(kw.get("run_id", "?")),
        "planner_streaming": lambda: "Planner streaming (iteration={})".format(kw.get("iteration", "?")),
        "delegation_detected": lambda: "DELEGATION: {}".format(_truncate(kw.get("task", ""), 200)),
        "delegation_rejected": lambda: "Duplicate delegation rejected (already: {})".format(
            _truncate(kw.get("existing_task", ""), 120)
        ),
        "executor_created": lambda: "Executor created: {} (use_history={})".format(
            kw.get("executor_name", "?"), kw.get("use_history", False)
        ),
        "executor_streaming": lambda: "Executor streaming: {}".format(kw.get("executor_name", "?")),
        "executor_completed": lambda: "Executor completed: {} (turns={})".format(
            kw.get("executor_name", "?"), kw.get("turns", 0)
        ),
        "executor_error": lambda: "Executor FAILED: {} — {}".format(
            kw.get("executor_name", "?"), _truncate(str(kw.get("error", "")), 150)
        ),
        "executor_truncated": lambda: "Executor TRUNCATED (max_steps): {}".format(kw.get("executor_name", "?")),
        "planner_direct_response": lambda: "Planner responded directly (no delegation, iteration={})".format(
            kw.get("iteration", "?")
        ),
        "planner_error": lambda: "Planner ERROR (iteration={}): {}".format(
            kw.get("iteration", "?"), _truncate(str(kw.get("error", "")), 150)
        ),
        "planner_error_with_delegation": lambda: "Planner errored but delegation signal set — proceeding with executor",
        "handoff_to_executor": lambda: "Handoff: planner -> executor ({})".format(kw.get("executor_name", "?")),
        "handoff_to_planner": lambda: "Handoff: executor ({}) -> planner".format(kw.get("executor_name", "?")),
        "advise_cache_invalidated": lambda: "Advise cache invalidated (reason={}, role={})".format(
            kw.get("reason", "?"), kw.get("role", "?")
        ),
        "km_trigger": lambda: "KM triggered: trigger={} scope={}".format(kw.get("trigger", "?"), kw.get("scope", "?")),
        "km_completed": lambda: "KM completed: trigger={}".format(kw.get("trigger", "?")),
        "km_failed": lambda: "KM FAILED: {}".format(_truncate(str(kw.get("error", "")), 150)),
        "orchestrator_completed": lambda: "Orchestrator completed: reason={} planner_turns={} delegations={}".format(
            kw.get("reason", "?"), kw.get("planner_turns", 0), kw.get("delegations", 0)
        ),
        "orchestrator_max_iterations": lambda: "Orchestrator hit MAX_DELEGATION_ITERATIONS={}".format(
            kw.get("max_iterations", "?")
        ),
        # Ralph events
        "ralph_iteration_started": lambda: "Ralph iteration {}/{} (passed={}/{})".format(
            kw.get("iteration", "?"), kw.get("max_iterations", "?"), kw.get("passed", "?"), kw.get("total", "?")
        ),
        "ralph_iteration_completed": lambda: "Ralph iteration {} completed (passed={}/{}, score={})".format(
            kw.get("iteration", "?"), kw.get("passed", "?"), kw.get("total", "?"), kw.get("score", "?")
        ),
        "ralph_iteration_failed": lambda: "Ralph iteration {} FAILED: {}".format(
            kw.get("iteration", "?"), _truncate(str(kw.get("error", "")), 150)
        ),
        "ralph_complete": lambda: "Ralph complete: reason={} iterations={} (passed={}/{})".format(
            kw.get("reason", "?"), kw.get("iterations", "?"), kw.get("passed", "?"), kw.get("total", "?")
        ),
    }

    formatter = _FORMATTERS.get(event_name)
    msg = formatter() if formatter else f"{event_name}: {kw}"

    # Pick symbol and agent for coloring
    if "km" in event_name:
        symbol, agent = "KM", "km"
    elif "ralph" in event_name:
        symbol, agent = "**", kw.get("agent_name", "ralph")
    elif "executor" in event_name:
        symbol, agent = "=>", kw.get("executor_name", "executor")
    elif "handoff" in event_name:
        symbol, agent = "<>", ""
    elif "planner" in event_name:
        symbol, agent = "**", "planner"
    else:
        symbol, agent = "**", ""

    log.info(_fmt(agent, symbol, msg))
