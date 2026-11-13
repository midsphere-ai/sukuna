"""File system tools — native @tool implementations for file operations."""

__version__ = "0.1.0"

import json
import logging
import os
import shutil
import tempfile
import time
from functools import wraps
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import structlog
from _lib.utils import alias_hint, error_result, resolve_alias
from exo import tool
from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError
from igittigitt import IgnoreParser
from pythonjsonlogger.jsonlogger import JsonFormatter  # type: ignore[attr-defined]

# ─── Logger Initialization ─────────────────────
stdlogger = logging.getLogger(__name__)
logger = logging.getLogger(__name__)
structured_logger = structlog.get_logger(__name__)

# ─── Module Level Storage ─────────────────────
_project_dir: Optional[Path] = Path(
    os.environ.get("PROJECT_DIR")
    or os.environ.get("WORKSPACE")
    or os.environ.get("SANDBOX_WORKSPACE_ROOT")
    or str(Path.home())
)
_reference_projects: Dict[str, Path] = {}

# Path segments that are invisible to the standard file tool.  When a caller
# references one of these, the tool behaves exactly as if the path did not
# exist — same errno, same error text — so an adversarial prompt has no
# protection-flavoured signal to latch onto.  Used by the Knowledge Manager
# knowledge manager to keep its own storage out of reach of the planner / executor.
_HIDDEN_SEGMENTS: Tuple[str, ...] = (".sukuna",)


def _first_hidden_segment(path_like: Union[str, Path]) -> Optional[str]:
    """Return the first hidden segment found in ``path_like``, or None.

    Checks every component (not a prefix match) so ``a/.sukuna/b`` is also
    rejected.
    """
    parts = Path(str(path_like)).parts
    for part in parts:
        if part in _HIDDEN_SEGMENTS:
            return part
    return None


def _raise_not_found(path: str) -> None:
    """Raise a ``FileNotFoundError`` whose string matches the format the
    file tool itself emits for genuinely missing paths.

    Uses a lightweight file-vs-directory heuristic: a trailing slash or an
    extension-less basename (after stripping leading dots, so ``.sukuna``
    reads as a hidden directory rather than an extension) looks dir-like.
    This ensures the error phrasing matches what ``read_file_util`` /
    ``list_files_util`` would produce for a real miss.
    """
    p = str(path)
    basename = os.path.basename(p.rstrip("/"))
    name_after_leading_dots = basename.lstrip(".")
    looks_like_dir = p.endswith("/") or "." not in name_after_leading_dots
    if looks_like_dir:
        raise FileNotFoundError(f"Directory '{p}' does not exist")
    raise FileNotFoundError(f"File '{p}' does not exist")


T = TypeVar("T")


def setup_logging(log_level: str, log_file: Optional[str] = None) -> None:
    """Configure logging - if log_file specified, logs only to file; otherwise to console."""
    # Set log level
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {log_level}")

    # Clear existing handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    root_logger.setLevel(numeric_level)

    # Set up logging based on whether log_file is specified
    if log_file:
        # FILE LOGGING ONLY - no console output
        # Create directory if needed
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)

        # Configure JSON file handler
        json_handler = logging.FileHandler(log_file)

        # This formatter ensures timestamp and level are included as separate fields in JSON
        json_formatter = JsonFormatter(
            fmt="%(timestamp)s %(level)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d",
            timestamp=True,
        )
        json_handler.setFormatter(json_formatter)
        root_logger.addHandler(json_handler)

        # Configure structlog processors
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),  # Use JSONRenderer instead of wrap_for_formatter
            ],
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )

        # Log initialization message to file only
        stdlogger.info("Logging initialized: file=%s, level=%s", log_file, log_level)
    else:
        # CONSOLE LOGGING ONLY (fallback when no file specified)
        console_handler = logging.StreamHandler()
        console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(console_formatter)
        root_logger.addHandler(console_handler)

        stdlogger.info("Logging initialized: console=%s", log_level)


def log_function_call(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to log function calls with parameters, timing, and results."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        func_name = func.__name__
        module_name = func.__module__
        line_no = func.__code__.co_firstlineno

        # Prepare parameters for logging
        log_params = {}

        # Handle method calls (skip self/cls)
        if args and hasattr(args[0], "__class__") and args[0].__class__.__module__ != "builtins":
            log_params.update({k: v for k, v in zip(func.__code__.co_varnames[1 : len(args)], args[1:])})
        else:
            log_params.update({k: v for k, v in zip(func.__code__.co_varnames[: len(args)], args)})

        # Add keyword arguments
        log_params.update(kwargs)

        # Convert Path objects to strings and handle other non-serializable types
        serializable_params = {}
        for k, v in log_params.items():
            if isinstance(v, Path):
                serializable_params[k] = str(v)
            else:
                try:
                    # Test if it's JSON serializable
                    json.dumps(v)
                    serializable_params[k] = v
                except (TypeError, OverflowError):
                    # If not serializable, convert to string
                    serializable_params[k] = str(v)

        # Check if structured logging is enabled
        has_structured = any(isinstance(h, logging.FileHandler) for h in logging.getLogger().handlers)

        # Log function call - always provide 'event' as the first parameter
        if has_structured:
            structlogger = structlog.get_logger(module_name)
            structlogger.debug(
                f"Calling function {func_name}",  # This is the 'event' parameter
                function=func_name,
                parameters=serializable_params,
                module=module_name,
                lineno=line_no,
            )

        stdlogger.debug(
            "Calling %s with parameters: %s",
            func_name,
            json.dumps(serializable_params, default=str),
        )

        # Execute function and measure time
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            # Prepare result for logging
            result_for_log: Any
            serializable_result: Any
            if isinstance(result, (list, dict)) and len(str(result)) > 1000:
                result_for_log = f"<Large result of type {type(result).__name__}, length: {len(str(result))}>"
                serializable_result = result_for_log
            else:
                result_for_log = result
                # Make result JSON serializable for structured logging
                try:
                    json.dumps(result)  # Test if result is JSON serializable
                    serializable_result = result
                except (TypeError, OverflowError):
                    serializable_result = str(result) if result is not None else None

            # Log completion
            if has_structured:
                structlogger.debug(
                    f"Function {func_name} completed",  # This is the 'event' parameter
                    function=func_name,
                    execution_time_ms=elapsed_ms,
                    status="success",
                    result=serializable_result,
                    module=module_name,
                    lineno=line_no,
                )

            stdlogger.debug(
                "%s completed in %sms with result: %s",
                func_name,
                elapsed_ms,
                result_for_log,
            )
            return result

        except Exception as e:
            # Log exceptions
            elapsed_ms = round((time.time() - start_time) * 1000, 2)

            if has_structured:
                structlogger.error(
                    f"Function {func_name} failed",  # This is the 'event' parameter
                    function=func_name,
                    execution_time_ms=elapsed_ms,
                    error_type=type(e).__name__,
                    error_message=str(e),
                    module=module_name,
                    lineno=line_no,
                    exc_info=True,
                )

            stdlogger.error(
                "%s failed after %sms with error: %s: %s",
                func_name,
                elapsed_ms,
                type(e).__name__,
                str(e),
                exc_info=True,
            )
            raise

    return cast(Callable[..., T], wrapper)


def normalize_path(path: str, project_dir: Path) -> tuple[Path, str]:
    """
    Normalize a path to be relative to the project directory.

    Args:
        path: Path to normalize
        project_dir: Project directory path

    Returns:
        Tuple of (absolute path, relative path)

    Raises:
        ValueError: If the path is outside the project directory
    """
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    path_obj = Path(path)

    # Hidden segments (e.g. .sukuna — Knowledge Manager storage)
    # are made indistinguishable from missing files.  Raise the same error
    # Python's own filesystem layer would raise for a nonexistent path so no
    # prompt-injection footing is exposed.
    if _first_hidden_segment(path_obj) is not None:
        _raise_not_found(path)

    # If the path is absolute, make it relative to the project directory
    if path_obj.is_absolute():
        try:
            # Make sure the path is inside the project directory
            relative_path = path_obj.relative_to(project_dir)
            if _first_hidden_segment(relative_path) is not None:
                _raise_not_found(path)
            return path_obj, str(relative_path)
        except ValueError as exc:
            raise ValueError(
                f"Security error: Path '{path}' is outside the project directory '{project_dir}'. "
                f"All file operations must be within the project directory."
            ) from exc

    # If the path is already relative, make sure it doesn't try to escape
    absolute_path = project_dir / path_obj
    try:
        # Make sure the resolved path is inside the project directory
        # During testing, resolve() may fail on non-existent paths, so handle that case
        try:
            resolved_path = absolute_path.resolve()
            project_resolved = project_dir.resolve()
            # Check if the resolved path starts with the resolved project dir
            if os.path.commonpath([resolved_path, project_resolved]) != str(project_resolved):
                raise ValueError(
                    f"Security error: Path '{path}' resolves to a location outside "
                    f"the project directory '{project_dir}'. Path traversal is not allowed."
                )
        except (FileNotFoundError, OSError):
            # During testing with non-existent paths, just do a simple string check
            pass

        return absolute_path, str(path_obj)
    except ValueError as e:
        # If the error already has our detailed message, pass it through
        if "Security error:" in str(e):
            raise
        # Otherwise add more context
        raise ValueError(
            f"Security error: Path '{path}' is outside the project directory '{project_dir}'. "
            f"All file operations must be within the project directory."
        ) from e


def _discover_files(directory: Path, project_dir: Path) -> List[str]:
    """Discover all files recursively, excluding .git and hidden segments."""
    discovered_files = []

    for root, dirs, files in os.walk(directory):
        # Skip .git directories
        if ".git" in dirs:
            dirs.remove(".git")
        # Silently skip hidden segments (e.g. .sukuna — knowledge manager storage).
        # No error, no log — indistinguishable from the dir not existing.
        for hidden in _HIDDEN_SEGMENTS:
            if hidden in dirs:
                dirs.remove(hidden)

        root_path = Path(root)
        try:
            rel_root = root_path.relative_to(project_dir)
        except ValueError:
            continue

        for file in files:
            rel_file_path = str(rel_root / file)
            discovered_files.append(rel_file_path)

    return discovered_files


def read_gitignore_rules(
    gitignore_path: Path,
) -> Tuple[Optional[Callable[[str], bool]], Optional[str]]:
    """Read and parse a .gitignore file to create a matcher function.

    Args:
        gitignore_path: Path to the .gitignore file

    Returns:
        A tuple containing (matcher_function, gitignore_content), or (None, None) if file doesn't exist
    """
    if not gitignore_path.is_file():
        logger.info("No .gitignore file found at %s", gitignore_path)
        return None, None

    try:
        # Read the gitignore file content for logging
        with open(gitignore_path, "r") as f:
            gitignore_content = f.read()

        logger.info("Gitignore content: %s", gitignore_content)

        # Parse the gitignore file to get a matcher function
        logger.info("Parsing gitignore file at %s", gitignore_path)
        parser = IgnoreParser()
        parser.parse_rule_file(gitignore_path)

        # Create a matcher function that mimics the behavior of the old parse_gitignore
        def matcher(path: str) -> bool:
            return bool(parser.match(path))

        return matcher, gitignore_content

    except Exception as e:
        logger.warning("Error reading/parsing gitignore: %s", str(e))
        return None, None


def apply_gitignore_filter(
    file_paths: List[str], matcher: Optional[Callable[[str], bool]], project_dir: Path
) -> List[str]:
    """Filter a list of file paths using a gitignore matcher function.

    Args:
        file_paths: List of file paths to filter
        matcher: Function that takes a path and returns True if it should be ignored
        project_dir: Base directory for resolving relative paths to absolute

    Returns:
        Filtered list of file paths that are not ignored
    """
    if matcher is None:
        return file_paths

    filtered_files = []

    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    for file_path in file_paths:
        # Convert to absolute path for the matcher
        abs_file_path = str(project_dir / file_path)

        # The matcher returns True if the file should be ignored
        if not matcher(abs_file_path):
            filtered_files.append(file_path)

    logger.info(
        "Applied gitignore filtering: %s files found, %s after filtering",
        len(file_paths),
        len(filtered_files),
    )
    return filtered_files


def filter_with_gitignore(file_paths: List[str], base_dir: Path, project_dir: Path) -> List[str]:
    """Filter a list of file paths using .gitignore rules.

    Args:
        file_paths: List of file paths to filter
        base_dir: Directory containing the .gitignore file
        project_dir: Project directory path

    Returns:
        List of file paths that are not ignored
    """
    gitignore_path = base_dir / ".gitignore"

    # Get the matcher function from the gitignore file
    matcher, _ = read_gitignore_rules(gitignore_path)

    if matcher is None:
        return file_paths

    # Use the matcher for more complex gitignore patterns
    return apply_gitignore_filter(file_paths, matcher, project_dir)


def list_files_util(directory: Union[str, Path], project_dir: Path, use_gitignore: bool = True) -> List[str]:
    """List all files in a directory and its subdirectories with optional gitignore filtering.

    Args:
        directory: Directory to list files from
        project_dir: Project directory path
        use_gitignore: Whether to apply gitignore filtering

    Returns:
        List of file paths
    """
    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    abs_path, rel_path = normalize_path(str(directory), project_dir)

    if not abs_path.exists():
        raise FileNotFoundError(f"Directory '{directory}' does not exist")

    if not abs_path.is_dir():
        raise NotADirectoryError(f"Path '{directory}' is not a directory")

    try:
        all_files = _discover_files(abs_path, project_dir)
        logger.info("Discovered %s files in %s", len(all_files), rel_path)

        if not use_gitignore:
            return all_files

        # Apply gitignore filtering
        return filter_with_gitignore(all_files, abs_path, project_dir)

    except Exception as e:
        logger.error("Error listing files in directory %s: %s", rel_path, str(e))
        raise


# Backward compatibility alias
list_files = list_files_util


def read_file_util(file_path: str, project_dir: Path) -> str:
    """
    Read the contents of a file.

    Args:
        file_path: Path to the file to read (relative to project directory)
        project_dir: Project directory path

    Returns:
        The contents of the file as a string

    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If access to the file is denied
        ValueError: If the file is outside the project directory
    """
    # Validate file_path parameter
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    # Normalize the path to be relative to the project directory
    abs_path, rel_path = normalize_path(file_path, project_dir)

    if not abs_path.exists():
        logger.error("File not found: %s", file_path)
        raise FileNotFoundError(f"File '{file_path}' does not exist")

    if not abs_path.is_file():
        logger.error("Path is not a file: %s", file_path)
        raise IsADirectoryError(f"Path '{file_path}' is not a file")

    file_handle = None
    try:
        logger.debug("Reading file: %s", rel_path)
        file_handle = open(abs_path, "r", encoding="utf-8")
        content = file_handle.read()
        logger.debug("Successfully read %s bytes from %s", len(content), rel_path)
        return content
    except UnicodeDecodeError as e:
        logger.error("Unicode decode error while reading %s: %s", rel_path, str(e))
        raise ValueError(f"File '{file_path}' contains invalid characters. Ensure it's a valid text file.") from e
    except Exception as e:
        logger.error("Error reading file %s: %s", rel_path, str(e))
        raise
    finally:
        if file_handle is not None:
            file_handle.close()


def _validate_save_parameters(file_path: str, content: Any, project_dir: Path) -> tuple[Path, str, str]:
    """Validate and normalize save operation parameters.

    Args:
        file_path: Path to file (relative to project_dir)
        content: Content to write to file
        project_dir: Project directory path

    Returns:
        Tuple of (abs_path, rel_path, validated_content)

    Raises:
        ValueError: If parameters are invalid
    """
    # Validate file_path parameter
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    # Validate content parameter
    if content is None:
        logger.warning("Content is None, treating as empty string")
        content = ""
    elif not isinstance(content, str):
        logger.error("Invalid content type: %s", type(content))
        raise ValueError(f"Content must be a string, got {type(content)}")

    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    # Normalize the path to be relative to the project directory
    abs_path, rel_path = normalize_path(file_path, project_dir)

    return abs_path, rel_path, content


def _create_parent_directories(abs_path: Path) -> None:
    """Create parent directories if they don't exist.

    Args:
        abs_path: Absolute path to file

    Raises:
        PermissionError: If lacking permissions to create directories
        Exception: For other directory creation errors
    """
    try:
        if not abs_path.parent.exists():
            logger.info("Creating directory: %s", abs_path.parent)
            abs_path.parent.mkdir(parents=True)
    except PermissionError as e:
        logger.error("Permission denied creating directory %s: %s", abs_path.parent, str(e))
        raise
    except Exception as e:
        logger.error("Error creating directory %s: %s", abs_path.parent, str(e))
        raise


def _write_file_atomically(abs_path: Path, rel_path: str, content: str) -> bool:
    """Write file atomically using a temporary file.

    Args:
        abs_path: Absolute path to file
        rel_path: Relative path for logging
        content: Content to write

    Returns:
        True if successful

    Raises:
        ValueError: If content cannot be encoded
        Exception: For other write errors
    """
    # Use a temporary file for atomic write
    temp_file = None
    try:
        # Create a temporary file in the same directory as the target
        # This ensures the atomic move works across filesystems
        temp_fd, temp_path = tempfile.mkstemp(dir=str(abs_path.parent))
        temp_file = Path(temp_path)

        logger.debug("Writing to temporary file for %s", rel_path)

        # Write content to temporary file
        with open(temp_fd, "w", encoding="utf-8") as f:
            try:
                f.write(content)
            except UnicodeEncodeError as e:
                logger.error("Unicode encode error while writing to %s: %s", rel_path, str(e))
                raise ValueError(
                    "Content contains characters that cannot be encoded. Please check the encoding."
                ) from e

        # Atomically replace the target file
        logger.debug("Atomically replacing %s with temporary file", rel_path)
        try:
            # On Windows, we need to remove the target file first
            if os.name == "nt" and abs_path.exists():
                abs_path.unlink()
            os.replace(temp_path, str(abs_path))
        except Exception as e:
            logger.error("Error replacing file %s: %s", rel_path, str(e))
            raise

        logger.debug("Successfully wrote %s bytes to %s", len(content), rel_path)
        return True

    finally:
        # Clean up the temporary file if it still exists
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except Exception as e:
                logger.warning("Failed to clean up temporary file %s: %s", temp_file, str(e))


def save_file_util(file_path: str, content: Any, project_dir: Path) -> bool:
    """
    Write content to a file atomically.

    Args:
        file_path: Path to the file to write to (relative to project directory)
        content: Content to write to the file
        project_dir: Project directory path

    Returns:
        True if the file was written successfully

    Raises:
        PermissionError: If access to the file is denied
        ValueError: If the file is outside the project directory
    """
    # Validate and normalize parameters
    abs_path, rel_path, validated_content = _validate_save_parameters(file_path, content, project_dir)

    # Create parent directories if needed
    _create_parent_directories(abs_path)

    # Write file atomically
    return _write_file_atomically(abs_path, rel_path, validated_content)


# Backward compatibility alias
write_file = save_file_util


def append_file_util(file_path: str, content: Any, project_dir: Path) -> bool:
    """
    Append content to the end of a file.

    Args:
        file_path: Path to the file to append to (relative to project directory)
        content: Content to append to the file
        project_dir: Project directory path

    Returns:
        True if the content was appended successfully

    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If access to the file is denied
        ValueError: If the file is outside the project directory
    """
    # Validate file_path parameter
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    # Validate content parameter
    if content is None:
        logger.warning("Content is None, treating as empty string")
        content = ""
    elif not isinstance(content, str):
        logger.error("Invalid content type: %s", type(content))
        raise ValueError(f"Content must be a string, got {type(content)}")

    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    # Normalize the path to be relative to the project directory
    abs_path, rel_path = normalize_path(file_path, project_dir)

    # Check if the file exists
    if not abs_path.exists():
        logger.error("File not found: %s", file_path)
        raise FileNotFoundError(f"File '{file_path}' does not exist")

    if not abs_path.is_file():
        logger.error("Path is not a file: %s", file_path)
        raise IsADirectoryError(f"Path '{file_path}' is not a file")

    # Read existing content
    existing_content = read_file_util(file_path, project_dir)

    # Append new content
    combined_content = existing_content + content

    # Use save_file to write the combined content
    logger.debug("Appending %s bytes to %s", len(content), rel_path)
    return save_file_util(file_path, combined_content, project_dir)


def delete_file_util(file_path: str, project_dir: Path) -> bool:
    """
    Delete a file.

    Args:
        file_path: Path to the file to delete (relative to project directory)
        project_dir: Project directory path

    Returns:
        True if the file was deleted successfully

    Raises:
        FileNotFoundError: If the file does not exist
        PermissionError: If access to the file is denied
        IsADirectoryError: If the path points to a directory
        ValueError: If the file is outside the project directory or the parameter is invalid
    """
    # Validate file_path parameter
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    # Validate project_dir parameter
    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    # Normalize the path to be relative to the project directory
    abs_path, rel_path = normalize_path(file_path, project_dir)

    if not abs_path.exists():
        logger.error("File not found: %s", file_path)
        raise FileNotFoundError(f"File '{file_path}' does not exist")

    if not abs_path.is_file():
        logger.error("Path is not a file: %s", file_path)
        raise IsADirectoryError(f"Path '{file_path}' is not a file or is a directory")

    try:
        logger.debug("Deleting file: %s", rel_path)
        abs_path.unlink()
        logger.debug("Successfully deleted file: %s", rel_path)
        return True
    except PermissionError as e:
        logger.error("Permission denied when deleting file %s: %s", rel_path, str(e))
        raise
    except Exception as e:
        logger.error("Error deleting file %s: %s", rel_path, str(e))
        raise


def _validate_move_parameters(
    source_path: str, destination_path: str, project_dir: Path
) -> tuple[Path, str, Path, str]:
    """Validate and normalize move operation parameters.

    Args:
        source_path: Source file/directory path
        destination_path: Destination path
        project_dir: Project directory path

    Returns:
        Tuple of (src_abs, src_rel, dest_abs, dest_rel)

    Raises:
        ValueError: If paths are invalid
        FileNotFoundError: If source doesn't exist
        FileExistsError: If destination already exists
    """
    # Validate inputs
    if not source_path or not isinstance(source_path, str):
        raise ValueError(f"Source path must be a non-empty string, got {type(source_path)}")

    if not destination_path or not isinstance(destination_path, str):
        raise ValueError(f"Destination path must be a non-empty string, got {type(destination_path)}")

    if project_dir is None:
        raise ValueError("Project directory cannot be None")

    # Normalize paths (this also validates they're within project_dir)
    src_abs, src_rel = normalize_path(source_path, project_dir)
    dest_abs, dest_rel = normalize_path(destination_path, project_dir)

    # Check if source exists
    if not src_abs.exists():
        raise FileNotFoundError(f"Source file '{source_path}' does not exist")

    # Check if destination already exists
    if dest_abs.exists():
        raise FileExistsError(f"Destination '{destination_path}' already exists")

    return src_abs, src_rel, dest_abs, dest_rel


def _determine_move_method(src_abs: Path, project_dir: Path) -> bool:
    """Determine if git should be used for the move operation.

    Args:
        src_abs: Absolute path to source
        project_dir: Project directory path

    Returns:
        True if git should be used, False otherwise
    """
    if not is_git_repository(project_dir):
        return False

    # Simply check if the source is tracked (for files)
    # For directories, git mv will handle it or fail gracefully
    if src_abs.is_file():
        return is_file_tracked(src_abs, project_dir)
    else:
        # For directories, just try git mv and let it fail if needed
        return True


def _execute_git_move(src_rel: str, dest_rel: str, project_dir: Path) -> Dict[str, Any]:
    """Execute move using git mv.

    Args:
        src_rel: Relative source path
        dest_rel: Relative destination path
        project_dir: Project directory path

    Returns:
        Dict with move result

    Raises:
        GitCommandError: If git move fails
    """
    logger.info("Attempting git move: %s -> %s", src_rel, dest_rel)
    logger.debug("Moving %s to %s using git mv", src_rel, dest_rel)

    repo = Repo(project_dir, search_parent_directories=False)

    # Convert paths to posix format for git (even on Windows)
    git_src = src_rel.replace("\\", "/")
    git_dest = dest_rel.replace("\\", "/")

    # Execute git mv
    repo.git.mv(git_src, git_dest)

    logger.info("Successfully moved using git: %s -> %s", src_rel, dest_rel)

    return {
        "success": True,
        "method": "git",
        "source": src_rel,
        "destination": dest_rel,
        "message": "File moved using git mv (preserving history)",
    }


def _execute_filesystem_move(
    src_abs: Path, dest_abs: Path, src_rel: str, dest_rel: str, is_fallback: bool
) -> Dict[str, Any]:
    """Execute move using filesystem operations.

    Args:
        src_abs: Absolute source path
        dest_abs: Absolute destination path
        src_rel: Relative source path
        dest_rel: Relative destination path
        is_fallback: Whether this is a fallback from git

    Returns:
        Dict with move result

    Raises:
        PermissionError: If lacking permissions
        Exception: For other move errors
    """
    logger.debug("Moving %s to %s using filesystem operations", src_rel, dest_rel)

    # Use shutil.move for both files and directories
    shutil.move(str(src_abs), str(dest_abs))

    message = "File moved using filesystem operations"
    if is_fallback:
        message += " (fallback from git)"

    logger.info("Successfully moved: %s -> %s", src_rel, dest_rel)

    return {
        "success": True,
        "method": "filesystem",
        "source": src_rel,
        "destination": dest_rel,
        "message": message,
    }


@log_function_call  # Automatic logging of parameters, timing, and exceptions
def move_file_util(source_path: str, destination_path: str, project_dir: Path) -> Dict[str, Any]:
    """
    Move or rename a file or directory.

    Automatically uses git mv if the file is tracked by git,
    otherwise uses standard filesystem operations.
    Always creates parent directories if they don't exist.

    Args:
        source_path: Source file/directory path (relative to project_dir)
        destination_path: Destination path (relative to project_dir)
        project_dir: Project directory path

    Returns:
        Dict containing:
            - success: bool indicating if the move succeeded
            - method: 'git' or 'filesystem' indicating method used
            - source: normalized source path
            - destination: normalized destination path
            - message: optional status message

    Raises:
        FileNotFoundError: If source doesn't exist
        FileExistsError: If destination already exists
        ValueError: If paths are invalid or outside project directory
        PermissionError: If lacking permissions for the operation
    """
    # Validate and normalize paths
    src_abs, src_rel, dest_abs, dest_rel = _validate_move_parameters(source_path, destination_path, project_dir)

    # Automatically create parent directories
    dest_parent = dest_abs.parent
    dest_parent.mkdir(parents=True, exist_ok=True)

    # Determine if git should be used
    should_use_git = _determine_move_method(src_abs, project_dir)

    # Try git move if applicable
    if should_use_git:
        try:
            return _execute_git_move(src_rel, dest_rel, project_dir)
        except (GitCommandError, Exception) as e:
            logger.warning("Git move failed for %s, falling back to filesystem: %s", src_rel, e)
            # Fall through to filesystem move

    # Use filesystem operations (either as primary method or fallback)
    try:
        return _execute_filesystem_move(src_abs, dest_abs, src_rel, dest_rel, is_fallback=should_use_git)
    except PermissionError as e:
        logger.error("Permission denied moving %s to %s: %s", src_rel, dest_rel, e)
        raise
    except Exception as e:
        logger.error("Error moving %s to %s: %s", src_rel, dest_rel, e)
        raise


def is_git_repository(project_dir: Path) -> bool:
    """
    Check if the project directory is a git repository.

    Args:
        project_dir: Path to check for git repository

    Returns:
        True if the directory is a git repository, False otherwise
    """
    logger.debug("Checking if %s is a git repository", project_dir)

    try:
        Repo(project_dir, search_parent_directories=False)
        logger.debug("Detected as git repository: %s", project_dir)
        return True
    except InvalidGitRepositoryError:
        logger.debug("Not a git repository: %s", project_dir)
        return False
    except Exception as e:
        logger.warning("Error checking if directory is git repository: %s", e)
        return False


def is_file_tracked(file_path: Path, project_dir: Path) -> bool:
    """
    Check if a file is tracked by git.

    Args:
        file_path: Path to the file to check
        project_dir: Project directory containing the git repository

    Returns:
        True if the file is tracked by git, False otherwise
    """
    if not is_git_repository(project_dir):
        return False

    try:
        repo = Repo(project_dir, search_parent_directories=False)

        # Get relative path from project directory
        try:
            relative_path = file_path.relative_to(project_dir)
        except ValueError:
            # File is outside project directory
            logger.debug("File %s is outside project directory %s", file_path, project_dir)
            return False

        # Convert to posix path for git (even on Windows)
        git_path = str(relative_path).replace("\\", "/")

        # Use git ls-files to check if file is tracked
        # This returns all files that git knows about (staged or committed)
        try:
            # Use ls-files with the specific file to avoid loading all files
            result = repo.git.ls_files(git_path)
            # If git returns the file path, it's tracked
            return bool(result and git_path in result)
        except GitCommandError:
            # File is not tracked
            return False

    except (InvalidGitRepositoryError, GitCommandError) as e:
        logger.debug("Git error checking if file is tracked: %s", e)
        return False
    except Exception as e:
        logger.warning("Unexpected error checking if file is tracked: %s", e)
        return False


def git_move(source_path: Path, dest_path: Path, project_dir: Path) -> bool:
    """
    Move a file using git mv command.

    Args:
        source_path: Source file path
        dest_path: Destination file path
        project_dir: Project directory containing the git repository

    Returns:
        True if the file was moved successfully using git, False otherwise

    Raises:
        GitCommandError: If git mv command fails
    """
    if not is_git_repository(project_dir):
        return False

    try:
        repo = Repo(project_dir, search_parent_directories=False)

        # Get relative paths from project directory
        try:
            source_relative = source_path.relative_to(project_dir)
            dest_relative = dest_path.relative_to(project_dir)
        except ValueError as e:
            logger.error("Paths must be within project directory: %s", e)
            return False

        # Convert to posix paths for git
        source_git = str(source_relative).replace("\\", "/")
        dest_git = str(dest_relative).replace("\\", "/")

        # Execute git mv command
        logger.info("Executing git mv from %s to %s", source_git, dest_git)
        repo.git.mv(source_git, dest_git)

        logger.info("Successfully moved file using git from %s to %s", source_git, dest_git)
        return True

    except GitCommandError as e:
        logger.error("Git move failed: %s", e)
        raise
    except Exception as e:
        logger.error("Unexpected error during git move: %s", e)
        return False


@log_function_call
def set_project_dir(directory: Path) -> None:
    """Set the project directory for file operations.

    Args:
        directory: The project directory path
    """
    global _project_dir  # pylint: disable=global-statement
    _project_dir = Path(directory)
    logger.info("Project directory set to: %s", _project_dir)
    structured_logger.info("Project directory set", project_dir=str(_project_dir))


@log_function_call
def set_reference_projects(reference_projects: Dict[str, Path]) -> None:
    """Set the reference projects for file operations.

    Args:
        reference_projects: Dictionary mapping project names to directory paths
    """
    global _reference_projects  # pylint: disable=global-statement
    _reference_projects = reference_projects.copy()  # Create a copy to avoid external modifications

    # Log each reference project
    for project_name, project_path in reference_projects.items():
        logger.info("Reference project '%s' set to: %s", project_name, project_path)
        structured_logger.info(
            "Reference project set",
            project_name=project_name,
            project_path=str(project_path),
        )


# ─── Internal helpers (former @tool functions, decorators stripped) ─────────


@log_function_call
def _get_reference_projects() -> Dict[str, Any]:
    """Get available reference project names."""
    try:
        if not _reference_projects:
            logger.info("No reference projects configured")
            return {
                "count": 0,
                "projects": [],
                "usage": "No reference projects available",
            }

        project_names = sorted(_reference_projects.keys())
        logger.info("Found %d reference projects: %s", len(project_names), project_names)

        return {
            "count": len(project_names),
            "projects": project_names,
            "usage": f"Use these {len(project_names)} projects with list_reference_directory() and read_reference_file()",
        }

    except Exception as e:
        logger.error("Error getting reference projects: %s", str(e))
        raise


@log_function_call
def _read_reference_file(reference_name: str, file_path: str) -> str:
    """Read the contents of a file from a reference project."""
    if reference_name not in _reference_projects:
        logger.error("Reference project '%s' not found", reference_name)
        raise ValueError(f"Reference project '{reference_name}' not found")

    ref_path = _reference_projects[reference_name]
    logger.debug(
        "Reading file '%s' from reference project '%s' at path: %s",
        file_path,
        reference_name,
        ref_path,
    )
    return read_file_util(file_path, project_dir=ref_path)


@log_function_call
def _list_reference_directory(reference_name: str) -> List[str]:
    """List files and directories in a reference project directory."""
    if reference_name not in _reference_projects:
        logger.error("Reference project '%s' not found", reference_name)
        raise ValueError(f"Reference project '{reference_name}' not found")

    ref_path = _reference_projects[reference_name]
    logger.debug(
        "Listing files in reference project '%s' at path: %s",
        reference_name,
        ref_path,
    )
    return list_files_util(".", project_dir=ref_path, use_gitignore=True)


@log_function_call
def _list_directory(path: str) -> List[str]:
    """List files and directories in the project directory."""
    try:
        if _project_dir is None:
            raise ValueError("Project directory has not been set")

        logger.info("Listing all files in project directory: %s", _project_dir)
        result = list_files_util(".", project_dir=_project_dir, use_gitignore=True)
        return result
    except Exception as e:
        logger.error("Error listing project directory: %s", str(e))
        raise


@log_function_call
def _read_file(file_path: str, range: Optional[list] = None) -> str:
    """Read the contents of a file, optionally a specific line range."""
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path parameter: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    if _project_dir is None:
        raise ValueError("Project directory has not been set")

    logger.info("Reading file: %s", file_path)
    try:
        content = read_file_util(file_path, project_dir=_project_dir)
        if range and len(range) == 2:
            lines = content.splitlines(keepends=True)
            start = max(0, range[0] - 1)  # 1-based to 0-based
            end = min(len(lines), range[1])
            content = "".join(lines[start:end])
        return content
    except Exception as e:
        logger.error("Error reading file: %s", str(e))
        raise


@log_function_call
def _save_file(file_path: str, content: Any) -> bool:
    """Write content to a file."""
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path parameter: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    if content is None:
        logger.warning("Content is None, treating as empty string")
        content = ""
    elif not isinstance(content, str):
        logger.error("Invalid content type: %s", type(content))
        raise ValueError(f"Content must be a string, got {type(content)}")

    if _project_dir is None:
        raise ValueError("Project directory has not been set")

    logger.info("Writing to file: %s", file_path)
    try:
        success = save_file_util(file_path, content, project_dir=_project_dir)
        return success
    except Exception as e:
        logger.error("Error writing to file: %s", str(e))
        raise


@log_function_call
def _append_file(file_path: str, content: Any) -> bool:
    """Append content to the end of a file."""
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path parameter: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    if content is None:
        logger.warning("Content is None, treating as empty string")
        content = ""
    elif not isinstance(content, str):
        logger.error("Invalid content type: %s", type(content))
        raise ValueError(f"Content must be a string, got {type(content)}")

    if _project_dir is None:
        raise ValueError("Project directory has not been set")

    logger.info("Appending to file: %s", file_path)
    try:
        success = append_file_util(file_path, content, project_dir=_project_dir)
        return success
    except Exception as e:
        logger.error("Error appending to file: %s", str(e))
        raise


@log_function_call
def _delete_this_file(file_path: str) -> bool:
    """Delete a specified file from the filesystem."""
    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path parameter: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    if _project_dir is None:
        raise ValueError("Project directory has not been set")

    logger.info("Deleting file: %s", file_path)
    try:
        success = delete_file_util(file_path, project_dir=_project_dir)
        logger.info("File deleted successfully: %s", file_path)
        return success
    except Exception as e:
        logger.error("Error deleting file %s: %s", file_path, str(e))
        raise


@log_function_call
def _move_file(source_path: str, destination_path: str) -> bool:
    """Move or rename a file or directory within the project."""
    if not source_path or not isinstance(source_path, str):
        raise ValueError("Invalid source path")

    if not destination_path or not isinstance(destination_path, str):
        raise ValueError("Invalid destination path")

    if _project_dir is None:
        raise ValueError("Project directory not configured")

    try:
        result = move_file_util(source_path, destination_path, project_dir=_project_dir)
        return bool(result.get("success", False))
    except FileNotFoundError as exc:
        raise FileNotFoundError("File not found") from exc
    except FileExistsError as exc:
        raise FileExistsError("Destination already exists") from exc
    except PermissionError as exc:
        raise PermissionError("Permission denied") from exc
    except ValueError as e:
        if "Security" in str(e) or "outside" in str(e).lower():
            raise ValueError("Invalid path") from e
        raise ValueError("Invalid operation") from e
    except Exception as e:
        raise RuntimeError("Move operation failed") from e


# ─── Unified file tool ─────────────────────────────────────────────────────


# Extensions recognized as multimodal / document files that should be
# converted via markitdown rather than listed as directories.
_VIEWABLE_EXTENSIONS: set[str] = {
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".ico",
    ".tiff",
    # Documents
    ".pdf",
    ".docx",
    ".doc",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".csv",
    # Archives (markitdown can list contents)
    ".zip",
}


_FILE_ALIASES: dict[str, str] = {
    "open": "view",
    "list": "view",
    "ls": "view",
    "dir": "view",
    "display": "view",
    "show": "view",
    "browse": "view",
    "explore": "view",
    "preview": "view",
    "cat": "read",
    "load": "read",
    "get": "read",
    "fetch": "read",
    "print": "read",
    "save": "write",
    "create": "write",
    "put": "write",
    "store": "write",
    "output": "write",
    "add": "append",
    "extend": "append",
    "concat": "append",
    "modify": "edit",
    "change": "edit",
    "patch": "edit",
    "update": "edit",
    "replace": "edit",
    "fix": "edit",
    "revise": "edit",
    "fetch_url": "download",
    "pull": "download",
    "curl": "download",
    "wget": "download",
    "grab": "download",
    "retrieve": "download",
}


@tool(name="file")
async def file_tool(
    action: Annotated[
        Literal["view", "read", "write", "append", "edit", "download"],
        "The action to perform. Supported values: view, read, write, append, edit, download.",
    ],
    path: Annotated[str, "The absolute path to the target file."],
    text: Annotated[str | None, "The content to be written or appended. Required for write and append actions."] = None,
    edits: Annotated[
        list | None, "A list of edits to be sequentially applied to the file. Required for edit action."
    ] = None,
    range: Annotated[
        list | None,
        "An array of two integers specifying the start and end of the range. Numbers are 1-indexed, and -1 for the end means read to the end of the file. Optional, only used for view and read actions.",
    ] = None,
    url: Annotated[str | None, "Source URL for download operations."] = None,
    overwrite: Annotated[bool, "Allow overwriting existing files on download."] = False,
) -> dict | str | list:
    """Perform operations on files in the sandbox file system.

    <instructions>
    - Prioritize using this tool for file content operations instead of `shell` tool to avoid escaping errors.
    - For file copying, moving, and deletion operations, use `shell` tool to complete them.
    - `view` action is suitable for files that require multimodal understanding, such as images and PDFs.
    - `read` action is suitable for text-based or line-oriented formats, such as Markdown documents and code files.
    - For PDF, Word, and PowerPoint files, freely choose to use `read` to extract text content, or use `view` to visually examine them.
    - After every two `view` actions or browser operations, MUST immediately save key findings to text files to prevent loss of multimodal information in subsequent operations.
    - Under `read` action, the `range` parameter represents line number ranges.
    - Under `view` action, the `range` parameter represents page number ranges, and will be ignored for non-paged formats.
    - If the `range` parameter is not specified, the entire file will be read by default.
    - DO NOT use the `range` parameter when reading a file for the first time; if the content is too long and gets truncated, the result will include range hints.
    - `write` and `append` actions will automatically create files if they do not exist, no need to `write` first then `append`.
    - When writing and appending text, ensure necessary trailing newlines are used to comply with POSIX standards.
    - Code MUST be saved to a file using this tool before execution via `shell` tool to enable debugging and future modifications.
    - DO NOT read files that were just written, as their content remains in context.
    - DO NOT repeatedly read template files or boilerplate code that has already been reviewed once; focus on user-modified or project-specific files.
    - Choose appropriate file extensions based on file content and syntax, e.g., Markdown syntax MUST use `.md` extension.
    - DO NOT write partial or truncated content, always output full content.
    - `edit` can make multiple edits to a single file at once, all edits will be applied sequentially, all must succeed or none are applied.
    - For extensive modifications to shorter files, use `write` to rewrite the entire file instead of using `edit` for modifications.
    </instructions>

    <recommended_usage>
    - Use `view` to view image files.
    - Use `view` with `range` parameter to view specific pages of PDF files.
    - Use `read` to read text files.
    - Use `read` to extract text from Word documents.
    - Use `read` with `range` parameter to read specific parts of log files.
    - Use `read` to re-read files and skills that were offloaded during context compression.
    - Use `write` to create files and record key findings.
    - Use `write` to save code to files before execution via `shell` tool.
    - Use `write` to refactor code files or rewrite short documents.
    - Use `write` to record key information obtained from `view` into text files.
    - Use `append` to write long content in segments.
    - Use `edit` to fix errors in code.
    - Use `edit` to update markers in todo lists.
    </recommended_usage>
    """
    action, _alias = resolve_alias(action, _FILE_ALIASES)

    from .edit import _edit_file
    from .io import _do_download, _do_read_resource

    try:
        if action == "view":
            # If path points to a file with a viewable extension, use markitdown
            # for multimodal conversion (images, PDFs, documents). Otherwise
            # fall back to directory listing.
            resolved = Path(path) if path else None
            if resolved and resolved.is_file() and resolved.suffix.lower() in _VIEWABLE_EXTENSIONS:
                result = await _do_read_resource(uri=path)
                return alias_hint(result, _alias, action)
            return alias_hint(_list_directory(path=path), _alias, action)
        elif action == "read":
            return alias_hint(_read_file(file_path=path, range=range), _alias, action)
        elif action == "write":
            if text is None:
                return error_result(
                    "Missing required parameter: text. Provide the content to write.",
                    hint="Use action='write' with text='your content here'.",
                )
            return alias_hint(_save_file(file_path=path, content=text), _alias, action)
        elif action == "append":
            if text is None:
                return error_result(
                    "Missing required parameter: text. Provide the content to append.",
                    hint="Use action='append' with text='content to add'.",
                )
            return alias_hint(_append_file(file_path=path, content=text), _alias, action)
        elif action == "edit":
            if not edits:
                return error_result(
                    "Missing required parameter: edits. Provide a non-empty list of edit dicts.",
                    hint="Use edits=[{'old_text': 'find this', 'new_text': 'replace with'}].",
                )
            return alias_hint(_edit_file(file_path=path, edits=edits, dry_run=False, options=None), _alias, action)
        elif action == "download":
            if not url:
                return error_result(
                    "Missing required parameter: url. Provide the source URL.",
                    hint="Use action='download' with url='https://example.com/file.zip'.",
                )
            return alias_hint(_do_download(url=url, output_path=path, overwrite=overwrite), _alias, action)
        else:
            return error_result(
                f"Unknown action: {action}", hint="Use one of: view, read, write, append, edit, download"
            )
    except FileNotFoundError as e:
        return error_result(
            str(e),
            hint="The file or directory does not exist. Use action='view' to list files in the project, or action='write' to create a new file.",
        )
    except IsADirectoryError as e:
        return error_result(
            str(e),
            hint="The path points to a directory, not a file. Use action='view' with this path to list its contents instead.",
        )
    except PermissionError as e:
        return error_result(
            str(e),
            hint="Permission denied. The file may be read-only or owned by another user. Check file permissions with the shell tool.",
        )
    except ValueError as e:
        return error_result(
            str(e),
            hint="Invalid parameter. Ensure path is a non-empty string relative to the project directory, and content is a string for write/append actions.",
        )
    except Exception as e:
        stdlogger.exception("file_tool error: %s", e)
        return error_result(
            f"File operation failed: {e}",
            hint="Unexpected error. Verify the project directory is set (use webdev/mobiledev set_project first) and the path is valid.",
        )


# ─── Tool exports ─────────────────────────────
FILE_TOOLS = [file_tool]
