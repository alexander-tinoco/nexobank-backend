"""Pydantic v2 schemas for account-related endpoints.

``AccountCreate`` — validated input for creating a new account.
``AccountResponse`` — serialised output for a single account.
``AccountListResponse`` — paginated list of accounts.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.account import AccountStatus, AccountType

# Currencies the system accepts.  Kept as a module-level constant so other
# modules (e.g. account_service) can import and reuse it.
SUPPORTED_CURRENCIES: frozenset[str] = frozenset({"MXN", "USD"})


class AccountCreate(BaseModel):
    """Input schema for POST /accounts."""

    currency: str
    type: AccountType

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalised = value.upper()
        if normalised not in SUPPORTED_CURRENCIES:
            raise ValueError(
                f"Currency '{value}' is not supported. "
                f"Supported currencies: {sorted(SUPPORTED_CURRENCIES)}"
            )
        return normalised


class AccountResponse(BaseModel):
    """Output schema for a single account."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    account_number: str
    currency: str
    balance: Decimal
    status: AccountStatus
    type: AccountType
    created_at: datetime


class AccountListResponse(BaseModel):
    """Output schema for GET /accounts (list of accounts)."""

    items: list[AccountResponse]
    total: int


class DepositRequest(BaseModel):
    """Input schema for POST /accounts/{id}/deposit."""

    amount: Decimal
    description: str | None = None

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Deposit amount must be greater than zero.")
        return value
