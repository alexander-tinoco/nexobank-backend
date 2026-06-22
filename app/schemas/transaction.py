"""Pydantic v2 schemas for the transactions and transfers endpoints.

Validation rules
----------------
- ``amount`` must be > 0, finite, and have at most 2 decimal places.
  Enforcing exactly 2 decimal places at the schema level prevents clients
  from sending amounts that would be silently rounded by the DB.
- ``currency`` must be one of the two supported currencies (MXN, USD).
- ``idempotency_key`` is mandatory on transfers and capped at 64 chars
  to match the DB column length.
- ``next_cursor`` in ``TransactionListResponse`` is an opaque string (base64
  encoded UUID) for cursor-based pagination.  Clients must not interpret it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.transaction import TransactionStatus, TransactionType

# Supported currencies — extend as the product grows
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"MXN", "USD"})


class TransferRequest(BaseModel):
    """Validated payload for ``POST /api/v1/transfers``."""

    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Decimal = Field(..., description="Positive amount with at most 2 decimal places.")
    currency: str = Field(..., description="ISO 4217 currency code (MXN or USD).")
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="Client-generated key; the server returns the same response for repeated calls.",
    )
    description: str | None = Field(default=None, max_length=255)

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Decimal) -> Decimal:
        """Ensure amount is strictly positive and has at most 2 decimal places.

        We inspect the exponent of the Decimal directly — this avoids rounding
        or quantisation side-effects and correctly rejects values like 10.001.
        """
        if v <= Decimal("0"):
            raise ValueError("amount must be greater than zero")

        # sign, digits, exponent = v.as_tuple()
        # exponent < -2 means more than 2 decimal places (e.g. 10.001 → exp=-3)
        sign, digits, exponent = v.as_tuple()
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount must have at most 2 decimal places")

        # Normalise to exactly 2 decimal places for consistent DB storage
        return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, v: str) -> str:
        """Enforce the supported currency list."""
        upper = v.upper()
        if upper not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"currency '{v}' is not supported. Supported: {', '.join(sorted(SUPPORTED_CURRENCIES))}"
            )
        return upper


class TransactionResponse(BaseModel):
    """Read-only view of a single Transaction returned to clients."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_id: uuid.UUID
    counterparty_account_id: uuid.UUID | None
    type: TransactionType
    amount: Decimal
    status: TransactionStatus
    description: str | None
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated list of transactions using cursor-based pagination.

    ``next_cursor`` is an opaque token.  Pass it as the ``cursor`` query
    parameter to retrieve the next page.  When ``has_more`` is ``False``
    there are no more pages.
    """

    items: list[TransactionResponse]
    next_cursor: str | None  # opaque base64-encoded UUID cursor
    has_more: bool
