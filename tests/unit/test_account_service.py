"""Unit tests for app.services.account_service.

Repositories are replaced with lightweight fakes so these tests run without a
database.  They verify:
- Happy paths produce the expected result.
- Domain exceptions are raised under the correct conditions.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import (
    AccountNotFoundError,
    UnauthorizedResourceError,
    UnsupportedCurrencyError,
)
from app.models.account import Account, AccountStatus, AccountType
from app.services import account_service

# ---------------------------------------------------------------------------
# Helpers — simple in-memory fake Account
# ---------------------------------------------------------------------------


def _make_account(
    *,
    user_id: uuid.UUID | None = None,
    currency: str = "MXN",
    account_type: AccountType = AccountType.checking,
    status: AccountStatus = AccountStatus.active,
) -> Account:
    """Return a minimal Account ORM instance (not backed by a real DB)."""
    return Account(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        account_number=f"{currency}123456789012",
        currency=currency,
        balance=Decimal("0.00"),
        status=status,
        type=account_type,
    )


# ---------------------------------------------------------------------------
# create_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_account_success() -> None:
    """create_account returns the new account on a valid request."""
    user_id = uuid.uuid4()
    expected_account = _make_account(user_id=user_id)

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.account_service.AccountRepository.create",
            new=AsyncMock(return_value=expected_account),
        ),
        patch(
            "app.services.account_service.AuditLogRepository.log",
            new=AsyncMock(),
        ),
    ):
        result = await account_service.create_account(
            fake_db,
            user_id=user_id,
            currency="MXN",
            account_type=AccountType.checking,
        )

    assert result is expected_account


@pytest.mark.asyncio
async def test_create_account_unsupported_currency() -> None:
    """create_account raises UnsupportedCurrencyError for unknown currencies."""
    fake_db: Any = AsyncMock()

    with pytest.raises(UnsupportedCurrencyError):
        await account_service.create_account(
            fake_db,
            user_id=uuid.uuid4(),
            currency="EUR",
            account_type=AccountType.savings,
        )


@pytest.mark.asyncio
async def test_create_account_currency_case_insensitive() -> None:
    """create_account normalises currency to uppercase before validating."""
    user_id = uuid.uuid4()
    expected_account = _make_account(user_id=user_id, currency="USD")

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.account_service.AccountRepository.create",
            new=AsyncMock(return_value=expected_account),
        ),
        patch(
            "app.services.account_service.AuditLogRepository.log",
            new=AsyncMock(),
        ),
    ):
        result = await account_service.create_account(
            fake_db,
            user_id=user_id,
            currency="usd",  # lowercase — should be accepted
            account_type=AccountType.savings,
        )

    assert result is expected_account


# ---------------------------------------------------------------------------
# get_account
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_account_not_found() -> None:
    """get_account raises AccountNotFoundError when the account doesn't exist."""
    fake_db: Any = AsyncMock()

    with patch(
        "app.services.account_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(AccountNotFoundError):
            await account_service.get_account(
                fake_db,
                account_id=uuid.uuid4(),
                requesting_user_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_get_account_wrong_owner() -> None:
    """get_account raises UnauthorizedResourceError for a different user's account."""
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    account = _make_account(user_id=owner_id)

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.account_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=account),
    ):
        with pytest.raises(UnauthorizedResourceError):
            await account_service.get_account(
                fake_db,
                account_id=account.id,
                requesting_user_id=other_user_id,
            )


@pytest.mark.asyncio
async def test_get_account_success() -> None:
    """get_account returns the account when the owner requests it."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id)

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.account_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=account),
    ):
        result = await account_service.get_account(
            fake_db,
            account_id=account.id,
            requesting_user_id=user_id,
        )

    assert result is account


# ---------------------------------------------------------------------------
# get_user_accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_accounts_returns_list() -> None:
    """get_user_accounts delegates to the repository and returns its result."""
    user_id = uuid.uuid4()
    accounts = [_make_account(user_id=user_id) for _ in range(3)]

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.account_service.AccountRepository.get_by_user_id",
        new=AsyncMock(return_value=accounts),
    ):
        result = await account_service.get_user_accounts(fake_db, user_id=user_id)

    assert result == accounts
    assert len(result) == 3
