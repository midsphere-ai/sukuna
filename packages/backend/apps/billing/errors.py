"""Custom exception classes for the billing app."""


class InsufficientCreditsError(Exception):
    """Raised when a wallet does not have enough credits for an operation."""

    def __init__(self, needed: int, available: int):
        self.needed = needed
        self.available = available
        super().__init__(f"Insufficient credits: need {needed}, have {available}")


class CreditHoldError(Exception):
    """Raised when a credit hold operation fails."""

    def __init__(self, message: str):
        super().__init__(message)


class OptimisticLockError(Exception):
    """Raised when optimistic locking fails after max retries."""

    def __init__(self):
        super().__init__("Wallet update failed due to concurrent modification")
