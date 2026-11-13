"""Git operations tool — unified checkpoint management for web and mobile projects.

Extracts the duplicated checkpoint/list/rollback logic from ``web.py`` and
``mobile.py`` into a single tool.  Both the webdev and mobiledev tools call
``set_project_path()`` when the active project changes so this tool always
operates on the correct project directory.
"""

from __future__ import annotations

__version__ = "0.1.0"

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

import git
from _lib.utils import alias_hint, error_result, resolve_alias, success_result
from _lib.validators import (
    MAX_CHECKPOINT_LIMIT,
    ensure_git_config,
    initialize_git_repo,
    validate_commit_message,
    validate_limit,
)
from exo import tool
from git.exc import BadName, GitCommandError, InvalidGitRepositoryError

logger = logging.getLogger(__name__)

# ── Module-level project path (set by webdev/mobiledev tools) ───────────────
_current_project_path: Path | None = None


def set_project_path(path: Path | None) -> None:
    """Set the active project path for git operations.

    Called by web/mobile project and init tools when the user switches
    projects via their ``set`` action or initializes a new project.
    """
    global _current_project_path
    _current_project_path = path


def get_project_path() -> Path:
    """Return the current project path or raise if not set."""
    if _current_project_path is None:
        raise ValueError(
            "No current project set. "
            "Hint: Use the webdev or mobiledev tool with action='set_project' first, "
            "or action='init' to create a new project."
        )
    if not _current_project_path.exists():
        raise ValueError(
            f"Current project path '{_current_project_path}' no longer exists. Hint: The project may have been deleted."
        )
    return _current_project_path


_GIT_ALIASES: dict[str, str] = {
    "save": "checkpoint",
    "commit": "checkpoint",
    "snapshot": "checkpoint",
    "backup": "checkpoint",
    "preserve": "checkpoint",
    "store": "checkpoint",
    "log": "list",
    "history": "list",
    "show": "list",
    "commits": "list",
    "checkpoints": "list",
    "display": "list",
    "view": "list",
    "revert": "rollback",
    "undo": "rollback",
    "restore": "rollback",
    "reset": "rollback",
    "recover": "rollback",
    "go_back": "rollback",
}


@tool(name="git")
def git_tool(
    action: Annotated[
        Literal["checkpoint", "list", "rollback"],
        "The action to perform. Supported values: checkpoint, list, rollback.",
    ],
    commit_message: Annotated[
        str | None,
        "Descriptive message for the checkpoint commit. Required for checkpoint action.",
    ] = None,
    commit_hash: Annotated[
        str | None,
        "Target commit hash to rollback to (min 4 hex chars). Required for rollback action.",
    ] = None,
    limit: Annotated[
        int,
        "Maximum number of checkpoints to list. Optional, defaults to 10.",
    ] = 10,
    hard: Annotated[
        bool,
        "Use hard reset for rollback (discards all uncommitted changes). Defaults to false.",
    ] = False,
) -> dict:
    """Manage project version control with git checkpoints.

    <instructions>
    - Use `checkpoint` to save the current state of the project before making significant changes.
    - Always provide a descriptive `commit_message` that explains what was accomplished.
    - Use `list` to review recent checkpoints before deciding on a rollback target.
    - Soft rollback (default) keeps current changes as uncommitted — use this when you want to preserve work.
    - Hard rollback discards ALL uncommitted changes — use with extreme caution and only when explicitly requested.
    - MUST create a checkpoint before attempting risky operations to ensure a safe restore point.
    </instructions>

    <recommended_usage>
    - Use `checkpoint` to save progress after completing a significant piece of work.
    - Use `checkpoint` before making risky or experimental changes.
    - Use `list` to review project history and find rollback targets.
    - Use `rollback` to restore the project to a known good state when something goes wrong.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _GIT_ALIASES)

    if action == "checkpoint":
        return alias_hint(_create_checkpoint(commit_message), _alias, action)
    elif action == "list":
        return alias_hint(_list_checkpoints(limit), _alias, action)
    elif action == "rollback":
        return alias_hint(_rollback_checkpoint(commit_hash, hard), _alias, action)
    else:
        return error_result(
            f"Unknown action '{action}'.",
            hint="Valid actions: 'checkpoint', 'list', 'rollback'.",
        )


# ── Action implementations ──────────────────────────────────────────────────


def _create_checkpoint(commit_message: str | None) -> dict:
    """Create a git checkpoint (commit) of the current project state."""
    if not commit_message or not str(commit_message).strip():
        return error_result(
            "commit_message is required and cannot be empty.",
            hint="Provide a descriptive message, e.g. commit_message='Added login page'.",
        )

    try:
        validate_commit_message(commit_message)
    except ValueError as e:
        return error_result(str(e), hint="Commit messages must be non-empty and under 500 characters.")

    try:
        project_path = get_project_path()
        repo = initialize_git_repo(project_path)

        # Stage all changes
        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(project_path),
            capture_output=True,
            text=True,
            timeout=180,
        )

        # Check if there are changes to commit
        try:
            head_exists = repo.head.is_valid()
        except Exception:
            head_exists = False

        if head_exists:
            if not repo.index.diff("HEAD") and not repo.untracked_files:
                return error_result(
                    "No changes to checkpoint.",
                    hint="Make some changes to your project files before creating a checkpoint.",
                )
        elif not repo.untracked_files:
            return error_result(
                "No changes to checkpoint.",
                hint="Add some files to your project before creating a checkpoint.",
            )

        commit = repo.index.commit(commit_message.strip())

        return success_result(
            "Checkpoint created successfully",
            commit=commit.hexsha[:8],
            commit_message=commit_message.strip(),
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    except ValueError as e:
        return error_result(str(e), hint="Use action='set_project' or action='init' first.")
    except GitCommandError as e:
        return error_result(
            f"Git error: {e}",
            hint="Check that git is properly configured.",
        )
    except Exception as e:
        logger.exception("Error creating checkpoint: %s", e)
        return error_result(
            f"Error creating checkpoint: {e}",
            hint="An unexpected error occurred during git commit. Verify the project directory is writable and git is installed.",
        )


def _list_checkpoints(limit: int) -> dict:
    """List recent checkpoints (git commits) for the current project."""
    try:
        limit = validate_limit(limit, MAX_CHECKPOINT_LIMIT, "limit")
    except ValueError as e:
        return error_result(str(e), hint="limit must be a positive integer (max 100).")

    try:
        project_path = get_project_path()
        repo = git.Repo(project_path)
        ensure_git_config(repo)
        commits = list(repo.iter_commits(max_count=limit))

        if not commits:
            return error_result(
                "No checkpoints found.",
                hint="Create a checkpoint using the git tool with action='checkpoint'.",
            )

        entries = []
        for commit in commits:
            date = datetime.fromtimestamp(commit.committed_date).strftime("%Y-%m-%d %H:%M:%S")
            entries.append(
                {
                    "hash": commit.hexsha[:8],
                    "message": commit.message.strip(),
                    "author": commit.author.name,
                    "date": date,
                }
            )

        return success_result(
            f"Found {len(entries)} checkpoint(s)",
            checkpoints=entries,
            count=len(entries),
        )

    except ValueError as e:
        return error_result(str(e), hint="Use action='set_project' or action='init' first.")
    except InvalidGitRepositoryError:
        return error_result(
            "Project is not a git repository.",
            hint="Create a checkpoint first with action='checkpoint' to initialize git.",
        )
    except Exception as e:
        return error_result(
            f"Error listing checkpoints: {e}",
            hint="Verify a project is set and the project directory contains a valid git repository.",
        )


def _rollback_checkpoint(commit_hash: str | None, hard: bool) -> dict:
    """Rollback the current project to a previous checkpoint."""
    if not commit_hash or not commit_hash.strip():
        return error_result(
            "commit_hash is required for rollback action.",
            hint="Use the git tool with action='list' to see available commits.",
        )

    commit_hash = commit_hash.strip()

    if not re.match(r"^[a-fA-F0-9]{4,40}$", commit_hash):
        return error_result(
            f"Invalid commit hash format '{commit_hash}'.",
            hint="Commit hashes should be 4-40 hexadecimal characters. Use action='list' to see valid hashes.",
        )

    try:
        project_path = get_project_path()
        repo = git.Repo(project_path)
        ensure_git_config(repo)

        try:
            commit = repo.commit(commit_hash)
        except (GitCommandError, BadName, ValueError):
            return error_result(
                f"Commit '{commit_hash}' not found.",
                hint="Use action='list' to see available commits. Use at least 4 characters of the hash.",
            )

        if hard:
            logger.warning("Performing hard rollback to %s — discarding all changes", commit_hash)
            repo.head.reset(commit, index=True, working_tree=True)
            mode = "HARD (all changes discarded)"
        else:
            repo.head.reset(commit, index=False, working_tree=False)
            mode = "SOFT (changes kept as uncommitted)"

        return success_result(
            f"Rolled back to checkpoint: {commit.hexsha[:8]}",
            commit=commit.hexsha[:8],
            commit_message=commit.message.strip(),
            mode=mode,
        )

    except ValueError as e:
        return error_result(str(e), hint="Use action='set_project' or action='init' first.")
    except InvalidGitRepositoryError:
        return error_result(
            "Project is not a git repository.",
            hint="Initialize git with action='checkpoint'.",
        )
    except GitCommandError as e:
        return error_result(
            f"Git error: {e}",
            hint="Make sure there are no conflicts and your working directory is clean.",
        )
    except Exception as e:
        logger.exception("Error rolling back: %s", e)
        return error_result(
            f"Error rolling back: {e}",
            hint="Verify the project directory is writable and the git repository is not in a conflicted state.",
        )


GIT_TOOLS = [git_tool]
