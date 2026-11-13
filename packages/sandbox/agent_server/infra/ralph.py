"""Ralph loop helpers — PRD completion checks, pass merging, and progress patterns."""

from __future__ import annotations

import json
from pathlib import Path as FilePath
from typing import Any


def _check_prd_completion(workspace_root: str) -> tuple[int, int, float]:
    """Read prd.json and return (passed, total, score).

    Returns (0, 0, 0.0) if prd.json is missing or malformed.

    Note: this collapses "file not found" and "malformed JSON" into the
    same sentinel. For logs that need to distinguish the two, use
    ``_check_prd_completion_detailed`` instead. This variant is preserved
    for backwards compatibility with existing callers (and tests).
    """
    passed, total, score, _reason = _check_prd_completion_detailed(workspace_root)
    return passed, total, score


def _check_prd_completion_detailed(
    workspace_root: str,
) -> tuple[int, int, float, str | None]:
    """Read prd.json and return (passed, total, score, error_reason).

    ``error_reason`` is one of:
        - ``None`` — file read and parsed successfully
        - ``"file_not_found"`` — prd.json missing at workspace root
        - ``"parse_error"`` — file exists but is not valid JSON
        - ``"schema_error"`` — JSON parsed but required keys are missing

    Use this variant when the caller needs to distinguish "prd.json is
    missing/corrupted" from "all stories are genuinely incomplete" — the
    original ``_check_prd_completion`` collapses both into (0, 0, 0.0).
    """
    prd_path = FilePath(workspace_root) / "prd.json"
    try:
        prd = json.loads(prd_path.read_text())
        stories = prd["userStories"]
        total = len(stories)
        if total == 0:
            return 0, 0, 0.0, None
        passed = sum(1 for s in stories if s.get("passes"))
        return passed, total, passed / total, None
    except FileNotFoundError:
        return 0, 0, 0.0, "file_not_found"
    except json.JSONDecodeError:
        return 0, 0, 0.0, "parse_error"
    except (KeyError, TypeError):
        return 0, 0, 0.0, "schema_error"


def _merge_prd_passes(
    new_stories: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve ``passes: true`` from existing stories in the new story list.

    When ralph_loop is re-invoked, the caller may pass the original PRD
    with all ``passes: false``.  This helper merges the on-disk completion
    state so already-completed stories aren't reset.

    Returns the new_stories list (mutated in place for efficiency).
    """
    existing_passes = {s["id"]: s.get("passes", False) for s in existing_stories}
    for story in new_stories:
        if existing_passes.get(story.get("id")):
            story["passes"] = True
    return new_stories


_PROGRESS_READ_MAX_BYTES = 256 * 1024  # 256 KB — bounded read to defend
# against pathological growth (e.g. an agent repeatedly appending to
# progress.txt without honoring our truncation contract). The worker-side
# truncation in run.py (`_truncate_patterns_block`) caps what gets fed
# into the worker prompt; this read cap is a belt-and-suspenders defense
# against reading gigabytes into memory in the first place. Last 256 KB
# is where the recent patterns live, which is what matters.


def _read_progress_patterns(workspace_root: str) -> str:
    """Extract the ``## Codebase Patterns`` section from progress.txt.

    Returns the patterns text, or an empty string if not found.

    Reads only the last ``_PROGRESS_READ_MAX_BYTES`` bytes to avoid OOM
    on pathologically large progress.txt files.
    """
    progress_path = FilePath(workspace_root) / "progress.txt"
    try:
        size = progress_path.stat().st_size
        if size <= _PROGRESS_READ_MAX_BYTES:
            content = progress_path.read_text()
        else:
            # Read the tail — the most recent content — and let the
            # marker search below find the Codebase Patterns section if
            # it's in that window.
            with progress_path.open("rb") as fh:
                fh.seek(size - _PROGRESS_READ_MAX_BYTES)
                content = fh.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""

    # Find the Codebase Patterns section — it starts with the header and
    # ends at the next ``## `` heading or end of file.
    marker = "## Codebase Patterns"
    idx = content.find(marker)
    if idx == -1:
        return ""
    # Find the next section heading after the marker line
    rest = content[idx + len(marker) :]
    next_heading = rest.find("\n## ")
    if next_heading != -1:
        return (marker + rest[:next_heading]).strip()
    return (marker + rest).strip()
