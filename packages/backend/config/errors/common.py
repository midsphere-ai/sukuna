"""Common domain exception types used across the Sukuna platform.

These exceptions are caught by the centralised error handlers in
``config.errors.handlers`` and translated to appropriate HTTP responses.
"""


class UnauthorizedAccessError(Exception):
    """Raised when user lacks permission for the requested operation."""

    pass


class InvalidInputError(Exception):
    """Raised when input validation fails."""

    pass


class FileProcessingError(Exception):
    """Raised when file processing fails."""

    pass


class NotFoundError(Exception):
    """Raised when something is not found."""

    pass
