from __future__ import annotations

from agent_server.infra import sync as sync_module


def test_fallback_title_is_fast_and_deterministic() -> None:
    title = sync_module._fallback_title("Fix API timeout in postgres request handler and add retry logic.")

    assert title == "Fix API timeout in postgres request handler and add retry"


def test_fallback_title_uses_first_line_and_sentence() -> None:
    title = sync_module._fallback_title(
        "Build auth middleware with JWT.\nThen add refresh token rotation and revocation list."
    )

    assert title == "Build auth middleware with JWT"


def test_fallback_title_for_blank_prompt() -> None:
    title = sync_module._fallback_title("   ")

    assert title == "New conversation"


def test_truncate_title_keeps_word_boundaries_when_possible() -> None:
    title = sync_module._truncate_title("One two three four five six seven", max_len=15)

    assert title == "One two three"


def test_parse_llm_title_response_accepts_xml_title() -> None:
    parsed = sync_module._parse_llm_title_response("<title>Build caching layer for search results</title>")

    assert parsed == "Build caching layer for search results"


def test_parse_llm_title_response_accepts_fenced_xml_title() -> None:
    parsed = sync_module._parse_llm_title_response(
        "```xml\n<title>Investigate stream backpressure handling</title>\n```"
    )

    assert parsed == "Investigate stream backpressure handling"


def test_parse_llm_title_response_rejects_unused_tokens() -> None:
    parsed = sync_module._parse_llm_title_response("<unused49><unused49><unused49>")

    assert parsed is None


def test_parse_llm_title_response_rejects_unused_tokens_in_json_title() -> None:
    parsed = sync_module._parse_llm_title_response('{"title":"<unused49><unused49><unused49>"}')

    assert parsed is None


def test_parse_llm_title_response_rejects_unused_tokens_in_fenced_json_title() -> None:
    parsed = sync_module._parse_llm_title_response('```json\n{"title":"<unused49><unused49><unused49>"}\n```')

    assert parsed is None


def test_parse_llm_title_response_rejects_plain_text_without_xml() -> None:
    parsed = sync_module._parse_llm_title_response("Build caching layer for search results")

    assert parsed is None


def test_parse_llm_title_response_rejects_unused_tokens_inside_xml_title() -> None:
    parsed = sync_module._parse_llm_title_response("<title><unused49><unused49><unused49></title>")

    assert parsed is None
