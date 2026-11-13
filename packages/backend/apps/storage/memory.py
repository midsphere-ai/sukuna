"""Custom exception classes for memory and conversation service operations."""


# Custom Exceptions
class MemoryServiceError(Exception):
    """Base exception for storage services errors."""

    pass


class ConversationNotFoundError(MemoryServiceError):
    """Raised when a conversation is not found."""

    pass
