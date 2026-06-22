"""Unit tests for app.services.card_service.

Repositories are replaced with lightweight fakes so these tests run without a
database.  They verify:
- Happy paths produce the expected result.
- Domain exceptions are raised under the correct conditions.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import (
    AccountFrozenError,
    CardNotFoundError,
    UnauthorizedResourceError,
)
from app.models.account import Account, AccountStatus, AccountType
from app.models.card import Card, CardStatus, CardType
from app.services import card_service

# ---------------------------------------------------------------------------
# Helpers — simple in-memory fakes
# ---------------------------------------------------------------------------


def _make_account(
    *,
    user_id: uuid.UUID | None = None,
    status: AccountStatus = AccountStatus.active,
) -> Account:
    account = Account.__new__(Account)
    account.id = uuid.uuid4()
    account.user_id = user_id or uuid.uuid4()
    account.account_number = "MXN123456789012"
    account.currency = "MXN"
    account.balance = Decimal("0.00")
    account.status = status
    account.type = AccountType.checking
    return account


def _make_card(
    *,
    account_id: uuid.UUID | None = None,
    card_type: CardType = CardType.debit,
    status: CardStatus = CardStatus.active,
) -> Card:
    card = Card.__new__(Card)
    card.id = uuid.uuid4()
    card.account_id = account_id or uuid.uuid4()
    card.last4 = "1234"
    card.type = card_type
    card.status = status
    card.expires_at = date.today() + timedelta(days=365 * 3)
    return card


# ---------------------------------------------------------------------------
# create_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_card_success() -> None:
    """create_card returns the new card for an active account owned by the user."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id)
    expected_card = _make_card(account_id=account.id)

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.card_service.AccountRepository.get_by_id",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.card_service.CardRepository.create",
            new=AsyncMock(return_value=expected_card),
        ),
        patch(
            "app.services.card_service.AuditLogRepository.log",
            new=AsyncMock(),
        ),
    ):
        result = await card_service.create_card(
            fake_db,
            account_id=account.id,
            requesting_user_id=user_id,
            card_type=CardType.debit,
        )

    assert result is expected_card


@pytest.mark.asyncio
async def test_create_card_account_frozen() -> None:
    """create_card raises AccountFrozenError when the account is frozen."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id, status=AccountStatus.frozen)

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.card_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=account),
    ):
        with pytest.raises(AccountFrozenError):
            await card_service.create_card(
                fake_db,
                account_id=account.id,
                requesting_user_id=user_id,
                card_type=CardType.debit,
            )


@pytest.mark.asyncio
async def test_create_card_account_closed() -> None:
    """create_card raises AccountFrozenError when the account is closed."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id, status=AccountStatus.closed)

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.card_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=account),
    ):
        with pytest.raises(AccountFrozenError):
            await card_service.create_card(
                fake_db,
                account_id=account.id,
                requesting_user_id=user_id,
                card_type=CardType.debit,
            )


@pytest.mark.asyncio
async def test_create_card_wrong_owner() -> None:
    """create_card raises UnauthorizedResourceError when the account belongs to another user."""
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    account = _make_account(user_id=owner_id)

    fake_db: Any = AsyncMock()

    with patch(
        "app.services.card_service.AccountRepository.get_by_id",
        new=AsyncMock(return_value=account),
    ):
        with pytest.raises(UnauthorizedResourceError):
            await card_service.create_card(
                fake_db,
                account_id=account.id,
                requesting_user_id=other_user_id,
                card_type=CardType.debit,
            )


# ---------------------------------------------------------------------------
# set_card_frozen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_freeze_card_success() -> None:
    """set_card_frozen with frozen=True returns a card with frozen status."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id)
    card = _make_card(account_id=account.id)
    frozen_card = _make_card(account_id=account.id, status=CardStatus.frozen)
    frozen_card.id = card.id

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.card_service.CardRepository.get_by_id",
            new=AsyncMock(return_value=card),
        ),
        patch(
            "app.services.card_service.AccountRepository.get_by_id",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.card_service.CardRepository.update_status",
            new=AsyncMock(return_value=frozen_card),
        ),
        patch(
            "app.services.card_service.AuditLogRepository.log",
            new=AsyncMock(),
        ),
    ):
        result = await card_service.set_card_frozen(
            fake_db,
            card_id=card.id,
            frozen=True,
            requesting_user_id=user_id,
        )

    assert result.status == CardStatus.frozen


@pytest.mark.asyncio
async def test_unfreeze_card_success() -> None:
    """set_card_frozen with frozen=False returns a card with active status."""
    user_id = uuid.uuid4()
    account = _make_account(user_id=user_id)
    card = _make_card(account_id=account.id, status=CardStatus.frozen)
    active_card = _make_card(account_id=account.id, status=CardStatus.active)
    active_card.id = card.id

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.card_service.CardRepository.get_by_id",
            new=AsyncMock(return_value=card),
        ),
        patch(
            "app.services.card_service.AccountRepository.get_by_id",
            new=AsyncMock(return_value=account),
        ),
        patch(
            "app.services.card_service.CardRepository.update_status",
            new=AsyncMock(return_value=active_card),
        ),
        patch(
            "app.services.card_service.AuditLogRepository.log",
            new=AsyncMock(),
        ),
    ):
        result = await card_service.set_card_frozen(
            fake_db,
            card_id=card.id,
            frozen=False,
            requesting_user_id=user_id,
        )

    assert result.status == CardStatus.active


@pytest.mark.asyncio
async def test_freeze_card_not_found() -> None:
    """set_card_frozen raises CardNotFoundError when the card doesn't exist."""
    fake_db: Any = AsyncMock()

    with patch(
        "app.services.card_service.CardRepository.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(CardNotFoundError):
            await card_service.set_card_frozen(
                fake_db,
                card_id=uuid.uuid4(),
                frozen=True,
                requesting_user_id=uuid.uuid4(),
            )


@pytest.mark.asyncio
async def test_freeze_card_wrong_owner() -> None:
    """set_card_frozen raises UnauthorizedResourceError for another user's card."""
    owner_id = uuid.uuid4()
    other_user_id = uuid.uuid4()
    account = _make_account(user_id=owner_id)
    card = _make_card(account_id=account.id)

    fake_db: Any = AsyncMock()

    with (
        patch(
            "app.services.card_service.CardRepository.get_by_id",
            new=AsyncMock(return_value=card),
        ),
        patch(
            "app.services.card_service.AccountRepository.get_by_id",
            new=AsyncMock(return_value=account),
        ),
    ):
        with pytest.raises(UnauthorizedResourceError):
            await card_service.set_card_frozen(
                fake_db,
                card_id=card.id,
                frozen=True,
                requesting_user_id=other_user_id,
            )
