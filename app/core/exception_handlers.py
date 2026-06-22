"""Central exception handlers that translate domain errors to HTTP responses.

Every NexoBank domain exception is mapped here to:
- An HTTP status code.
- A machine-readable ``error_code`` string (SCREAMING_SNAKE_CASE).
- A human-readable ``message``.
- The ``request_id`` from the ``X-Request-ID`` header (or a fresh UUID).

The response body always follows the standard error envelope::

    {
        "error_code": "INSUFFICIENT_FUNDS",
        "message": "The account does not have enough balance to complete the operation.",
        "request_id": "550e8400-e29b-41d4-a716-446655440000"
    }

Register all handlers with a FastAPI application via ``register_exception_handlers(app)``.
"""

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.status import (
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from app.core.exceptions import (
    AccountFrozenError,
    AccountNotFoundError,
    CardFrozenError,
    CardNotFoundError,
    DuplicateTransactionError,
    InsufficientFundsError,
    InvalidCredentialsError,
    NexoBankError,
    UnauthorizedResourceError,
    UnsupportedCurrencyError,
    UserNotFoundError,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Mapping: exception class → (http_status, error_code, default_message)
# ---------------------------------------------------------------------------

_EXCEPTION_MAP: dict[
    type[NexoBankError],
    tuple[int, str, str],
] = {
    InsufficientFundsError: (
        422,
        "INSUFFICIENT_FUNDS",
        "The account does not have enough balance to complete the operation.",
    ),
    AccountNotFoundError: (
        HTTP_404_NOT_FOUND,
        "ACCOUNT_NOT_FOUND",
        "The requested account was not found.",
    ),
    UserNotFoundError: (
        HTTP_404_NOT_FOUND,
        "USER_NOT_FOUND",
        "The requested user was not found.",
    ),
    CardNotFoundError: (
        HTTP_404_NOT_FOUND,
        "CARD_NOT_FOUND",
        "The requested card was not found.",
    ),
    UnauthorizedResourceError: (
        HTTP_403_FORBIDDEN,
        "UNAUTHORIZED_RESOURCE",
        "You do not have permission to access this resource.",
    ),
    DuplicateTransactionError: (
        HTTP_409_CONFLICT,
        "DUPLICATE_TRANSACTION",
        "A transaction with this idempotency key already exists.",
    ),
    InvalidCredentialsError: (
        HTTP_401_UNAUTHORIZED,
        "INVALID_CREDENTIALS",
        "The provided credentials are invalid.",
    ),
    AccountFrozenError: (
        HTTP_422_UNPROCESSABLE_ENTITY,
        "ACCOUNT_FROZEN",
        "This account is frozen and cannot process transactions.",
    ),
    CardFrozenError: (
        HTTP_422_UNPROCESSABLE_ENTITY,
        "CARD_FROZEN",
        "This card is frozen and cannot be used.",
    ),
    UnsupportedCurrencyError: (
        HTTP_422_UNPROCESSABLE_ENTITY,
        "UNSUPPORTED_CURRENCY",
        "The requested currency is not supported.",
    ),
}


# ---------------------------------------------------------------------------
# Helper — extract or generate request ID
# ---------------------------------------------------------------------------


def _get_request_id(request: Request) -> str:
    """Return the ``X-Request-ID`` header value or generate a fresh UUID."""
    return request.headers.get("X-Request-ID") or str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Helper — build the standard JSON error body
# ---------------------------------------------------------------------------


def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    content: dict[str, Any] = {
        "error_code": error_code,
        "message": message,
        "request_id": request_id,
    }
    return JSONResponse(status_code=status_code, content=content)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


async def nexobank_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle any ``NexoBankError`` subclass.

    Looks up the exception type in ``_EXCEPTION_MAP``; if not found (i.e. a
    new exception was added but not mapped) it falls back to 500.
    """
    request_id = _get_request_id(request)
    domain_exc = exc if isinstance(exc, NexoBankError) else NexoBankError(str(exc))

    mapping = _EXCEPTION_MAP.get(type(domain_exc))
    if mapping is None:
        # Unmapped domain error — log with context but keep the message generic
        logger.error(
            "Unmapped NexoBankError",
            extra={
                "exc_type": type(exc).__name__,
                "request_id": request_id,
                "path": request.url.path,
            },
        )
        return _error_response(
            status_code=500,
            error_code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            request_id=request_id,
        )

    http_status, error_code, default_message = mapping
    # Use the exception's own message if it carries one, otherwise fall back to
    # the default so we don't accidentally expose internal details.
    message = domain_exc.message or default_message

    logger.warning(
        "Domain exception raised",
        extra={
            "error_code": error_code,
            "request_id": request_id,
            "path": request.url.path,
            "http_status": http_status,
        },
    )

    return _error_response(
        status_code=http_status,
        error_code=error_code,
        message=message,
        request_id=request_id,
    )


# ---------------------------------------------------------------------------
# Registration helper
# ---------------------------------------------------------------------------


def register_exception_handlers(app: FastAPI) -> None:
    """Register all domain exception handlers on *app*."""
    app.add_exception_handler(NexoBankError, nexobank_exception_handler)
