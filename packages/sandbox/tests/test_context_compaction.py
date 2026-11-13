"""Tests for ``compact_messages`` in ``agent_server/engine/context.py``.

Covers the ``COMPACT_REGISTRY`` path (tool-native compaction) and the
PTC ``_compact_intent`` path.  Tools not in the registry are left
untouched.

The function under test is pure — it modifies a list of exo message
objects in place and returns an estimated token-savings count.  No
provider, agent, or running event loop is required.
"""

from __future__ import annotations

import json

from exo.ptc import PTC_TOOL_NAME
from exo.types import AssistantMessage, SystemMessage, ToolCall, ToolResult

from agent_server.engine.context import compact_messages

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

BIG_CODE = "for i in range(500):\n    print(i)\n" * 20  # ~7 KB
BIG_STDOUT = "".join(f"item-{i}\n" for i in range(500))  # ~4 KB
BIG_BLOB = "X" * 4000  # ~4 KB
SYSTEM_CONTENT = "You are a helpful agent."


def _assistant(tc_id: str, name: str, args: dict) -> AssistantMessage:
    return AssistantMessage(
        content="",
        tool_calls=[ToolCall(id=tc_id, name=name, arguments=json.dumps(args))],
    )


def _result(tc_id: str, tool_name: str, content: str) -> ToolResult:
    return ToolResult(tool_call_id=tc_id, tool_name=tool_name, content=content)


def _file_pair(tc_id: str) -> tuple[AssistantMessage, ToolResult]:
    """Known 'file' tool — uses COMPACT_REGISTRY."""
    args = {
        "action": "write",
        "path": "/tmp/note.txt",
        "text": BIG_BLOB,
    }
    asst = _assistant(tc_id, "file", args)
    result = _result(
        tc_id,
        "file",
        json.dumps(
            {
                "success": True,
                "message": "File write complete",
                "bytes": len(BIG_BLOB),
                "debug_dump": BIG_BLOB,
            }
        ),
    )
    return asst, result


def _browser_pair(tc_id: str) -> tuple[AssistantMessage, ToolResult]:
    """Known 'browser' tool — uses COMPACT_REGISTRY."""
    args = {
        "url": "https://example.com/docs",
        "intent": "informational",
        "focus": "pricing table",
    }
    asst = _assistant(tc_id, "browser", args)
    result = _result(
        tc_id,
        "browser",
        json.dumps(
            {
                "success": True,
                "message": "Navigated to https://example.com/docs",
                "output": BIG_BLOB,
            }
        ),
    )
    return asst, result


def _shell_pair(tc_id: str) -> tuple[AssistantMessage, ToolResult]:
    """Known 'shell' tool — uses COMPACT_REGISTRY."""
    args = {
        "action": "foreground",
        "session": "main",
        "command": "ls -la /home/ubuntu",
        "timeout": 30,
    }
    asst = _assistant(tc_id, "shell", args)
    result = _result(
        tc_id,
        "shell",
        json.dumps(
            {
                "success": True,
                "message": "Command completed",
                "exit_code": 0,
                "stdout": BIG_STDOUT,
                "output_saved_to": "/tmp/.outputs/stdout_abc123.txt",
            }
        ),
    )
    return asst, result


def _unknown_pair(tc_id: str) -> tuple[AssistantMessage, ToolResult]:
    """Unknown tool not in registry — stays verbose."""
    args = {
        "query": "some data",
        "blob": BIG_BLOB,
    }
    asst = _assistant(tc_id, "unknown_tool", args)
    result = _result(tc_id, "unknown_tool", BIG_BLOB)
    return asst, result


def _ptc_pair(
    tc_id: str,
    *,
    with_intent: bool = True,
    stdout: str = BIG_STDOUT,
) -> tuple[AssistantMessage, ToolResult]:
    """A ``__exo_ptc__`` tool call paired with its stdout result."""
    args: dict = {"code": BIG_CODE}
    if with_intent:
        args["_compact_intent"] = "printed integers 0 to 499"
    asst = _assistant(tc_id, PTC_TOOL_NAME, args)
    result = _result(tc_id, PTC_TOOL_NAME, stdout)
    return asst, result


def _history(*pairs: tuple[AssistantMessage, ToolResult]) -> list:
    """Compose [system, asst, result, asst, result, ...] in order."""
    msgs: list = [SystemMessage(content=SYSTEM_CONTENT)]
    for asst, result in pairs:
        msgs.append(asst)
        msgs.append(result)
    return msgs


# ---------------------------------------------------------------------------
# Tests — COMPACT_REGISTRY (tool-native compaction)
# ---------------------------------------------------------------------------


def test_file_tool_drops_non_essential_args() -> None:
    """The 'file' tool keeps only essential_args=(action, path, url)
    and drops everything else (like 'text')."""
    pair = _file_pair("file_1")
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args == {"action": "write", "path": "/tmp/note.txt"}
    assert "text" not in args


def test_file_tool_result_becomes_restorable_pointer() -> None:
    """The file tool result is replaced with a restorable pointer."""
    pair = _file_pair("file_1")
    messages = _history(pair)

    compact_messages(messages)

    assert "write on /tmp/note.txt" in messages[2].content
    assert "Re-read" in messages[2].content
    assert BIG_BLOB not in messages[2].content


def test_browser_tool_keeps_essential_args_drops_others() -> None:
    """Browser tool keeps url and intent, drops focus."""
    pair = _browser_pair("browser_1")
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args == {"url": "https://example.com/docs", "intent": "informational"}
    assert "focus" not in args


def test_browser_tool_result_becomes_restorable_pointer() -> None:
    """Browser tool result becomes a revisit pointer."""
    pair = _browser_pair("browser_1")
    messages = _history(pair)

    compact_messages(messages)

    assert "https://example.com/docs" in messages[2].content
    assert "Revisit" in messages[2].content
    assert BIG_BLOB not in messages[2].content


def test_shell_tool_keeps_essential_args() -> None:
    """Shell tool keeps action, session, command; drops timeout."""
    pair = _shell_pair("shell_1")
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args == {"action": "foreground", "session": "main", "command": "ls -la /home/ubuntu"}
    assert "timeout" not in args


def test_shell_tool_result_includes_saved_path() -> None:
    """Shell tool result pointer includes the output_saved_to path."""
    pair = _shell_pair("shell_1")
    messages = _history(pair)

    compact_messages(messages)

    assert "/tmp/.outputs/stdout_abc123.txt" in messages[2].content
    assert BIG_STDOUT not in messages[2].content


# ---------------------------------------------------------------------------
# Tests — PTC compaction
# ---------------------------------------------------------------------------


def test_ptc_happy_path_drops_code() -> None:
    """PTC call with ``_compact_intent``: args collapse to
    ``{"_compact_intent": ...}`` and code is dropped."""
    pair = _ptc_pair("ptc_1", with_intent=True)
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args == {"_compact_intent": "printed integers 0 to 499"}
    assert "code" not in args


def test_ptc_without_intent_passes_through() -> None:
    """If the LLM forgot ``_compact_intent`` the args pass through
    unchanged (full ``code`` preserved)."""
    pair = _ptc_pair("ptc_1", with_intent=False)
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args["code"] == BIG_CODE
    assert "_compact_intent" not in args


def test_ptc_with_failed_result_is_not_compacted() -> None:
    """Failed tool results (``success: false``) must not be compacted."""
    tc_id = "ptc_fail"
    args = {
        "code": BIG_CODE,
        "_compact_intent": "tried to do the thing",
    }
    asst = _assistant(tc_id, PTC_TOOL_NAME, args)
    result = _result(
        tc_id,
        PTC_TOOL_NAME,
        json.dumps({"success": False, "error": "SyntaxError in user code"}),
    )
    messages = _history((asst, result))

    compact_messages(messages)

    # Call-side untouched.
    stale_args = json.loads(messages[1].tool_calls[0].arguments)
    assert stale_args["code"] == BIG_CODE
    # Result-side untouched.
    assert '"success": false' in messages[2].content
    assert "SyntaxError" in messages[2].content


def test_empty_or_whitespace_intent_is_ignored() -> None:
    """Empty ``_compact_intent`` must not trigger compaction."""
    tc_id = "ptc_empty"
    args = {"code": BIG_CODE, "_compact_intent": "   "}
    asst = _assistant(tc_id, PTC_TOOL_NAME, args)
    result = _result(tc_id, PTC_TOOL_NAME, BIG_STDOUT)
    messages = _history((asst, result))

    compact_messages(messages)

    stale_args = json.loads(messages[1].tool_calls[0].arguments)
    assert stale_args["code"] == BIG_CODE


# ---------------------------------------------------------------------------
# Tests — Unknown tools (no registry entry, no legacy)
# ---------------------------------------------------------------------------


def test_unknown_tool_stays_verbose() -> None:
    """Unknown tool not in registry stays completely untouched."""
    pair = _unknown_pair("unknown_1")
    messages = _history(pair)

    compact_messages(messages)

    args = json.loads(messages[1].tool_calls[0].arguments)
    assert args["blob"] == BIG_BLOB
    assert messages[2].content == BIG_BLOB


# ---------------------------------------------------------------------------
# Tests — Mixed tool types and invariants
# ---------------------------------------------------------------------------


def test_mixed_ptc_and_registry_tools() -> None:
    """Different tool types each compact via their own path."""
    reg_pair = _file_pair("file_1")
    ptc_pair_val = _ptc_pair("ptc_1")
    messages = _history(reg_pair, ptc_pair_val)

    compact_messages(messages)

    # File tool: registry compaction
    file_args = json.loads(messages[1].tool_calls[0].arguments)
    assert file_args == {"action": "write", "path": "/tmp/note.txt"}
    assert "Re-read" in messages[2].content

    # PTC tool: intent compaction
    ptc_args = json.loads(messages[3].tool_calls[0].arguments)
    assert ptc_args == {"_compact_intent": "printed integers 0 to 499"}


def test_compaction_is_idempotent() -> None:
    """Running compact_messages twice produces same result."""
    pair = _file_pair("file_1")
    messages = _history(pair)

    compact_messages(messages)
    args_after_first = json.loads(messages[1].tool_calls[0].arguments)
    result_after_first = messages[2].content

    compact_messages(messages)
    args_after_second = json.loads(messages[1].tool_calls[0].arguments)
    result_after_second = messages[2].content

    assert args_after_first == args_after_second
    assert result_after_first == result_after_second


def test_system_messages_are_never_touched() -> None:
    """System messages pass through compaction unchanged."""
    pair = _file_pair("file_1")
    messages = _history(pair)

    compact_messages(messages)

    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == SYSTEM_CONTENT


def test_failed_registry_tool_result_is_not_compacted() -> None:
    """Registry tools with success=false keep full result."""
    tc_id = "file_fail"
    args = {"action": "read", "path": "/nonexistent.txt"}
    asst = _assistant(tc_id, "file", args)
    result = _result(
        tc_id,
        "file",
        json.dumps({"success": False, "message": "File not found", "error": "ENOENT"}),
    )
    messages = _history((asst, result))

    compact_messages(messages)

    # Call-side still compacted (only failed RESULTS are preserved)
    call_args = json.loads(messages[1].tool_calls[0].arguments)
    assert call_args == {"action": "read", "path": "/nonexistent.txt"}
    # Result-side preserved — full error context
    assert '"success": false' in messages[2].content
    assert "File not found" in messages[2].content


def test_tokens_saved_is_positive_for_compacted_messages() -> None:
    """compact_messages returns a positive token savings estimate."""
    pair = _file_pair("file_1")
    messages = _history(pair)

    saved = compact_messages(messages)

    assert saved > 0
