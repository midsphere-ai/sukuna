"""Tests for the ``.sukuna`` path sandbox.

The Knowledge Manager stores its canonical markdown notes under
``<workspace>/.sukuna/km/``.  The standard file tool (``tools/file/ops.py``)
must be unable to read, write, list, or even *detect* anything under that
directory.  Critically, when the tool refuses, its error must be
*indistinguishable* from a genuinely missing path — no "protected",
"security", or "sandbox" keywords anywhere — so a prompt-injection attacker
has no protection-flavoured signal to latch onto.

These tests live here rather than in ``tests/test_path_traversal.py``
because they exercise the hidden-segment gaslighting layer specifically,
not the generic project-root traversal guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``tools`` importable the same way the agent server does.
_SANDBOX = Path(__file__).resolve().parent.parent
if str(_SANDBOX / "tools") not in sys.path:
    sys.path.insert(0, str(_SANDBOX / "tools"))

from file.ops import (  # noqa: E402
    _discover_files,
    _first_hidden_segment,
    list_files_util,
    normalize_path,
    read_file_util,
)

# Keywords that MUST NEVER appear in a hidden-segment error — they would
# telegraph the existence of protection to the model.  ``hidden`` is NOT on
# this list because pytest's own ``tmp_path`` can generate directory names
# containing "hidden" when tests have that word in their function name.
_FORBIDDEN_KEYWORDS = (
    "protect",
    "protected",
    "security keyword",  # bare "security" can show up in system paths
    "sandbox",
    "access denied",
    "permission denied",
    "forbidden",
)


def _assert_no_leak(err: Exception) -> None:
    msg = str(err).lower()
    for bad in _FORBIDDEN_KEYWORDS:
        assert bad not in msg, f"error message leaks protection keyword {bad!r}: {err}"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    # A realistic workspace with some regular files, a .git dir, and a
    # populated .sukuna/km tree the tests should not be able to see.
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "README.md").write_text("# docs\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / ".sukuna" / "km" / "_project" / "decision").mkdir(parents=True)
    (tmp_path / ".sukuna" / "km" / "_project" / "decision" / "x.md").write_text(
        "---\ntitle: x\ncategory: decision\nscope: project\n---\n## Summary\n\nsecret\n\n## Raw\n\nraw\n"
    )
    return tmp_path


# ── Segment detection helper ─────────────────────────────────────────────


def test_first_hidden_segment_detects_dotdotsukuna() -> None:
    assert _first_hidden_segment(".sukuna") == ".sukuna"
    assert _first_hidden_segment(".sukuna/km/foo.md") == ".sukuna"
    assert _first_hidden_segment("a/b/.sukuna/c") == ".sukuna"
    assert _first_hidden_segment("src/main.py") is None
    assert _first_hidden_segment("normal/.env") is None  # .env is not hidden


# ── normalize_path: relative paths ───────────────────────────────────────


def test_normalize_path_refuses_bare_sukuna_dir(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        normalize_path(".sukuna", workspace)
    _assert_no_leak(exc.value)
    # Bare .sukuna looks dir-like (no extension, no trailing slash but
    # also no internal dot after leading dots) → "Directory 'X' does not exist"
    assert "Directory" in str(exc.value)


def test_normalize_path_refuses_km_file(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        normalize_path(".sukuna/km/_project/decision/x.md", workspace)
    _assert_no_leak(exc.value)
    # File-like path → "File 'X' does not exist"
    assert "File" in str(exc.value)


def test_normalize_path_refuses_midpath_sukuna(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        normalize_path("a/.sukuna/b", workspace)
    _assert_no_leak(exc.value)


def test_normalize_path_refuses_absolute_sukuna(workspace: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc:
        normalize_path(str(workspace / ".sukuna" / "km" / "x.md"), workspace)
    _assert_no_leak(exc.value)


# ── normalize_path: regular paths still work ─────────────────────────────


def test_normalize_path_accepts_regular_file(workspace: Path) -> None:
    abs_p, rel = normalize_path("src/main.py", workspace)
    assert rel == "src/main.py"


def test_normalize_path_accepts_absolute_inside_workspace(
    workspace: Path,
) -> None:
    abs_p, rel = normalize_path(str(workspace / "docs" / "README.md"), workspace)
    assert rel.endswith("README.md")


# ── read_file_util: error shapes match real-missing ──────────────────────


def test_read_hidden_file_looks_like_missing_file(workspace: Path) -> None:
    real_missing_msg: str = ""
    hidden_msg: str = ""
    try:
        read_file_util(str(workspace / "src" / "does-not-exist.py"), project_dir=workspace)
    except FileNotFoundError as e:
        real_missing_msg = str(e)

    try:
        read_file_util(
            str(workspace / ".sukuna" / "km" / "_project" / "decision" / "x.md"),
            project_dir=workspace,
        )
    except FileNotFoundError as e:
        hidden_msg = str(e)

    # Both should use the "File 'X' does not exist" format and neither
    # should leak any protection-flavoured keyword.
    assert "does not exist" in real_missing_msg
    assert "does not exist" in hidden_msg
    assert "File '" in real_missing_msg
    assert "File '" in hidden_msg
    _assert_no_leak(FileNotFoundError(hidden_msg))


def test_list_hidden_dir_looks_like_missing_directory(workspace: Path) -> None:
    real_missing_msg: str = ""
    hidden_msg: str = ""
    try:
        list_files_util(str(workspace / "nonexistent-dir"), project_dir=workspace)
    except FileNotFoundError as e:
        real_missing_msg = str(e)
    try:
        list_files_util(str(workspace / ".sukuna"), project_dir=workspace)
    except FileNotFoundError as e:
        hidden_msg = str(e)

    assert "Directory '" in real_missing_msg
    assert "Directory '" in hidden_msg
    assert "does not exist" in real_missing_msg
    assert "does not exist" in hidden_msg
    _assert_no_leak(FileNotFoundError(hidden_msg))


# ── _discover_files silently skips .sukuna ───────────────────────────────


def test_discover_files_excludes_sukuna(workspace: Path) -> None:
    found = _discover_files(workspace, workspace)
    # Regular files are found
    assert any("src/main.py" in p for p in found)
    assert any("docs/README.md" in p for p in found)
    # .sukuna and everything under it is completely invisible
    for p in found:
        assert ".sukuna" not in p, f"discover leaked hidden path: {p}"


def test_discover_files_excludes_git_too(workspace: Path) -> None:
    """Sanity check that the original .git exclusion still works."""
    found = _discover_files(workspace, workspace)
    for p in found:
        assert ".git" not in p, f"discover leaked .git path: {p}"
