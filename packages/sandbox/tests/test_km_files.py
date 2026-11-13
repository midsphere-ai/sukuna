"""Tests for the Knowledge Manager file-format module.

Covers the load-bearing invariants:
- ``dump_km_file`` / ``parse_km_file`` roundtrip preserves every field
- ``dump_km_file`` always emits both ``## Summary`` and ``## Raw`` headings
  (even when ``raw`` is empty) so the parser can rely on structure
- ``format_for_injection`` NEVER references ``KMFile.raw`` — this is the
  trust-tier invariant that keeps untrusted external content out of
  planner/executor ephemeral injection
- ``_resolve_km_path`` refuses absolute paths, ``..`` segments, and any
  path that escapes ``<workspace>/.sukuna/km/``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_server.engine.km_files import (
    KMFile,
    KMFileFrontmatter,
    _resolve_km_path,
    build_relative_path,
    category_subdir,
    content_hash,
    dump_km_file,
    format_for_injection,
    km_root,
    parse_km_file,
    slugify,
    workspace_root,
)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point PROJECT_DIR at a fresh tmp dir for each test."""
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    return tmp_path


def _sample_file(raw: str = "<untrusted> content") -> KMFile:
    return KMFile(
        frontmatter=KMFileFrontmatter(
            title="Postgres timeout on startup",
            category="issue",
            scope="conversation",
            rationale="Connection pool exhausted at boot",
            supersedes=[],
            created_run_id="run-abc",
            updated_at="2026-04-10T09:00:00+00:00",
        ),
        summary="Raise max_connections to 200 and restart the pool.",
        raw=raw,
    )


# ── Roundtrip ────────────────────────────────────────────────────────────


def test_dump_parse_roundtrip_preserves_every_field() -> None:
    f = _sample_file(raw="line1\nline2\nverbatim")
    parsed = parse_km_file(dump_km_file(f))
    assert parsed.frontmatter.title == f.frontmatter.title
    assert parsed.frontmatter.category == f.frontmatter.category
    assert parsed.frontmatter.scope == f.frontmatter.scope
    assert parsed.frontmatter.rationale == f.frontmatter.rationale
    assert parsed.frontmatter.supersedes == f.frontmatter.supersedes
    assert parsed.frontmatter.created_run_id == f.frontmatter.created_run_id
    assert parsed.frontmatter.updated_at == f.frontmatter.updated_at
    assert parsed.summary == f.summary
    assert parsed.raw == f.raw


def test_dump_always_emits_both_section_headers_even_with_empty_raw() -> None:
    f = _sample_file(raw="")
    dumped = dump_km_file(f)
    assert "## Summary" in dumped
    assert "## Raw" in dumped
    # Parser handles the empty raw case
    parsed = parse_km_file(dumped)
    assert parsed.raw == ""


def test_parse_rejects_missing_frontmatter() -> None:
    with pytest.raises(ValueError, match="frontmatter"):
        parse_km_file("## Summary\n\nno frontmatter\n\n## Raw\n")


def test_parse_rejects_missing_summary_section() -> None:
    text = "---\ntitle: x\ncategory: issue\nscope: conversation\n---\n\nno summary here\n"
    with pytest.raises(ValueError, match="Summary"):
        parse_km_file(text)


# ── Trust-tier invariant (load-bearing) ──────────────────────────────────


def test_format_for_injection_never_contains_raw_content() -> None:
    """The single most important invariant in the whole knowledge manager design.

    ``format_for_injection`` is the function that takes ``KMFile`` objects
    and produces the markdown block injected into planner/executor context
    on every LLM call.  If it ever touches ``file.raw``, untrusted external
    content would be amplified into the prompt on every turn.
    """
    f = _sample_file(raw="BEGIN_RAW_MARKER <script>alert('xss')</script> END_RAW_MARKER")
    injected = format_for_injection([f])
    assert "BEGIN_RAW_MARKER" not in injected
    assert "script" not in injected
    assert "END_RAW_MARKER" not in injected
    # And the summary IS present
    assert "max_connections" in injected


def test_format_for_injection_empty_input_returns_empty_string() -> None:
    assert format_for_injection([]) == ""


def test_format_for_injection_groups_by_category() -> None:
    f_issue = _sample_file()
    f_decision = KMFile(
        frontmatter=KMFileFrontmatter(
            title="Chose Postgres",
            category="decision",
            scope="project",
            rationale="ACID guarantees",
        ),
        summary="Using Postgres 16 with pgvector.",
    )
    injected = format_for_injection([f_issue, f_decision])
    # Both categories appear with their human labels
    assert "Issues & Resolutions" in injected
    assert "Technical Decisions" in injected
    assert "Chose Postgres" in injected
    # Decision includes rationale
    assert "ACID guarantees" in injected


# ── Path resolver sandbox ────────────────────────────────────────────────


def test_resolve_km_path_refuses_absolute() -> None:
    with pytest.raises(ValueError, match="absolute"):
        _resolve_km_path("/etc/passwd")


def test_resolve_km_path_refuses_windows_absolute() -> None:
    with pytest.raises(ValueError):
        _resolve_km_path("\\windows\\system32")


def test_resolve_km_path_refuses_dotdot() -> None:
    with pytest.raises(ValueError, match=r"\.\."):
        _resolve_km_path("conv-1/../../../etc/passwd")


def test_resolve_km_path_refuses_null_byte() -> None:
    with pytest.raises(ValueError, match="null"):
        _resolve_km_path("conv-1/issue/foo\x00.md")


def test_resolve_km_path_refuses_empty() -> None:
    with pytest.raises(ValueError):
        _resolve_km_path("")


def test_resolve_km_path_accepts_good_path(isolated_workspace: Path) -> None:
    resolved = _resolve_km_path("conv-abc/issue/timeout.md")
    # Must live under the KM root
    assert str(resolved).startswith(str(isolated_workspace / ".sukuna" / "km"))
    assert resolved.name == "timeout.md"


def test_resolve_km_path_stays_inside_km_root(isolated_workspace: Path) -> None:
    # Tricky case: absolute resolution of `a/b/../c` normalizes to `a/c`
    # and should stay inside the km root.  But `../../..` must escape.
    with pytest.raises(ValueError):
        _resolve_km_path("../../outside")


# ── Supporting helpers ───────────────────────────────────────────────────


def test_slugify_basic() -> None:
    assert slugify("PostgreSQL Connection Timeout!") == "postgresql-connection-timeout"
    assert slugify("   hello world   ") == "hello-world"
    assert slugify("") == "untitled"
    assert slugify("a" * 200, max_len=32) == "a" * 32


def test_category_subdir() -> None:
    assert category_subdir("issue") == "issue"
    with pytest.raises(ValueError):
        category_subdir("not-a-real-category")


def test_build_relative_path_conversation_scope() -> None:
    p = build_relative_path(
        scope="conversation",
        conversation_id="conv-123",
        category="decision",
        slug="use-postgres",
    )
    assert p == "conv-123/decision/use-postgres.md"


def test_build_relative_path_project_scope_ignores_conv_id() -> None:
    p = build_relative_path(
        scope="project",
        conversation_id="",
        category="requirement",
        slug="sso-only",
    )
    assert p == "_project/requirement/sso-only.md"


def test_build_relative_path_refuses_bad_scope() -> None:
    with pytest.raises(ValueError):
        build_relative_path(
            scope="global",  # type: ignore[arg-type]
            conversation_id="c",
            category="issue",
            slug="x",
        )


def test_content_hash_normalizes_line_endings() -> None:
    a = content_hash("line1\nline2\n")
    b = content_hash("line1\r\nline2\r\n")
    c = content_hash("line1\rline2\r")
    assert a == b == c
    # Different content produces different hash
    assert content_hash("different") != a


def test_workspace_root_reads_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("PROJECT_DIR", str(tmp_path))
    assert workspace_root() == tmp_path


def test_km_root_nests_under_workspace(isolated_workspace: Path) -> None:
    root = km_root()
    assert root.is_relative_to(isolated_workspace) or str(root).startswith(str(isolated_workspace))
    assert root.name == "km"
    assert root.parent.name == ".sukuna"
