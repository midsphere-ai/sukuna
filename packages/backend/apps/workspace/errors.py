"""Custom exception classes for the workspace app."""


class WorkspaceException(Exception):
    """Base exception for Workspace services errors."""

    pass


class UserAlreadyExistsError(WorkspaceException):
    """Raised when attempting to create a user that already exists."""

    pass


class UserDoesNotExistError(WorkspaceException):
    """Raised when a referenced user cannot be found."""

    pass
