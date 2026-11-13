"""Canonical format and path helpers for Knowledge Manager files.

All reads/writes of ``<workspace>/.sukuna/km/**`` flow through this module.  It
is the single source of truth for:

- the on-disk layout (``_project/<category>/<slug>.md`` and
  ``<conversation_id>/<category>/<slug>.md``)
- the trust-tiered file format (``## Summary`` section is injectable,
  ``## Raw`` section is never injected)
- the sandboxed path resolver (refuses absolutes, ``..``, and anything outside
  the KM root)

The knowledge manager's ``km_*`` tools and the ``km_rebuild_index`` management command
both import helpers from here.  The file is the canonical source of truth;
``VitalInformation`` rows are a derived index.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Literal, Sequence

import yaml
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KM_ROOT_DIRNAME: str = ".sukuna/km"
KM_SUMMARY_MARKER: str = "## Summary"
KM_RAW_MARKER: str = "## Raw"
KM_PROJECT_SCOPE_DIR: str = "_project"

VALID_CATEGORIES: frozenset[str] = frozenset({"requirement", "research", "decision", "issue", "resource", "visual"})
VALID_SCOPES: frozenset[str] = frozenset({"conversation", "project"})

_CATEGORY_DIRS: dict[str, str] = {
    "requirement": "requirement",
    "research": "research",
    "decision": "decision",
    "issue": "issue",
    "resource": "resource",
    "visual": "visual",
}

_CATEGORY_LABELS: dict[str, str] = {
    "requirement": "Requirements",
    "research": "Research Findings",
    "decision": "Technical Decisions",
    "issue": "Issues & Resolutions",
    "resource": "Resources",
    "visual": "Visual Findings",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class KMFileFrontmatter(BaseModel):
    """YAML frontmatter for a knowledge manager file."""

    title: str
    category: str
    scope: Literal["conversation", "project"]
    rationale: str = ""
    supersedes: list[str] = Field(default_factory=list)
    created_run_id: str = ""
    updated_at: str = ""  # ISO8601


class KMFile(BaseModel):
    """A parsed knowledge manager file.

    The trust-tier split is load-bearing: ``summary`` is derived by the
    knowledge manager and safe to inject into planner/executor context; ``raw`` may
    contain untrusted external tool output (web fetches, file dumps) and must
    NEVER be surfaced via ``format_for_injection``.
    """

    frontmatter: KMFileFrontmatter
    summary: str
    raw: str = ""


# ---------------------------------------------------------------------------
# Workspace / path helpers
# ---------------------------------------------------------------------------


def workspace_root() -> Path:
    """Return the current workspace root.

    Mirrors ``tools/file/ops.py``'s ``_project_dir`` resolution so KM files
    always land in the same workspace the standard file tools see.
    """
    return Path(
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(Path.home())
    )


def km_root(workspace: Path | None = None) -> Path:
    """Return ``<workspace>/.sukuna/km`` as an absolute path."""
    ws = workspace if workspace is not None else workspace_root()
    return (ws / KM_ROOT_DIRNAME).resolve(strict=False)


def km_project_dir(workspace: Path | None = None) -> Path:
    return km_root(workspace) / KM_PROJECT_SCOPE_DIR


def km_conversation_dir(conversation_id: str, workspace: Path | None = None) -> Path:
    if not conversation_id or conversation_id == KM_PROJECT_SCOPE_DIR:
        raise ValueError(f"Invalid conversation_id for KM dir: {conversation_id!r}")
    return km_root(workspace) / conversation_id


def category_subdir(category: str) -> str:
    """Return the on-disk subdirectory name for a category."""
    if category not in _CATEGORY_DIRS:
        raise ValueError(f"Unknown KM category {category!r}; expected one of {sorted(VALID_CATEGORIES)}")
    return _CATEGORY_DIRS[category]


def slugify(title: str, max_len: int = 64) -> str:
    """Turn a human title into a filesystem-safe slug."""
    lowered = title.strip().lower()
    slug = _SLUG_RE.sub("-", lowered).strip("-")
    if not slug:
        slug = "untitled"
    if len(slug) > max_len:
        slug = slug[:max_len].rstrip("-")
    return slug


def build_relative_path(
    *,
    scope: str,
    conversation_id: str,
    category: str,
    slug: str,
) -> str:
    """Build the KM-relative path for a file.

    Returns a path like ``_project/decision/db-choice.md`` or
    ``<conversation_id>/issue/timeout-on-startup.md``.  The result is relative
    to ``<workspace>/.sukuna/km/``.
    """
    if scope not in VALID_SCOPES:
        raise ValueError(f"Invalid scope {scope!r}; expected one of {sorted(VALID_SCOPES)}")
    if scope == "project":
        top = KM_PROJECT_SCOPE_DIR
    else:
        if not conversation_id:
            raise ValueError("conversation_id required for conversation-scoped files")
        top = conversation_id
    return f"{top}/{category_subdir(category)}/{slug}.md"


def _resolve_km_path(relative: str, workspace: Path | None = None) -> Path:
    """Resolve a KM-relative path to an absolute path inside the KM root.

    Raises ``ValueError`` if:
    - ``relative`` is absolute
    - any segment is ``..``
    - the resolved path escapes ``<workspace>/.sukuna/km/``
    """
    if not relative or not isinstance(relative, str):
        raise ValueError("KM path must be a non-empty string")
    rel = relative.strip()
    if "\x00" in rel:
        raise ValueError("KM path contains null byte")
    if rel.startswith("/") or rel.startswith("\\"):
        raise ValueError(f"KM path must be relative, got absolute: {relative!r}")
    rel_path = Path(rel)
    if rel_path.is_absolute():
        raise ValueError(f"KM path must be relative, got absolute: {relative!r}")
    for part in rel_path.parts:
        if part == "..":
            raise ValueError(f"KM path must not contain '..' segments: {relative!r}")

    root = km_root(workspace)
    candidate = (root / rel_path).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"KM path {relative!r} escapes the KM root ({root_resolved})") from exc
    return candidate


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def content_hash(body: str) -> str:
    """Return the sha256 hex digest of a normalized file body.

    Newlines are normalized to ``\\n`` so hashes are stable across platforms.
    """
    normalized = body.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def dump_km_file(file: KMFile) -> str:
    """Serialize a ``KMFile`` to the canonical markdown-with-frontmatter form.

    The output always contains both ``## Summary`` and ``## Raw`` headings
    (even when ``file.raw`` is empty) so ``parse_km_file`` can rely on
    structure.
    """
    frontmatter_dict = file.frontmatter.model_dump()
    # sort_keys=False preserves declaration order; default_flow_style=False keeps
    # it human-readable.
    yaml_text = yaml.safe_dump(
        frontmatter_dict,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    ).strip()
    summary_body = file.summary.strip("\n")
    raw_body = (file.raw or "").strip("\n")
    parts = [
        "---",
        yaml_text,
        "---",
        "",
        KM_SUMMARY_MARKER,
        "",
        summary_body,
        "",
        KM_RAW_MARKER,
        "",
        raw_body,
        "",
    ]
    return "\n".join(parts)


def parse_km_file(text: str) -> KMFile:
    """Parse canonical KM markdown back into a ``KMFile``.

    Tolerant of missing/empty ``## Raw`` section.  Raises ``ValueError`` if
    frontmatter or ``## Summary`` is missing or malformed.
    """
    if not text or not text.strip():
        raise ValueError("Empty KM file")

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("KM file must start with YAML frontmatter delimited by '---'")

    # Find closing frontmatter fence
    closing_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            closing_idx = i
            break
    if closing_idx is None:
        raise ValueError("KM file frontmatter is not closed with '---'")

    yaml_text = "\n".join(lines[1:closing_idx])
    try:
        frontmatter_raw = yaml.safe_load(yaml_text) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"KM file frontmatter YAML is invalid: {exc}") from exc
    if not isinstance(frontmatter_raw, dict):
        raise ValueError("KM file frontmatter must be a mapping")

    frontmatter = KMFileFrontmatter.model_validate(frontmatter_raw)

    body_lines = lines[closing_idx + 1 :]
    # Find ## Summary and ## Raw headings
    summary_start: int | None = None
    raw_start: int | None = None
    for i, ln in enumerate(body_lines):
        stripped = ln.strip()
        if summary_start is None and stripped == KM_SUMMARY_MARKER:
            summary_start = i + 1
        elif stripped == KM_RAW_MARKER:
            raw_start = i + 1
            break

    if summary_start is None:
        raise ValueError(f"KM file missing '{KM_SUMMARY_MARKER}' section")

    if raw_start is None:
        summary_body = "\n".join(body_lines[summary_start:]).strip("\n")
        raw_body = ""
    else:
        summary_body = "\n".join(body_lines[summary_start : raw_start - 1]).strip("\n")
        raw_body = "\n".join(body_lines[raw_start:]).strip("\n")

    return KMFile(frontmatter=frontmatter, summary=summary_body, raw=raw_body)


# ---------------------------------------------------------------------------
# Injection formatter (trust-tier enforcement)
# ---------------------------------------------------------------------------

_INJECTION_MARKER = "<!-- VITAL_INFORMATION -->"


def format_for_injection(files: Sequence[KMFile]) -> str:
    """Format a list of ``KMFile``s as a markdown block for ephemeral injection.

    HARD INVARIANT: this function only references ``file.summary`` — it must
    never emit any content from ``file.raw``.  Enforced by a dedicated unit
    test in ``tests/test_km_files.py``.
    """
    if not files:
        return ""

    by_category: dict[str, list[KMFile]] = {}
    for f in files:
        by_category.setdefault(f.frontmatter.category, []).append(f)

    parts: list[str] = [
        _INJECTION_MARKER,
        "<vital-information>",
        "## Vital Information (Knowledge Manager)",
        "",
    ]
    for category, label in _CATEGORY_LABELS.items():
        bucket = by_category.get(category, [])
        if not bucket:
            continue
        parts.append(f"### {label}")
        for f in bucket:
            parts.append(f"- **{f.frontmatter.title}**: {f.summary.strip()}")
            if f.frontmatter.rationale:
                parts.append(f"  _Rationale: {f.frontmatter.rationale}_")
        parts.append("")
    parts.append("</vital-information>")
    return "\n".join(parts)
