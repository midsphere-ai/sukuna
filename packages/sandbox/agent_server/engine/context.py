"""Two-stage context reduction engine for long-running agent sessions.

Stage 1 — **Compaction**: Replace tool calls/results with compact
representations.  Each tool declares its essential args and a pointer
builder via ``CompactSpec`` in ``COMPACT_REGISTRY``.  Tools not in the
registry are left untouched.

Stage 2 — **Summarization**: When compaction yields diminishing returns,
dump full history to disk (``context-<timestamp>.log``) and replace with
a structured LLM-generated summary.

Triggers:
    - Turn-based (primary, deterministic): compact every 150 turns,
      summarize every 400 turns. "Turn" = one LLM step for the agent
      that owns the ContextEngineState (planner / executor / KM each
      have their own).
    - Token-based (safety net): compact at Level 4, summarize if
      still ≥ Level 4 after compaction.

Token budget levels (derived from ``CONTEXT_BUDGET_TOKENS`` env var,
default 128 000):
    - Level 1: 25 % of budget
    - Level 2: 50 % of budget
    - Level 3: 75 % of budget
    - Level 4: 100 % of budget  ← compaction / summarization trigger
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from exo.ptc import PTC_TOOL_NAME
from exo.types import (
    AssistantMessage,
    SystemMessage,
    ToolCall,
    ToolResult,
)
from pydantic import BaseModel
from pydantic import Field as PydanticField

log = logging.getLogger(__name__)

__version__ = "0.2.0"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextEngineConfig:
    """Tunable knobs for the context reduction engine.

    ``context_budget_tokens`` defines the total token budget for the
    agent's context window.  Four levels are derived from it:

        Level 1 = 25 %   Level 2 = 50 %   Level 3 = 75 %   Level 4 = 100 %

    Compaction fires when the window reaches Level 4.  If still at
    Level 4 after compaction, summarization fires.
    """

    # Turn triggers (primary, deterministic).
    # "Turn" = one LLM step for the agent that owns this state. The planner,
    # each executor spawn, and the KM each carry their own state, so these
    # intervals are per-agent — not shared across the run.
    #
    # Tools in this codebase already return compact pointers (file paths,
    # save-to-disk references) instead of dumping raw output, so per-turn
    # token growth is small. The deterministic intervals are tuned to fire
    # about once per "long" working block while leaving the token-based
    # safety net (Level 4) as the real backstop for runaway growth.
    compaction_turn_interval: int = 150
    summarization_turn_interval: int = 400

    # Token budget — set via CONTEXT_BUDGET_TOKENS env var at instantiation
    context_budget_tokens: int = 128_000

    # Summarization model (None = use the agent's own model/provider)
    summary_model: str | None = None

    # Agent role context — changes what the summarizer focuses on
    is_sub_agent: bool = False
    sub_agent_task: str = ""

    @property
    def level_4(self) -> int:
        """100 % of budget — compaction / summarization trigger."""
        return self.context_budget_tokens

    @property
    def level_3(self) -> int:
        """75 % of budget."""
        return int(self.context_budget_tokens * 0.75)

    @property
    def level_2(self) -> int:
        """50 % of budget."""
        return int(self.context_budget_tokens * 0.50)

    @property
    def level_1(self) -> int:
        """25 % of budget."""
        return int(self.context_budget_tokens * 0.25)


# ---------------------------------------------------------------------------
# CompactSpec — tool-native compaction declarations
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompactSpec:
    """Declares how a tool's calls and results should be compacted.

    ``essential_args``
        Argument names to **keep** in the compact call.  Everything
        else is **dropped** (never truncated).

    ``pointer_builder``
        ``(call_args, result_content) -> str`` — builds a restorable
        pointer from the tool call arguments and the raw result JSON
        string.  The pointer should tell the agent where/how to retrieve
        the full data if needed.
    """

    essential_args: tuple[str, ...]
    pointer_builder: Callable[[dict[str, Any], str], str]


def _extract_message(result_content: str) -> str:
    """Extract the ``message`` field from a JSON result, or first line."""
    try:
        data = json.loads(result_content)
        if isinstance(data, dict):
            msg = data.get("message", "")
            if isinstance(msg, str) and msg.strip():
                return msg.strip()
    except (json.JSONDecodeError, TypeError):
        pass
    first = result_content.strip().split("\n", 1)[0]
    return first if first else "(no result)"


def _safe_get(d: dict[str, Any], key: str, fallback: str = "") -> str:
    """Get a string value from a dict, returning *fallback* if missing."""
    val = d.get(key)
    return str(val) if val is not None else fallback


def _parse_result(result_content: str) -> dict[str, Any] | None:
    """Try to parse result_content as JSON dict."""
    try:
        data = json.loads(result_content)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        return None


# ── Pointer builders ──────────────────────────────────────────────────


def _ptr_file(args: dict[str, Any], result: str) -> str:
    action = _safe_get(args, "action", "file op")
    path = _safe_get(args, "path")
    url = _safe_get(args, "url")
    if path:
        return f"{action} on {path}. Re-read with file tool if needed"
    if url:
        return f"Downloaded from {url}. Re-read if needed"
    return _extract_message(result)


def _ptr_shell(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    saved = data.get("output_saved_to") or data.get("stdout_saved_to") if data else None
    command = _safe_get(args, "command")
    if saved:
        return f"Ran '{command}'. Output saved to {saved}. Read file if needed"
    return _extract_message(result)


def _ptr_match(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    count = data.get("count", data.get("match_count", "?")) if data else "?"
    regex = _safe_get(args, "regex")
    scope = _safe_get(args, "scope")
    if regex:
        return f"Found {count} matches for '{regex}' in {scope}. Re-run match if needed"
    return f"Found {count} files in {scope}. Re-run match if needed"


def _ptr_search(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    count = data.get("count", "?") if data else "?"
    queries = args.get("queries")
    query_str = queries[0] if isinstance(queries, list) and queries else str(queries)
    search_type = _safe_get(args, "type", "web")
    return f"Searched '{query_str}' ({search_type}), {count} results. Re-search if needed"


def _ptr_browser_navigate(args: dict[str, Any], result: str) -> str:
    url = _safe_get(args, "url")
    return f"Navigated to {url}. Revisit {url} if needed"


def _ptr_browser_save_image(args: dict[str, Any], result: str) -> str:
    save_dir = _safe_get(args, "save_dir")
    base_name = _safe_get(args, "base_name")
    return f"Saved image to {save_dir}/{base_name}. View with file tool if needed"


def _ptr_web_init(args: dict[str, Any], result: str) -> str:
    name = _safe_get(args, "name")
    return f"Initialized web project '{name}'"


def _ptr_mobile_init(args: dict[str, Any], result: str) -> str:
    name = _safe_get(args, "name")
    return f"Initialized mobile project '{name}'"


def _ptr_git(args: dict[str, Any], result: str) -> str:
    action = _safe_get(args, "action", "git op")
    commit_msg = _safe_get(args, "commit_message")
    commit_hash = _safe_get(args, "commit_hash")
    ref = commit_msg or commit_hash or ""
    return f"Git {action}: {ref}".strip() if ref else f"Git {action}"


def _ptr_expose(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    port = _safe_get(args, "port")
    url = data.get("url", "") if data else ""
    if url:
        return f"Exposed port {port} at {url}"
    return f"Exposed port {port}"


def _ptr_message(args: dict[str, Any], result: str) -> str:
    msg_type = _safe_get(args, "type", "info")
    return f"Sent {msg_type} message to user"


def _ptr_delegate(args: dict[str, Any], result: str) -> str:
    task = _safe_get(args, "task")
    return f"Delegated: {task}. Check sub-agent result if needed"


def _ptr_ralph_loop(args: dict[str, Any], result: str) -> str:
    max_iter = args.get("max_iterations", "?")
    prd_path = args.get("prd_path", "")
    return f"Ralph loop from '{prd_path}', {max_iter} iterations"


def _ptr_plan(args: dict[str, Any], result: str) -> str:
    action = _safe_get(args, "action", "plan op")
    return f"Plan {action}. View with plan tool if needed"


def _ptr_schedule(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    name = _safe_get(args, "name")
    task_id = data.get("task_id", "") if data else ""
    if name and task_id:
        return f"Scheduled '{name}' (id={task_id})"
    if name:
        return f"Scheduled '{name}'"
    return _extract_message(result)


def _ptr_km_read(args: dict[str, Any], result: str) -> str:
    path = _safe_get(args, "path")
    return f"Read KM at {path}. Re-read with km_read if needed"


def _ptr_km_write(args: dict[str, Any], result: str) -> str:
    title = _safe_get(args, "title")
    path = _safe_get(args, "path")
    return f"Wrote KM '{title}' to {path}"


def _ptr_km_list(args: dict[str, Any], result: str) -> str:
    data = _parse_result(result)
    count = data.get("count", "?") if data else "?"
    return f"Listed {count} KM entries. Re-list if needed"


def _ptr_km_delete(args: dict[str, Any], result: str) -> str:
    path = _safe_get(args, "path")
    return f"Deleted KM at {path}"


def _ptr_artifact(args: dict[str, Any], result: str) -> str:
    action = _safe_get(args, "action", "create")
    title = _safe_get(args, "title")
    return f"{action} artifact '{title}'. Retrieve with artifact tool if needed"


def _ptr_perception(args: dict[str, Any], result: str) -> str:
    source = _safe_get(args, "source")
    return f"Analyzed {source}. Re-analyze if needed"


def _ptr_skill(args: dict[str, Any], result: str) -> str:
    action = _safe_get(args, "action", "view")
    name = _safe_get(args, "name")
    return f"Skill {action}: {name}. Re-read with skill tool if needed"


def _ptr_extract_message(args: dict[str, Any], result: str) -> str:
    return _extract_message(result)


# ── Registry ──────────────────────────────────────────────────────────

COMPACT_REGISTRY: dict[str, CompactSpec] = {
    # File operations
    "file": CompactSpec(
        essential_args=("action", "path", "url"),
        pointer_builder=_ptr_file,
    ),
    # Shell execution
    "shell": CompactSpec(
        essential_args=("action", "session", "command"),
        pointer_builder=_ptr_shell,
    ),
    # File/text matching
    "match": CompactSpec(
        essential_args=("action", "scope", "regex"),
        pointer_builder=_ptr_match,
    ),
    # Web search
    "search": CompactSpec(
        essential_args=("type", "queries"),
        pointer_builder=_ptr_search,
    ),
    # Browser navigation
    "browser": CompactSpec(
        essential_args=("url", "intent"),
        pointer_builder=_ptr_browser_navigate,
    ),
    # Browser sub-tools — most just extract message
    "browser_click": CompactSpec(
        essential_args=("index",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_input": CompactSpec(
        essential_args=("index", "text"),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_scroll": CompactSpec(
        essential_args=("direction",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_move_mouse": CompactSpec(
        essential_args=(),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_press_key": CompactSpec(
        essential_args=("key",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_select_option": CompactSpec(
        essential_args=("index", "option_index"),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_save_image": CompactSpec(
        essential_args=("save_dir", "base_name"),
        pointer_builder=_ptr_browser_save_image,
    ),
    "browser_upload_file": CompactSpec(
        essential_args=("files",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_find_keyword": CompactSpec(
        essential_args=("keyword",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_fill_form": CompactSpec(
        essential_args=("fields",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_console_exec": CompactSpec(
        essential_args=("javascript",),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_console_view": CompactSpec(
        essential_args=(),
        pointer_builder=_ptr_extract_message,
    ),
    "browser_close": CompactSpec(
        essential_args=(),
        pointer_builder=lambda a, r: "Browser session closed",
    ),
    "browser_view": CompactSpec(
        essential_args=(),
        pointer_builder=_ptr_extract_message,
    ),
    # Web project tools
    "web_init": CompactSpec(
        essential_args=("name", "title", "scaffold"),
        pointer_builder=_ptr_web_init,
    ),
    "web_project": CompactSpec(
        essential_args=("action", "name"),
        pointer_builder=_ptr_extract_message,
    ),
    "web_server": CompactSpec(
        essential_args=("action", "port"),
        pointer_builder=_ptr_extract_message,
    ),
    "web_env": CompactSpec(
        essential_args=("action", "key"),
        pointer_builder=_ptr_extract_message,
    ),
    "web_db": CompactSpec(
        essential_args=("action", "query"),
        pointer_builder=_ptr_extract_message,
    ),
    # Mobile project tools
    "mobile_init": CompactSpec(
        essential_args=("name", "title"),
        pointer_builder=_ptr_mobile_init,
    ),
    "mobile_project": CompactSpec(
        essential_args=("action", "name"),
        pointer_builder=_ptr_extract_message,
    ),
    "mobile_server": CompactSpec(
        essential_args=("action", "port"),
        pointer_builder=_ptr_extract_message,
    ),
    # Git operations
    "git": CompactSpec(
        essential_args=("action", "commit_message", "commit_hash"),
        pointer_builder=_ptr_git,
    ),
    # Port exposure
    "expose": CompactSpec(
        essential_args=("port", "label"),
        pointer_builder=_ptr_expose,
    ),
    # Agent-to-user communication
    "message": CompactSpec(
        essential_args=("type", "text"),
        pointer_builder=_ptr_message,
    ),
    # Sub-agent delegation
    "delegate": CompactSpec(
        essential_args=("task", "brief"),
        pointer_builder=_ptr_delegate,
    ),
    # Ralph autonomous loop
    "ralph_loop": CompactSpec(
        essential_args=("max_iterations",),
        pointer_builder=_ptr_ralph_loop,
    ),
    # Plan management
    "plan": CompactSpec(
        essential_args=("action", "goal", "current_phase_id", "next_phase_id"),
        pointer_builder=_ptr_plan,
    ),
    # Schedule management
    "schedule": CompactSpec(
        essential_args=("type", "name", "cron", "interval"),
        pointer_builder=_ptr_schedule,
    ),
    # Knowledge Manager tools
    "km_read": CompactSpec(
        essential_args=("path", "section"),
        pointer_builder=_ptr_km_read,
    ),
    "km_write": CompactSpec(
        essential_args=("title", "category", "scope", "path"),
        pointer_builder=_ptr_km_write,
    ),
    "km_list": CompactSpec(
        essential_args=("scope", "category"),
        pointer_builder=_ptr_km_list,
    ),
    "km_delete": CompactSpec(
        essential_args=("path", "reason"),
        pointer_builder=_ptr_km_delete,
    ),
    "km_nudge": CompactSpec(
        essential_args=("title", "target_role", "urgency"),
        pointer_builder=_ptr_extract_message,
    ),
    # Artifact creation
    "artifact": CompactSpec(
        essential_args=("action", "artifact_type", "title"),
        pointer_builder=_ptr_artifact,
    ),
    "perception": CompactSpec(
        essential_args=("action", "source"),
        pointer_builder=_ptr_perception,
    ),
    # Extended reasoning
    "reasoning": CompactSpec(
        essential_args=("action", "question"),
        pointer_builder=_ptr_extract_message,
    ),
    # Skill discovery
    "skill": CompactSpec(
        essential_args=("action", "name"),
        pointer_builder=_ptr_skill,
    ),
}


# ---------------------------------------------------------------------------
# Structured summary object
# ---------------------------------------------------------------------------


@dataclass
class TrajectorySummary:
    """Structured representation of a summarized agent trajectory."""

    goal: str = ""
    actions: list[dict[str, str]] = field(default_factory=list)
    files: list[dict[str, str]] = field(default_factory=list)
    current_state: str = ""
    decisions: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-run mutable state
# ---------------------------------------------------------------------------


class ContextEngineState:
    """Tracks turn count and compaction/summarization history within a run."""

    __slots__ = ("turn_count", "compaction_count", "summary_count")

    def __init__(self) -> None:
        self.turn_count: int = 0
        self.compaction_count: int = 0
        self.summary_count: int = 0


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
#
# Used for two things:
#   1. Logging "before/after" deltas around compaction/summarization.
#   2. The safety-net trigger when the provider doesn't report
#      ``info.input_tokens`` (initial windowing pass).
#
# When ``info.input_tokens`` IS available, prefer it — it's the ground
# truth from the model API. ``estimate_tokens`` is a structural estimate
# of what we sent, not what the API counted.

_counter_cache: dict[str, Any] = {}

# Per-message wrapper overhead for OpenAI-style chat formats. Each message
# carries role/separators/etc. ~4 tokens is the well-documented constant.
_PER_MESSAGE_OVERHEAD = 4

# Per-tool-call wrapper overhead (id, name, function-call envelope) on top
# of just the arguments string.
_PER_TOOL_CALL_OVERHEAD = 8


def _get_counter(model: str = "gpt-4o") -> Any:
    if model not in _counter_cache:
        from exo.token_counter import TokenCounter

        _counter_cache[model] = TokenCounter(model)
    return _counter_cache[model]


def estimate_tools_tokens(tools: Any, model: str = "gpt-4o") -> int:
    """Estimate the token cost of the tool schemas sent to the LLM each turn.

    Tool schemas (name + description + JSON Schema parameters) are
    re-serialized into every LLM request. For 15 rich tools this can be
    5-10k tokens of prompt overhead that ``estimate_tokens(messages)``
    completely misses.

    ``tools`` may be:
        - an iterable of objects with ``.to_schema()`` (exo Tool / FunctionTool)
        - an iterable of pre-serialized dicts
        - ``None`` / empty (returns 0)
    """
    if not tools:
        return 0
    counter = _get_counter(model)
    total = 0
    try:
        for t in tools:
            try:
                schema = t.to_schema() if hasattr(t, "to_schema") else t
                if not isinstance(schema, (dict, list)):
                    continue
                total += counter.count(json.dumps(schema, ensure_ascii=False))
            except Exception:
                continue
    except TypeError:
        return 0
    return total


def estimate_tokens(
    messages: list[Any],
    model: str = "gpt-4o",
    tools: Any = None,
) -> int:
    """Estimate total prompt tokens for a message list.

    Counts:
        - Message ``content`` (string or list-of-blocks)
        - ``tool_calls`` arguments **and** the tool name + per-call envelope
        - ``ToolResult.tool_name`` (the result wrapper)
        - Per-message wrapper overhead (role/separators)
        - Optional ``tools`` schemas (the per-turn tool definitions block)

    Still an approximation — it doesn't model the exact wire format of
    every provider — but much closer to ``info.input_tokens`` than the
    content-only estimate it replaces.
    """
    counter = _get_counter(model)
    total = 0
    for msg in messages:
        total += _PER_MESSAGE_OVERHEAD

        content = getattr(msg, "content", "")
        if isinstance(content, str):
            if content:
                total += counter.count(content)
        elif isinstance(content, list):
            for block in content:
                text = getattr(block, "text", None) or getattr(block, "data", "")
                if isinstance(text, str) and text:
                    total += counter.count(text)

        # Tool calls: count arguments + name + per-call envelope.
        for tc in getattr(msg, "tool_calls", []) or []:
            total += _PER_TOOL_CALL_OVERHEAD
            name = getattr(tc, "name", "")
            if isinstance(name, str) and name:
                total += counter.count(name)
            args = getattr(tc, "arguments", "")
            if isinstance(args, str) and args:
                total += counter.count(args)

        # Tool results carry a tool_name string in addition to content.
        tool_name = getattr(msg, "tool_name", "")
        if isinstance(tool_name, str) and tool_name:
            total += counter.count(tool_name)

    total += estimate_tools_tokens(tools, model=model)
    return total


# ---------------------------------------------------------------------------
# Stage 1: Compaction
# ---------------------------------------------------------------------------


def compact_messages(messages: list[Any]) -> int:
    """Compact tool calls/results in-place using the ``COMPACT_REGISTRY``.

    Three compaction paths (in priority order):

    1. **PTC tool calls** (``__exo_ptc__``) — the bloated ``code`` field
       is replaced with ``_compact_intent``.

    2. **Known tools** — uses ``COMPACT_REGISTRY`` to keep only essential
       args and build a restorable pointer for results.

    Tools not in the registry are left untouched.

    Rules:
        - Failed tool results (``success: false``) are **never** compacted.
        - Non-essential args are **dropped**, never truncated.
        - Result pointers are restorable references (file paths, URLs).
        - Compaction is idempotent — re-processing a compact message is a no-op.

    Returns an estimate of tokens saved.
    """
    # First pass: build tool_call_id → parsed args / tool-name lookups
    tc_args_lookup: dict[str, dict[str, Any]] = {}
    tc_name_lookup: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AssistantMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    parsed = json.loads(tc.arguments) if tc.arguments else {}
                    if isinstance(parsed, dict):
                        tc_args_lookup[tc.id] = parsed
                        tc_name_lookup[tc.id] = tc.name
                except (json.JSONDecodeError, TypeError):
                    pass

    # Collect tool_call_ids whose results indicate failure — never compact these.
    failed_tc_ids: set[str] = set()
    for msg in messages:
        if not isinstance(msg, ToolResult) or not isinstance(msg.content, str):
            continue
        try:
            result_data = json.loads(msg.content)
            if isinstance(result_data, dict) and result_data.get("success") is False:
                failed_tc_ids.add(msg.tool_call_id)
        except (json.JSONDecodeError, TypeError):
            pass

    tokens_saved = 0
    compacted_calls = 0
    compacted_results = 0

    # Second pass: compact AssistantMessages (tool call arguments)
    for i, msg in enumerate(messages):
        if not isinstance(msg, AssistantMessage) or not msg.tool_calls:
            continue

        new_calls: list[ToolCall] = []
        changed = False

        for tc in msg.tool_calls:
            parsed = tc_args_lookup.get(tc.id)
            if parsed is None or tc.id in failed_tc_ids:
                new_calls.append(tc)
                continue

            # ── PTC-specific path ─────────────────────────────────────
            if tc.name == PTC_TOOL_NAME:
                compact_intent = parsed.get("_compact_intent")
                if isinstance(compact_intent, str) and compact_intent.strip():
                    compact_args = {"_compact_intent": compact_intent}
                    compact_json = json.dumps(compact_args, ensure_ascii=False)
                    old_len = len(tc.arguments) if tc.arguments else 0
                    tokens_saved += max(0, (old_len - len(compact_json))) // 4
                    if tc.arguments != compact_json:
                        new_calls.append(tc.model_copy(update={"arguments": compact_json}))
                        changed = True
                        compacted_calls += 1
                    else:
                        new_calls.append(tc)
                else:
                    new_calls.append(tc)
                continue

            # ── Registry path ─────────────────────────────────────────
            spec = COMPACT_REGISTRY.get(tc.name)
            if spec is not None:
                compact_args = {k: v for k, v in parsed.items() if k in spec.essential_args}
                compact_json = json.dumps(compact_args, ensure_ascii=False)
                old_len = len(tc.arguments) if tc.arguments else 0
                new_len = len(compact_json)
                tokens_saved += max(0, (old_len - new_len)) // 4
                if tc.arguments != compact_json:
                    new_calls.append(tc.model_copy(update={"arguments": compact_json}))
                    changed = True
                    compacted_calls += 1
                else:
                    new_calls.append(tc)
                continue

            # Tool not in registry — leave untouched
            new_calls.append(tc)

        if changed:
            messages[i] = msg.model_copy(update={"tool_calls": new_calls})

    # Third pass: compact ToolResults
    for i, msg in enumerate(messages):
        if not isinstance(msg, ToolResult):
            continue
        if not isinstance(msg.content, str):
            continue  # skip multimodal content

        # Never compact failed tool results — errors stay in context.
        try:
            result_data = json.loads(msg.content)
            if isinstance(result_data, dict) and result_data.get("success") is False:
                continue
        except (json.JSONDecodeError, TypeError):
            pass

        # Find matching tool call args/name if available.
        parsed = tc_args_lookup.get(msg.tool_call_id)
        tool_name = tc_name_lookup.get(msg.tool_call_id, msg.tool_name)

        # ── Registry path ─────────────────────────────────────────
        spec = COMPACT_REGISTRY.get(tool_name)
        if spec is not None:
            call_args = parsed if isinstance(parsed, dict) else {}
            pointer = spec.pointer_builder(call_args, msg.content)
            if pointer and msg.content != pointer:
                old_len = len(msg.content)
                tokens_saved += max(0, (old_len - len(pointer))) // 4
                messages[i] = msg.model_copy(update={"content": pointer})
                compacted_results += 1
            continue

    log.info(
        "compaction: ~%d tokens saved (%d tool calls, %d tool results compacted, %d failed skipped)",
        tokens_saved,
        compacted_calls,
        compacted_results,
        len(failed_tc_ids),
    )
    return tokens_saved


# ---------------------------------------------------------------------------
# Stage 2: Summarization
# ---------------------------------------------------------------------------


def _dump_context_to_disk(messages: list[Any], conversation_id: str) -> str:
    """Serialize full message history to a timestamped log file on disk.

    Returns the file path, or empty string on failure.
    """
    try:
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        workspace = os.environ.get(
            "SANDBOX_WORKSPACE_ROOT",
            os.environ.get("WORKSPACE", "/tmp"),
        )
        log_dir = os.path.join(workspace, ".context_dumps")
        os.makedirs(log_dir, exist_ok=True)
        filename = f"context-{timestamp}.log"
        filepath = os.path.join(log_dir, filename)

        lines: list[str] = []
        for msg in messages:
            role = getattr(msg, "role", type(msg).__name__)
            content = getattr(msg, "content", "")
            tool_calls = getattr(msg, "tool_calls", [])
            lines.append(f"=== {role} ===")
            if content:
                lines.append(str(content))
            for tc in tool_calls:
                lines.append(f"  [tool_call] {tc.name}({tc.arguments})")
            lines.append("")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        log.info("context engine: dumped %d messages to %s", len(messages), filepath)
        return filepath
    except Exception:
        log.warning("context engine: failed to dump context to disk", exc_info=True)
        return ""


def _build_summarize_instruction(
    messages: list[Any],
    config: ContextEngineConfig,
    conversation_id: str = "",
) -> str:
    """Build a context-aware summarization prompt."""
    parts: list[str] = []

    if config.is_sub_agent:
        parts.append(
            "You are summarizing the trajectory of a sub-agent that was given "
            "a specific task by the planner. Your summary must help the agent "
            "pick up exactly where it left off and complete the task."
        )
        if config.sub_agent_task:
            parts.append(f"\n## Assigned Task\n{config.sub_agent_task}")
        parts.append(
            "\nFocus on: what has been done toward this task, what obstacles "
            "were hit, what files were touched, and what remains to finish it. "
            "Do NOT summarize unrelated context — only what matters for this task."
        )
    else:
        parts.append(
            "You are summarizing the trajectory of an agent session. Your "
            "summary must preserve everything the agent needs to continue "
            "working effectively after context compression."
        )

        user_goal = _extract_user_goal(messages)
        if user_goal:
            parts.append(f"\n## User Goal\n{user_goal}")

        plan_md = _get_plan_state(conversation_id)
        if plan_md:
            parts.append(f"\n## Current Plan\n{plan_md}")

        if conversation_id:
            vital_md = _get_vital_info(conversation_id)
            if vital_md:
                parts.append(f"\n## Vital Information (from Knowledge Manager)\n{vital_md}")

    parts.append(
        "\n## Instructions\n"
        "Produce a structured trajectory summary. Be thorough with:\n"
        "- File paths — include every file created or modified\n"
        "- Errors and how they were recovered from\n"
        "- Key decisions and their rationale\n"
        "- What has been completed vs what remains\n"
        "- Any important context the agent will need to continue"
    )

    return "\n".join(parts)


def _extract_user_goal(messages: list[Any]) -> str:
    """Extract the user's original goal from the first few user messages."""
    user_texts: list[str] = []
    for msg in messages:
        role = getattr(msg, "role", "")
        if role == "user":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and content.strip():
                if content.startswith("<!--") or content.startswith("<plan-context>"):
                    continue
                user_texts.append(content.strip())
                if len(user_texts) >= 3:
                    break
    if not user_texts:
        return ""
    if len(user_texts) == 1:
        return user_texts[0][:500]
    goal = user_texts[0][:300]
    clarifications = " | ".join(t[:100] for t in user_texts[1:])
    return f"{goal}\n\nUser clarifications: {clarifications}"


def _get_plan_state(conversation_id: str = "") -> str:
    """Get the current plan state from the plan tool module, if available."""
    try:
        from agent_server.engine.hooks import format_plan_markdown  # noqa: C0415

        md = format_plan_markdown(conversation_id or None)
        if md:
            return (
                md.replace("<!-- PLAN_CONTEXT -->", "")
                .replace("<plan-context>", "")
                .replace("</plan-context>", "")
                .strip()
            )
    except Exception:
        pass
    return ""


def _get_vital_info(conversation_id: str) -> str:
    """Get KM vital info synchronously for the summarization prompt."""
    try:
        from agent_server.models import VitalInformation  # noqa: C0415

        items = list(
            VitalInformation.objects.filter(
                conversation_id=conversation_id,
                is_active=True,
            ).order_by("category", "-created_at")[:20]
        )
        if not items:
            return ""

        lines: list[str] = []
        for item in items:
            lines.append(f"- [{item.category}] **{item.title}**: {item.content}")
            if item.rationale:
                lines.append(f"  _Rationale: {item.rationale}_")
        return "\n".join(lines)
    except Exception:
        return ""


class TrajectorySummaryModel(BaseModel):
    """Pydantic model for structured output from the summarization LLM call."""

    goal: str = PydanticField(description="What the user originally asked for")
    actions: list[dict[str, str]] = PydanticField(
        default_factory=list,
        description='List of {"action": "what was done", "outcome": "what happened"}',
    )
    files: list[dict[str, str]] = PydanticField(
        default_factory=list,
        description='List of {"path": "/full/path", "description": "what this file is"}',
    )
    current_state: str = PydanticField(default="", description="Where things stand right now")
    decisions: list[dict[str, str]] = PydanticField(
        default_factory=list,
        description='List of {"decision": "choice made", "rationale": "why"}',
    )
    errors: list[dict[str, str]] = PydanticField(
        default_factory=list,
        description='List of {"error": "what went wrong", "resolution": "how fixed"}',
    )
    next_steps: list[str] = PydanticField(default_factory=list, description="What still needs to be done")


def _format_summary_message(summary: TrajectorySummary) -> str:
    """Format a TrajectorySummary into a readable message."""
    parts: list[str] = ["[Trajectory Summary]"]

    if summary.goal:
        parts.append(f"\n## Goal\n{summary.goal}")

    if summary.actions:
        parts.append("\n## Actions Completed")
        for i, a in enumerate(summary.actions, 1):
            parts.append(f"{i}. {a.get('action', '?')} → {a.get('outcome', '?')}")

    if summary.files:
        parts.append("\n## Files Created/Modified")
        for f in summary.files:
            parts.append(f"- {f.get('path', '?')}: {f.get('description', '?')}")

    if summary.current_state:
        parts.append(f"\n## Current State\n{summary.current_state}")

    if summary.decisions:
        parts.append("\n## Key Decisions")
        for d in summary.decisions:
            parts.append(f"- {d.get('decision', '?')}: {d.get('rationale', '?')}")

    if summary.errors:
        parts.append("\n## Errors & Recovery")
        for e in summary.errors:
            parts.append(f"- {e.get('error', '?')}: {e.get('resolution', '?')}")

    if summary.next_steps:
        parts.append("\n## Next Steps")
        for s in summary.next_steps:
            parts.append(f"- {s}")

    return "\n".join(parts)


def _is_user_message(msg: Any) -> bool:
    return not isinstance(msg, SystemMessage) and getattr(msg, "role", "") == "user"


def _coerce_structured_summary(raw_text: str) -> TrajectorySummary | None:
    """Best-effort extract a TrajectorySummary from freeform LLM text.

    Mirrors ``knowledge/runner.py::_coerce_output`` for the same reason:
    small / local models often drop the structured schema and return
    prose or fenced JSON. Try progressively looser parses and return
    ``None`` if nothing sticks.
    """
    import re as _re

    text = raw_text.strip()
    if not text:
        return None

    candidates: list[str] = [text]

    fence = _re.search(r"```(?:json|JSON)?\s*\n?(.*?)\n?\s*```", text, _re.DOTALL)
    if fence is not None:
        candidates.append(fence.group(1).strip())

    obj = _re.search(r"\{.*\}", text, _re.DOTALL)
    if obj is not None:
        candidates.append(obj.group(0))

    for cand in candidates:
        try:
            parsed = TrajectorySummaryModel.model_validate_json(cand)
        except Exception:
            continue
        return TrajectorySummary(
            goal=parsed.goal,
            actions=parsed.actions,
            files=parsed.files,
            current_state=parsed.current_state,
            decisions=parsed.decisions,
            errors=parsed.errors,
            next_steps=parsed.next_steps,
        )
    return None


async def summarize_messages(
    messages: list[Any],
    provider: Any,
    config: ContextEngineConfig,
    summary_count: int,
    conversation_id: str = "",
) -> TrajectorySummary:
    """Generate a structured summary by passing the full message history to an LLM.

    Before summarization, the full message history is dumped to disk
    (``context-<timestamp>.log``) as a persistent backup.

    Preservation strategy:
        * ``SystemMessage`` — always preserved (the agent's instructions).
        * **All** user messages — preserved verbatim.  Every ``UserMessage``
          in persisted history is genuine user input from the API / frontend
          (hook injections are ``AssistantMessage`` ephemerals; delegation
          results land as ``AssistantMessage`` too).  User turns are the
          ground truth of the conversation — we never compress them.
        * Assistant messages + tool results — summarized into a single
          replacement ``AssistantMessage`` (the agent's own recollection).
    """
    from exo.types import UserMessage

    # Dump full history to disk BEFORE any modification
    dump_path = _dump_context_to_disk(messages, conversation_id)

    # Partition: system + every user message are preserved;
    # assistants / tool results are the only things summarized.
    system_msgs: list[Any] = []
    user_msgs: list[Any] = []
    replaceable: list[Any] = []

    for msg in messages:
        if isinstance(msg, SystemMessage):
            system_msgs.append(msg)
        elif _is_user_message(msg):
            user_msgs.append(msg)
        else:
            replaceable.append(msg)

    if not replaceable:
        log.info("summarization: nothing to summarize")
        return TrajectorySummary()

    # Log what's being summarized
    replaceable_tokens = estimate_tokens(replaceable)
    log.info(
        "summarization: condensing %d messages (~%d tokens) into summary, "
        "preserving %d system + %d user messages | dump=%s",
        len(replaceable),
        replaceable_tokens,
        len(system_msgs),
        len(user_msgs),
        dump_path,
    )

    # Build context-aware summarization instruction
    summarize_instruction = _build_summarize_instruction(messages, config, conversation_id)

    # Send the replaceable messages + instruction to the LLM
    summary_input: list[Any] = list(replaceable) + [
        UserMessage(content=summarize_instruction),
    ]

    summary: TrajectorySummary | None = None
    raw_text = ""

    try:
        response = await provider.complete(
            summary_input,
            tools=None,
            temperature=0.3,
            max_tokens=2048,
            output_type=TrajectorySummaryModel,
        )
        raw_text = getattr(response, "content", "") or ""
        summary = _coerce_structured_summary(raw_text)
    except Exception:
        log.warning("summarization: structured output failed, trying raw", exc_info=True)

    if summary is None:
        # Fall back: request unstructured prose and try to salvage JSON
        # from it; if no JSON is present, keep the prose as current_state.
        try:
            response = await provider.complete(
                summary_input,
                tools=None,
                temperature=0.3,
                max_tokens=2048,
            )
            raw_text = getattr(response, "content", "") or ""
            summary = _coerce_structured_summary(raw_text)
            if summary is None:
                trimmed = raw_text.strip()
                if trimmed:
                    summary = TrajectorySummary(
                        goal=_extract_user_goal(messages)[:300] or "(summary below)",
                        current_state=trimmed[:4000],
                    )
                else:
                    summary = TrajectorySummary(
                        goal="(summarization returned empty)",
                        current_state=(
                            "Previous context was compressed; recent messages "
                            "remain. Re-read any files the plan references to "
                            "re-orient."
                        ),
                    )
        except Exception:
            log.warning("summarization: LLM call failed entirely", exc_info=True)
            summary = TrajectorySummary(
                goal="(summarization failed)",
                current_state=(
                    "Previous context was compressed. Continue from recent "
                    "messages and re-read plan/findings files to re-orient."
                ),
            )

    # Build the replacement message — AssistantMessage (agent's recollection)
    summary_text = _format_summary_message(summary)
    if dump_path:
        summary_text += f"\n\n_Full context dumped to {dump_path}_"
    summary_msg = AssistantMessage(content=summary_text, tool_calls=[])

    # Replace messages in-place: system + goal anchor + summary
    messages.clear()
    messages.extend(system_msgs + user_msgs + [summary_msg])

    summary_tokens = estimate_tokens([summary_msg])
    log.info(
        "summarization: replaced %d messages (~%d tokens) with 1 summary "
        "(~%d tokens) | goal=%r, actions=%d, files=%d, errors=%d, next_steps=%d",
        len(replaceable),
        replaceable_tokens,
        summary_tokens,
        summary.goal[:80] if summary.goal else "(none)",
        len(summary.actions),
        len(summary.files),
        len(summary.errors),
        len(summary.next_steps),
    )
    return summary


# The CONTEXT_WINDOW hook factory (``make_context_engine_hook``) that wires
# these helpers into exo's hook system lives in
# ``agent_server.engine.hooks`` alongside every other agent hook.
