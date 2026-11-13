"""File edit operations — edit_file_util and all supporting helpers."""

__version__ = "0.1.0"

import difflib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ops import log_function_call, normalize_path

# ─── Logger Initialization ─────────────────────
logger = logging.getLogger(__name__)


def edit_file_util(
    file_path: str,
    edits: List[Dict[str, str]],
    dry_run: bool = False,
    options: Optional[Dict[str, bool]] = None,
    project_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Make selective edits to a file with simplified, reliable processing.

    This simplified version focuses on reliability over advanced features:
    - Exact string matching only (no fuzzy matching)
    - Basic indentation preservation (preserve exactly as provided)
    - Clear error reporting
    - Single pass editing

    Args:
        file_path: Path to file (relative to project_dir if provided)
        edits: List of {'old_text': str, 'new_text': str} operations
        dry_run: If True, return diff without writing changes
        options: Optional settings (preserve_indentation: bool, default False)
        project_dir: Base directory for relative paths

    Returns:
        {
            'success': bool,
            'diff': str,  # unified diff or empty if no changes
            'message': str,  # human readable status (optional)
            'match_results': List[Dict],  # for compatibility
            'file_path': str,
            'dry_run': bool
        }
    """

    # Input validation
    if not file_path or not isinstance(file_path, str):
        return _error_result_edit(f"Invalid file_path: {file_path}")

    if not isinstance(edits, list) or not edits:
        return _error_result_edit("edits must be a non-empty list")

    # Resolve file path
    if project_dir:
        abs_path, _ = normalize_path(file_path, project_dir)
        file_path = str(abs_path)
    else:
        abs_path = Path(file_path)

    if not abs_path.exists():
        raise FileNotFoundError(f"File not found: {abs_path}")

    if not abs_path.is_file():
        raise ValueError(f"Not a file: {abs_path}")

    # Read file content
    try:
        with open(abs_path, "r", encoding="utf-8") as f:
            original_content = f.read()
    except UnicodeDecodeError:
        return _error_result_edit(f"File contains invalid UTF-8: {abs_path}", file_path)
    except Exception as e:
        return _error_result_edit(f"Cannot read file: {e}", file_path)

    # Validate edit operations
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            return _error_result_edit(f"Edit {i} must be a dict, got {type(edit)}", file_path)  # type: ignore[unreachable]

        # Check existence of required keys
        if "old_text" not in edit or "new_text" not in edit:
            return _error_result_edit(f"Edit {i} missing required keys 'old_text' or 'new_text'", file_path)

        # Check types of values
        if not isinstance(edit["old_text"], str) or not isinstance(edit["new_text"], str):
            return _error_result_edit(f"Edit {i} values must be strings", file_path)  # type: ignore[unreachable]

    # Extract options
    preserve_indentation = False  # Default to False for safety
    if options and "preserve_indentation" in options:
        preserve_indentation = options["preserve_indentation"]

    # Apply edits sequentially
    current_content = original_content
    match_results = []
    edits_applied = 0
    edits_failed = 0

    for i, edit in enumerate(edits):
        old_text = edit["old_text"]
        new_text = edit["new_text"]

        # Skip if no change needed
        if old_text == new_text:
            match_results.append(
                {
                    "edit_index": i,
                    "match_type": "skipped",
                    "details": "No change needed - text already matches desired state",
                }
            )
            continue

        # Check if old_text exists in current content
        if old_text in current_content:
            # Apply indentation preservation if requested
            final_new_text = new_text
            indentation_info = None
            if preserve_indentation:
                final_new_text, indentation_message = _preserve_basic_indentation(old_text, new_text)
                if indentation_message:
                    logger.info("Edit %s: %s", i, indentation_message)
                    indentation_info = indentation_message

            # Apply replacement (only first occurrence)
            old_text_position = current_content.find(old_text)
            line_index = current_content[:old_text_position].count("\n")
            current_content = current_content.replace(old_text, final_new_text, 1)
            match_result = {
                "edit_index": i,
                "match_type": "exact",
                "line_index": line_index,
                "line_count": old_text.count("\n") + 1,
            }
            if indentation_info:
                match_result["indentation_applied"] = indentation_info

            match_results.append(match_result)
            edits_applied += 1
        else:
            # Check if edit is already applied using contextual verification
            if preserve_indentation:
                # Need to check both the original new_text and the indentation-preserved version
                final_new_text, _ = _preserve_basic_indentation(old_text, new_text)
                edit_already_applied = _is_edit_already_applied(
                    current_content, old_text, final_new_text
                ) or _is_edit_already_applied(current_content, old_text, new_text)
            else:
                edit_already_applied = _is_edit_already_applied(current_content, old_text, new_text)

            if edit_already_applied:
                match_results.append(
                    {
                        "edit_index": i,
                        "match_type": "skipped",
                        "details": "Edit already applied - content already in desired state",
                    }
                )
            else:
                match_results.append(
                    {
                        "edit_index": i,
                        "match_type": "failed",
                        "details": f"Text not found: {_truncate(old_text)}",
                    }
                )
                edits_failed += 1

    # Determine success - success if no edits failed (even if no changes made due to already applied)
    success = edits_failed == 0
    changes_made = current_content != original_content

    # Generate diff
    diff = ""
    if changes_made:
        diff = _create_diff(original_content, current_content, str(abs_path))

    # Create result message
    message = None
    if edits_failed > 0:
        message = f"Failed to find exact match for {edits_failed} edit(s)"
    elif not changes_made:
        message = "No changes needed - content already in desired state"

    # Write changes if not dry run
    if not dry_run and changes_made and success:
        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(current_content)
        except Exception as e:
            return _error_result_edit(f"Cannot write file: {e}", file_path)

    result = {
        "success": success,
        "diff": diff,
        "match_results": match_results,
        "file_path": file_path,
        "dry_run": dry_run,
    }

    if message:
        result["message"] = message

    # Add error field when there are failures for test compatibility
    if not success and edits_failed > 0:
        result["error"] = f"Failed to find exact match for {edits_failed} edit(s)"

    return result


def _error_result_edit(error_msg: str, file_path: str = "") -> Dict[str, Any]:
    """Helper to create error result in expected format for edit operations."""
    logger.error(error_msg)
    return {
        "success": False,
        "error": error_msg,
        "diff": "",
        "match_results": [{"edit_index": 0, "match_type": "failed", "details": error_msg}],
        "file_path": file_path,
        "dry_run": False,
    }


# Keep backward compat alias
_error_result = _error_result_edit


def _truncate(text: str, max_len: int = 50) -> str:
    """Truncate text for error messages"""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _create_diff(original: str, modified: str, filename: str) -> str:
    """Create unified diff between original and modified content"""
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    return "".join(
        difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            lineterm="",
        )
    )


def _is_edit_already_applied(content: str, old_text: str, new_text: str) -> bool:
    """
    Check if an edit has already been applied by verifying contextual conditions.

    Returns True if:
    1. old_text is NOT found in content AND
    2. new_text IS found in content

    This prevents false positives where new_text appears elsewhere in the file.
    """
    old_text_exists = old_text in content
    new_text_exists = new_text in content

    # Edit is considered already applied only if:
    # - The old text is no longer present, AND
    # - The new text is present
    return not old_text_exists and new_text_exists


def _preserve_basic_indentation(old_text: str, new_text: str) -> tuple[str, str]:
    """
    Simple and safe indentation preservation with detailed feedback.

    Only applies indentation if new_text appears to be unindented (starts at column 0)
    and old_text has indentation. Otherwise returns new_text unchanged.

    This prevents the common problem of double-indentation.

    Returns:
        tuple: (processed_text, status_message)
    """
    old_lines = old_text.split("\n")
    new_lines = new_text.split("\n")

    if not old_lines or not new_lines:
        return new_text, "No indentation processing needed (empty content)"

    # Get indentation from first line of old_text
    first_old_line = old_lines[0]
    old_indent = ""
    for char in first_old_line:
        if char in " \t":
            old_indent += char
        else:
            break

    # Get indentation from first line of new_text
    first_new_line = new_lines[0]
    new_indent = ""
    for char in first_new_line:
        if char in " \t":
            new_indent += char
        else:
            break

    # Only apply indentation if:
    # 1. old_text has indentation
    # 2. new_text has no indentation (starts at column 0)
    if old_indent and not new_indent:
        # Apply the old indentation to all non-empty lines
        enhanced_lines = []
        for line in new_lines:
            if line.strip():  # Non-empty line
                enhanced_lines.append(old_indent + line)
            else:
                enhanced_lines.append("")
        result = "\n".join(enhanced_lines)
        message = f"Applied indentation ({len(old_indent)} spaces) to unindented replacement text"
        return result, message

    if old_indent and new_indent:
        message = f"Preserved existing indentation (old: {len(old_indent)}, new: {len(new_indent)} spaces)"
        return new_text, message

    if not old_indent and new_indent:
        message = f"Kept new text indentation ({len(new_indent)} spaces, old had none)"
        return new_text, message

    # Neither has indentation
    return new_text, "No indentation processing needed (neither text is indented)"


# Legacy compatibility functions (simplified versions)
def normalize_line_endings(text: str) -> str:
    """Convert all line endings to Unix style (\n)."""
    return text.replace("\r\n", "\n")


def create_unified_diff(original: str, modified: str, file_path: str) -> str:
    """Create a unified diff between original and modified content."""
    return _create_diff(original, modified, file_path)


@log_function_call
def _edit_file(
    file_path: str,
    edits: List[Dict[str, str]],
    dry_run: bool = False,
    options: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    """Make selective edits to files using exact string matching."""
    from .ops import _project_dir

    if not file_path or not isinstance(file_path, str):
        logger.error("Invalid file path parameter: %s", file_path)
        raise ValueError(f"File path must be a non-empty string, got {type(file_path)}")

    if not isinstance(edits, list) or not edits:
        logger.error("Invalid edits parameter: %s", edits)
        raise ValueError("Edits must be a non-empty list")

    if _project_dir is None:
        raise ValueError("Project directory has not been set")

    # Normalize edit operations
    normalized_edits = []
    for i, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise ValueError(f"Edit #{i} must be a dictionary, got {type(edit)}")

        if "old_text" not in edit or "new_text" not in edit:
            missing = ", ".join([f for f in ["old_text", "new_text"] if f not in edit])
            raise ValueError(f"Edit #{i} is missing required field(s): {missing}")

        normalized_edits.append({"old_text": edit["old_text"], "new_text": edit["new_text"]})

    # Process options
    normalized_options = {}
    supported_options = {"preserve_indentation"}

    if options:
        for opt_name, opt_value in options.items():
            if opt_name in supported_options:
                normalized_options[opt_name] = opt_value
            else:
                logger.warning(
                    "Unsupported option '%s' ignored. Supported options: %s",
                    opt_name,
                    supported_options,
                )

    logger.info("Editing file: %s, dry_run: %s", file_path, dry_run)

    try:
        return edit_file_util(
            file_path,
            normalized_edits,
            dry_run=dry_run,
            options=normalized_options,
            project_dir=_project_dir,
        )
    except (FileNotFoundError, ValueError, IsADirectoryError):
        raise  # Let file_tool's catch-all handle these known types
    except Exception as e:
        logger.error("Error editing file %s: %s", file_path, str(e))
        raise
