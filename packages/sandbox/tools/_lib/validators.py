"""Shared validation helpers extracted from web.py and mobile.py.

Provides common input validation for project names, env filenames,
port numbers, commit messages, and numeric limits.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import git
from git.exc import InvalidGitRepositoryError

logger = logging.getLogger(__name__)

# ── Patterns ────────────────────────────────────────────────────────────────
VALID_NAME_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9_\-]*$"
VALID_ENV_FILE_PATTERN = r"^\.env(\.[a-zA-Z0-9_\-]+)?$"
MAX_CHECKPOINT_LIMIT = 100


# ── Validators ──────────────────────────────────────────────────────────────


def validate_name(name: str, field_name: str) -> None:
    """Validate project/template names to prevent path traversal and injection.

    Args:
        name: The name to validate.
        field_name: Human-readable field name for error messages.

    Raises:
        ValueError: If the name is invalid.
    """
    if name is None:
        raise ValueError(f"{field_name} cannot be None. Please provide a valid name.")

    name = str(name).strip()

    if not name:
        raise ValueError(f"{field_name} cannot be empty. Hint: Use descriptive names like 'my-project' or 'webapp-v2'")

    if len(name) > 100:
        raise ValueError(f"{field_name} is too long ({len(name)} characters). Maximum length is 100 characters.")

    if ".." in name or name.startswith("/") or name.startswith("\\"):
        raise ValueError(
            f"Invalid {field_name}: '{name}' contains path traversal characters. "
            f"Security: Path traversal is not allowed."
        )

    if not re.match(VALID_NAME_PATTERN, name):
        raise ValueError(
            f"Invalid {field_name}: '{name}'. "
            f"Only alphanumeric characters, hyphens, and underscores allowed. "
            f"Must start with a letter or number. "
            f"Hint: Use names like 'my-project', 'webapp_v2', or 'MyApp'"
        )


def validate_env_filename(env_file: str) -> None:
    """Validate env filename to prevent file access outside project.

    Args:
        env_file: The env filename to validate.

    Raises:
        ValueError: If the filename is invalid.
    """
    if env_file is None:
        raise ValueError("env_file cannot be None. Use '.env.local' as default.")

    env_file = str(env_file).strip()

    if not env_file:
        raise ValueError("env_file cannot be empty. Hint: Use '.env.local', '.env.production', or '.env.development'")

    if "/" in env_file or "\\" in env_file or ".." in env_file:
        raise ValueError(
            f"Invalid env_file: '{env_file}'. "
            "Must be a simple filename without path separators. "
            "Security: Path traversal is not allowed. "
            "Hint: Use '.env.local', '.env.production', etc."
        )

    if not re.match(VALID_ENV_FILE_PATTERN, env_file):
        raise ValueError(
            f"Invalid env_file: '{env_file}'. "
            "Must match pattern '.env' or '.env.<suffix>'. "
            "Hint: Valid examples: '.env', '.env.local', '.env.production'"
        )


def validate_port(port: int) -> None:
    """Validate port number.

    Args:
        port: The port number to validate.

    Raises:
        ValueError: If the port is invalid.
    """
    if not isinstance(port, int):
        raise ValueError(
            f"Port must be an integer, got {type(port).__name__}. Hint: Use port numbers like 3000, 8080, or 13600"
        )

    if port < 1 or port > 65535:
        raise ValueError(
            f"Port {port} is out of range. Must be between 1 and 65535. "
            f"Hint: Common development ports are 3000, 8080, or 5000"
        )

    if port < 1024:
        logger.warning(f"Port {port} is a privileged port (<1024) and may require elevated permissions")


def validate_commit_message(message: str) -> None:
    """Validate git commit message.

    Args:
        message: The commit message to validate.

    Raises:
        ValueError: If the message is invalid.
    """
    if message is None:
        raise ValueError("Commit message cannot be None. Provide a descriptive message.")

    message = str(message).strip()

    if not message:
        raise ValueError(
            "Commit message cannot be empty. Hint: Describe what changed, e.g., 'Added user authentication feature'"
        )

    if len(message) > 500:
        raise ValueError(
            f"Commit message is too long ({len(message)} characters). "
            f"Maximum length is 500 characters. "
            f"Hint: Keep the first line under 72 characters for best practices"
        )


def validate_limit(limit: int, max_limit: int, field_name: str = "limit") -> int:
    """Validate and constrain a limit parameter.

    Args:
        limit: The limit value to validate.
        max_limit: Maximum allowed limit.
        field_name: Human-readable field name for error messages.

    Returns:
        The validated limit (clamped to max_limit if needed).

    Raises:
        ValueError: If the limit is invalid.
    """
    if not isinstance(limit, int):
        raise ValueError(
            f"{field_name} must be an integer, got {type(limit).__name__}. Hint: Use a number like 10 or 20"
        )

    if limit < 1:
        raise ValueError(f"{field_name} must be at least 1, got {limit}. Hint: Use a positive number")

    if limit > max_limit:
        logger.info(f"{field_name} {limit} exceeds maximum {max_limit}, using {max_limit}")
        return max_limit

    return limit


# ── Git helpers ─────────────────────────────────────────────────────────────


def ensure_git_config(repo: git.Repo) -> None:
    """Ensure git user configuration exists, set defaults if not.

    Args:
        repo: Git repository object.
    """
    try:
        user_name = repo.config_reader().get_value("user", "name", default=None)
    except Exception:
        user_name = None

    try:
        user_email = repo.config_reader().get_value("user", "email", default=None)
    except Exception:
        user_email = None

    with repo.config_writer() as config:
        if not user_name:
            config.set_value("user", "name", "MCP Template Manager")
        if not user_email:
            config.set_value("user", "email", "mcp@template-manager.local")


def initialize_git_repo(project_path: Path) -> git.Repo:
    """Initialize git repository if not already initialized.

    Args:
        project_path: Path to the project directory.

    Returns:
        The git.Repo object.
    """
    try:
        repo = git.Repo(project_path)
    except InvalidGitRepositoryError:
        repo = git.Repo.init(project_path)
        repo.index.add("*")
        repo.index.commit("Initial commit - Template copied")

    ensure_git_config(repo)
    return repo
