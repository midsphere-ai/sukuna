"""Match tool — find files or text in the sandbox using pattern matching."""

from __future__ import annotations

__version__ = "0.1.0"

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Literal

from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from exo import tool

logger = logging.getLogger(__name__)


def _workspace_root() -> Path:
    return Path(
        os.environ.get("PROJECT_DIR")
        or os.environ.get("WORKSPACE")
        or os.environ.get("SANDBOX_WORKSPACE_ROOT")
        or str(Path.home())
    )


_project_dir = _workspace_root()
_scope_example = f"{_project_dir}/**/*.py"

MAX_RESULTS = 500
MAX_CONTENT_LINES = 2000


_FIND_ALIASES: dict[str, str] = {
    "find": "glob",
    "search": "glob",
    "locate": "glob",
    "list": "glob",
    "files": "glob",
    "scan": "glob",
    "discover": "glob",
    "ls": "glob",
    "match": "glob",
    "text": "grep",
    "content": "grep",
    "regex": "grep",
    "pattern": "grep",
    "rg": "grep",
    "ripgrep": "grep",
    "search_text": "grep",
}


@tool(name="match")
async def find_tool(
    action: Annotated[
        Literal["glob", "grep"],
        "The action to perform. Supported values: glob, grep.",
    ],
    scope: Annotated[
        str,
        "The glob pattern that defines the absolute file path and name scope.",
    ],
    regex: Annotated[
        str | None,
        "The regex pattern to match file content. Required for grep action.",
    ] = None,
    leading: Annotated[
        int | None,
        "Number of lines to include before each match as context. Optional and only used for grep action. Defaults to 0.",
    ] = None,
    trailing: Annotated[
        int | None,
        "Number of lines to include after each match as context. Optional and only used for grep action. Defaults to 0.",
    ] = None,
) -> dict:
    """Find files or text in the sandbox file system using pattern matching.

    <instructions>
    - `glob` action matches only file names and paths, returning a list of matching files.
    - `grep` action searches for a `regex` pattern inside all files matching `scope`, returning matched text snippets.
    - `scope` defines the glob pattern that restricts the search range for both `glob` and `grep` actions.
    - `scope` must be a glob pattern using absolute paths, e.g., `/absolute/path/**/*.py`.
    - `regex` applies only to `grep` action and is case sensitive by default.
    - Results are returned in descending order of file modification time for both actions.
    </instructions>

    <recommended_usage>
    - Use `glob` to locate files by name, extension, or directory pattern.
    - Use `grep` to find occurrences of specific text across files.
    - Use `grep` with `leading` and `trailing` to view surrounding context in code or logs.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _FIND_ALIASES)

    try:
        if action == "glob":
            if not scope:
                return error_result(
                    "Missing required parameter: scope. Provide a glob pattern.",
                    hint=f"Use scope='{_scope_example}' for an absolute glob pattern.",
                )
            return alias_hint(await _do_glob(scope), _alias, action)
        elif action == "grep":
            if not scope:
                return error_result(
                    "Missing required parameter: scope. Provide a glob pattern.",
                    hint=f"Use scope='{_scope_example}' to restrict which files to search.",
                )
            if not regex:
                return error_result(
                    "Missing required parameter: regex. Provide a search pattern.",
                    hint="Use regex='pattern' to search file contents. Example: regex='import os'.",
                )
            return alias_hint(await _do_grep(scope, regex, leading or 0, trailing or 0), _alias, action)
        else:
            return error_result(f"Unknown action: {action}. Use 'glob' or 'grep'.")
    except Exception as e:
        logger.exception("find_tool error: %s", e)
        return error_result(
            f"Find operation failed: {e}", hint="An unexpected error occurred. Check the scope pattern and try again."
        )


def _resolve_glob(pattern: str) -> tuple[Path, str]:
    """Split a glob pattern into (base_dir, relative_pattern).

    Absolute patterns are split at the first glob character. Relative patterns
    are evaluated against the project directory.
    """
    if os.path.isabs(pattern):
        parts = Path(pattern).parts
        base_parts: list[str] = []
        glob_parts: list[str] = []
        hit_glob = False
        for part in parts:
            if not hit_glob and not any(c in part for c in ("*", "?", "[")):
                base_parts.append(part)
            else:
                hit_glob = True
                glob_parts.append(part)
        base = Path(*base_parts) if base_parts else Path("/")
        rel_pattern = str(Path(*glob_parts)) if glob_parts else "*"
    else:
        base = _project_dir
        rel_pattern = pattern
    return base, rel_pattern


def _glob_files_by_mtime(base: Path, rel_pattern: str, limit: int = MAX_RESULTS) -> list[Path]:
    """Glob for files and return them sorted by modification time descending."""
    files: list[Path] = []
    for p in base.glob(rel_pattern):
        if p.is_file():
            files.append(p)
            # Collect more than limit to allow proper mtime sorting, but cap to
            # avoid scanning enormous trees.  10x limit is a reasonable budget.
            if len(files) >= limit * 10:
                break

    # Sort by modification time descending
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


async def _do_glob(pattern: str) -> dict:
    """Find files matching a glob pattern, sorted by modification time descending."""
    try:
        base, rel_pattern = _resolve_glob(pattern)

        if not base.is_dir():
            return error_result(
                f"Base directory does not exist: {base}",
                hint="Check that the path is correct and the directory exists.",
            )

        matches = _glob_files_by_mtime(base, rel_pattern)
        file_paths = [str(p) for p in matches]

        return success_result(
            f"Found {len(file_paths)} file(s) matching '{pattern}'",
            files=file_paths,
            truncated=len(file_paths) >= MAX_RESULTS,
        )
    except Exception as e:
        return error_result(
            f"Glob error: {e}",
            hint=f"Use absolute glob patterns like '{_scope_example}'.",
        )


async def _do_grep(scope: str, regex: str, leading: int, trailing: int) -> dict:
    """Search for regex inside files matching the scope glob pattern.

    Unlike a directory-based grep, *scope* is a glob pattern that restricts
    which files are searched.  For example ``/absolute/path/**/*.py`` searches
    all Python files under that path.
    """
    # Validate regex syntax before doing any work
    try:
        re.compile(regex)
    except re.error as e:
        return error_result(
            f"Invalid regex pattern: {e}",
            hint=f"The regex '{regex}' has a syntax error. Fix the pattern — common issues: unmatched brackets [], unescaped special characters, missing closing delimiters.",
        )

    # Resolve the glob to get matching files, sorted by mtime descending
    try:
        base, rel_pattern = _resolve_glob(scope)
        if not base.is_dir():
            return error_result(
                f"Base directory does not exist: {base}",
                hint="Check that the scope glob points to an existing directory tree.",
            )
        files = _glob_files_by_mtime(base, rel_pattern, limit=MAX_RESULTS)
    except Exception as e:
        return error_result(
            f"Scope glob error: {e}",
            hint=f"Use absolute glob patterns like '{_scope_example}'.",
        )

    if not files:
        return success_result(
            f"No files matched scope '{scope}'",
            matches="",
            match_count=0,
            truncated=False,
        )

    # Run grep on each matched file
    file_args = [str(f) for f in files]
    cmd = ["grep", "-n"]
    if leading > 0:
        cmd.extend(["-B", str(leading)])
    if trailing > 0:
        cmd.extend(["-A", str(trailing)])
    # -H ensures filenames are always printed, even with single file
    cmd.append("-H")
    cmd.extend(["--", regex])
    cmd.extend(file_args)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        if proc.returncode == 2 and stderr_text:
            return error_result(
                f"Grep failed: {stderr_text}",
                hint="The grep command encountered an error. Check the regex pattern syntax.",
            )

        output = stdout.decode("utf-8", errors="replace")
        lines = output.splitlines()
        truncated = len(lines) > MAX_CONTENT_LINES
        if truncated:
            lines = lines[:MAX_CONTENT_LINES]

        return success_result(
            f"Found {len(lines)} matching line(s) for /{regex}/",
            matches="\n".join(lines),
            match_count=len(lines),
            truncated=truncated,
        )
    except asyncio.TimeoutError:
        return error_result(
            "Grep timed out after 30 seconds.",
            hint="The search is too broad. Narrow the scope glob or use a more specific regex pattern.",
        )
    except Exception as e:
        return error_result(
            f"Grep error: {e}",
            hint="An unexpected error occurred. Verify the scope glob is valid.",
        )


FIND_TOOLS = [find_tool]
