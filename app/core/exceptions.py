"""Domain-specific exceptions for NexoBank.

All custom exceptions inherit from ``NexoBankError`` so callers can catch the
entire family with a single ``except NexoBankError`` clause, or target a
specific subclass for fine-grained handling.

These exceptions are raised by the *service* layer and translated to HTTP
responses by the central exception handler in ``app.core.exception_handlers``.
No ``HTTPException`` should leak into ``services/`` or ``repositories/``.
"""


class NexoBankError(Exception):
    """Root exception for all NexoBank domain errors."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.message: str = message


# ---------------------------------------------------------------------------
# Account errors
# ---------------------------------------------------------------------------


class AccountNotFoundError(NexoBankError):
    """Raised when a requested account does not exist or is not accessible."""


class AccountFrozenError(NexoBankError):
    """Raised when an operation is attempted on a frozen/suspended account."""


class InsufficientFundsError(NexoBankError):
    """Raised when a debit would take the account balance below the allowed minimum."""


# ---------------------------------------------------------------------------
# User errors
# ---------------------------------------------------------------------------


class UserNotFoundError(NexoBankError):
    """Raised when a requested user does not exist."""


class InvalidCredentialsError(NexoBankError):
    """Raised on failed authentication (wrong password, expired token, etc.)."""


# ---------------------------------------------------------------------------
# Card errors
# ---------------------------------------------------------------------------


class CardNotFoundError(NexoBankError):
    """Raised when a requested card does not exist or is not accessible."""


class CardFrozenError(NexoBankError):
    """Raised when an operation is attempted on a frozen/suspended card."""


# ---------------------------------------------------------------------------
# Resource ownership / authorisation errors
# ---------------------------------------------------------------------------


class UnauthorizedResourceError(NexoBankError):
    """Raised when the authenticated user attempts to access a resource they do not own."""


# ---------------------------------------------------------------------------
# Transaction / idempotency errors
# ---------------------------------------------------------------------------


class DuplicateTransactionError(NexoBankError):
    """Raised when an idempotency key has already been used for a different transaction."""


# ---------------------------------------------------------------------------
# Currency errors
# ---------------------------------------------------------------------------


class UnsupportedCurrencyError(NexoBankError):
    """Raised when an operation is requested in a currency the system does not support."""
