"""File system tools package — re-exports for backward compatibility."""

from .edit import (
    create_unified_diff,
    edit_file_util,
    normalize_line_endings,
)
from .ops import (
    FILE_TOOLS,
    append_file_util,
    apply_gitignore_filter,
    delete_file_util,
    file_tool,
    filter_with_gitignore,
    git_move,
    is_file_tracked,
    is_git_repository,
    list_files,
    list_files_util,
    log_function_call,
    move_file_util,
    normalize_path,
    read_file_util,
    read_gitignore_rules,
    save_file_util,
    set_project_dir,
    set_reference_projects,
    # Public utility functions
    setup_logging,
    write_file,
)

__all__ = [
    "FILE_TOOLS",
    "file_tool",
    # ops
    "setup_logging",
    "log_function_call",
    "normalize_path",
    "list_files_util",
    "list_files",
    "read_file_util",
    "save_file_util",
    "write_file",
    "append_file_util",
    "delete_file_util",
    "move_file_util",
    "is_git_repository",
    "is_file_tracked",
    "git_move",
    "set_project_dir",
    "set_reference_projects",
    "read_gitignore_rules",
    "apply_gitignore_filter",
    "filter_with_gitignore",
    # edit
    "edit_file_util",
    "normalize_line_endings",
    "create_unified_diff",
]
