"""Tests for the tolerant structured-output parser used by the ralph loop.

Covers the failure modes that crashed every iteration of the run logged
in /tmp/sandbox_server.log: chat-tuned models wrap RalphResult JSON in
```` ```json ... ``` ```` fences and add a leading prose preamble, both of
which kill ``model_validate_json`` directly.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_server.engine._structured_output import (
    StructuredOutputError,
    try_parse_structured,
)


class _SampleResult(BaseModel):
    success: bool
    story_id: str
    outcome: str
    committed: bool = False
    notes: str = ""


def test_raw_json_happy_path() -> None:
    result = try_parse_structured(
        '{"success": true, "story_id": "42", "outcome": "completed", "committed": true, "notes": "ok"}',
        _SampleResult,
    )
    assert result.story_id == "42"
    assert result.outcome == "completed"
    assert result.committed is True


def test_markdown_fenced_with_prose_preamble() -> None:
    """Reproduces the exact shape that failed in the production log."""
    text = (
        "Now I'll implement Story 30. Let me first read the file...\n"
        "\n"
        "[a lot of prose]\n"
        "\n"
        "Story 58 is fully complete. Let me emit the RalphResult.\n"
        "\n"
        "```json\n"
        "{\n"
        '  "success": true,\n'
        '  "story_id": "58",\n'
        '  "outcome": "completed",\n'
        '  "committed": true,\n'
        '  "notes": "Created the suggested-creators API."\n'
        "}\n"
        "```"
    )
    result = try_parse_structured(text, _SampleResult)
    assert result.story_id == "58"
    assert result.outcome == "completed"
    assert result.committed is True


def test_unfenced_json_with_leading_prose() -> None:
    text = (
        "Done with story 7. Result: "
        '{"success": false, "story_id": "7", "outcome": "blocked", '
        '"notes": "missing API key"}'
    )
    result = try_parse_structured(text, _SampleResult)
    assert result.story_id == "7"
    assert result.outcome == "blocked"
    assert result.success is False


def test_fence_without_json_tag() -> None:
    text = 'Here\'s the result:\n```\n{"success": true, "story_id": "1", "outcome": "completed"}\n```'
    result = try_parse_structured(text, _SampleResult)
    assert result.story_id == "1"


def test_garbage_raises_with_original_text() -> None:
    text = "there is no json here at all just words"
    with pytest.raises(StructuredOutputError) as exc_info:
        try_parse_structured(text, _SampleResult)
    assert exc_info.value.text == text
    assert exc_info.value.last_error is not None


def test_empty_raises() -> None:
    with pytest.raises(StructuredOutputError):
        try_parse_structured("", _SampleResult)
    with pytest.raises(StructuredOutputError):
        try_parse_structured("   \n  ", _SampleResult)


def test_malformed_json_in_fence_falls_through_to_object_extract() -> None:
    """Fence body is broken but a balanced {...} still appears later."""
    text = (
        '```json\n{not valid json at all\n```\n\nRecovery: {"success": true, "story_id": "9", "outcome": "completed"}'
    )
    result = try_parse_structured(text, _SampleResult)
    assert result.story_id == "9"
