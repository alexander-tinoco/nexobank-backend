"""Unit tests for transaction_service — all external dependencies are faked.

These tests do NOT use a real database.  Instead, they rely on:
- ``FakeAccount``: an in-memory object that mimics the Account ORM model.
- ``FakeAsyncSession``: a no-op AsyncSession stand-in that records ``flush``
  and ``commit`` calls and stores added objects in a list.
- Monkey-patching of the lazy-imported ``Account`` model and of
  ``TransactionRepository`` methods so the service can run without a DB.

Why unit tests instead of integration tests for this layer?
-----------------------------------------------------------
Unit tests run in milliseconds and can cover many edge cases (frozen accounts,
currency mismatches, idempotency) without spinning up PostgreSQL.  Integration
tests in ``tests/integration/test_transfers.py`` verify the *real* DB behavior.
The concurrency test in ``tests/integration/test_concurrency.py`` verifies the
SELECT FOR UPDATE under actual concurrent load — that cannot be unit-tested.

Patching strategy
-----------------
The service imports ``Account`` and ``AccountStatus`` lazily (inside functions)
to avoid circular imports during parallel-agent development.  The tests patch
the service's internal helpers (``_lock_accounts_for_update``,
``_validate_account_active``, ``_validate_account_owner``) so the tests remain
decoupled from the Account model that another agent is implementing.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import (
    AccountFrozenError,
    AccountNotFoundError,
    InsufficientFundsError,
    UnauthorizedResourceError,
    UnsupportedCurrencyError,
)
from app.models.transaction import Transaction, TransactionStatus, TransactionType


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


def _make_account(
    *,
    account_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    balance: Decimal = Decimal("1000.00"),
    currency: str = "MXN",
    status: str = "active",
) -> MagicMock:
    """Return a MagicMock that behaves like an Account ORM instance."""
    acc = MagicMock()
    acc.id = account_id or uuid.uuid4()
    acc.user_id = user_id or uuid.uuid4()
    acc.balance = balance
    acc.currency = currency
    acc.status = status
    return acc


def _make_transaction(
    *,
    tx_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
    type: TransactionType = TransactionType.transfer_out,
    amount: Decimal = Decimal("500.00"),
    idempotency_key: str = "test-key",
) -> Transaction:
    """Return a Transaction-like MagicMock."""
    tx = MagicMock(spec=Transaction)
    tx.id = tx_id or uuid.uuid4()
    tx.account_id = account_id or uuid.uuid4()
    tx.type = type
    tx.amount = amount
    tx.idempotency_key = idempotency_key
    tx.status = TransactionStatus.completed
    tx.counterparty_account_id = None
    tx.description = None
    return tx


class FakeAsyncSession:
    """Minimal AsyncSession stub — records side effects without touching a DB."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = 0
        self.committed = 0
        self._execute_mock: AsyncMock | None = None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        pass

    async def execute(self, stmt: Any) -> Any:
        if self._execute_mock is not None:
            return await self._execute_mock(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalars.return_value.all.return_value = []
        return result

    async def refresh(self, obj: Any) -> None:  # noqa: ARG002
        pass


def _make_execute_returning(account: MagicMock) -> AsyncMock:
    """Return an AsyncMock for ``db.execute`` that returns *account* via scalar_one_or_none."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = account
    return AsyncMock(return_value=result)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfer_success() -> None:
    """Happy path: 500 transferred from A (balance=1000) to B (balance=0)."""
    user_id = uuid.uuid4()
    account_a = _make_account(user_id=user_id, balance=Decimal("1000.00"))
    account_b = _make_account(balance=Decimal("0.00"))

    tx_out = _make_transaction(
        account_id=account_a.id,
        type=TransactionType.transfer_out,
        amount=Decimal("500.00"),
        idempotency_key="key-001",
    )
    tx_in = _make_transaction(
        account_id=account_b.id,
        type=TransactionType.transfer_in,
        amount=Decimal("500.00"),
        idempotency_key="key-001_in",
    )

    db = FakeAsyncSession()
    db._execute_mock = _make_execute_returning(account_a)

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.transaction_service.TransactionRepository.create",
            new=AsyncMock(side_effect=[tx_out, tx_in]),
        ),
        patch(
            "app.services.transaction_service.AuditLogRepository.log",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "app.services.transaction_service._lock_accounts_for_update",
            new=AsyncMock(return_value=(account_a, account_b)),
        ),
        # _validate_account_active does a lazy import of AccountStatus; patch it
        patch(
            "app.services.transaction_service._validate_account_active",
        ),
        patch(
            "app.services.transaction_service._validate_account_owner",
        ),
    ):
        from app.services import transaction_service

        result_out, result_in = await transaction_service.execute_transfer(
            db,  # type: ignore[arg-type]
            from_account_id=account_a.id,
            to_account_id=account_b.id,
            amount=Decimal("500.00"),
            currency="MXN",
            idempotency_key="key-001",
            requesting_user_id=user_id,
        )

    # Balances mutated correctly
    assert account_a.balance == Decimal("500.00")
    assert account_b.balance == Decimal("500.00")
    assert result_out is tx_out
    assert result_in is tx_in


@pytest.mark.asyncio
async def test_transfer_insufficient_funds() -> None:
    """Transfer of 600 from an account with balance 500 raises InsufficientFundsError."""
    user_id = uuid.uuid4()
    account_a = _make_account(user_id=user_id, balance=Decimal("500.00"))
    account_b = _make_account(balance=Decimal("0.00"))

    db = FakeAsyncSession()
    db._execute_mock = _make_execute_returning(account_a)

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.transaction_service._lock_accounts_for_update",
            new=AsyncMock(return_value=(account_a, account_b)),
        ),
        patch("app.services.transaction_service._validate_account_active"),
        patch("app.services.transaction_service._validate_account_owner"),
    ):
        from app.services import transaction_service

        with pytest.raises(InsufficientFundsError):
            await transaction_service.execute_transfer(
                db,  # type: ignore[arg-type]
                from_account_id=account_a.id,
                to_account_id=account_b.id,
                amount=Decimal("600.00"),
                currency="MXN",
                idempotency_key="key-002",
                requesting_user_id=user_id,
            )


@pytest.mark.asyncio
async def test_transfer_account_frozen() -> None:
    """Transfer from a frozen account raises AccountFrozenError."""
    user_id = uuid.uuid4()
    account_a = _make_account(user_id=user_id, balance=Decimal("1000.00"), status="frozen")
    account_b = _make_account(balance=Decimal("0.00"))

    db = FakeAsyncSession()
    db._execute_mock = _make_execute_returning(account_a)

    def raise_frozen(account: Any, label: str) -> None:  # noqa: ARG001
        if account.status != "active":
            raise AccountFrozenError(f"Account '{label}' is frozen.")

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.transaction_service._lock_accounts_for_update",
            new=AsyncMock(return_value=(account_a, account_b)),
        ),
        patch(
            "app.services.transaction_service._validate_account_active",
            side_effect=raise_frozen,
        ),
        patch("app.services.transaction_service._validate_account_owner"),
    ):
        from app.services import transaction_service

        with pytest.raises(AccountFrozenError):
            await transaction_service.execute_transfer(
                db,  # type: ignore[arg-type]
                from_account_id=account_a.id,
                to_account_id=account_b.id,
                amount=Decimal("500.00"),
                currency="MXN",
                idempotency_key="key-003",
                requesting_user_id=user_id,
            )


@pytest.mark.asyncio
async def test_transfer_same_account() -> None:
    """Transferring to the same account raises AccountNotFoundError with a clear message."""
    user_id = uuid.uuid4()
    account_id = uuid.uuid4()

    db = FakeAsyncSession()

    with patch(
        "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
        new=AsyncMock(return_value=None),
    ):
        from app.services import transaction_service

        with pytest.raises(AccountNotFoundError, match="different"):
            await transaction_service.execute_transfer(
                db,  # type: ignore[arg-type]
                from_account_id=account_id,
                to_account_id=account_id,
                amount=Decimal("100.00"),
                currency="MXN",
                idempotency_key="key-004",
                requesting_user_id=user_id,
            )


@pytest.mark.asyncio
async def test_transfer_idempotency_key_reuse() -> None:
    """Reusing an idempotency key returns the original transactions without side effects."""
    user_id = uuid.uuid4()
    account_a_id = uuid.uuid4()
    account_b_id = uuid.uuid4()

    existing_tx_out = _make_transaction(
        account_id=account_a_id,
        type=TransactionType.transfer_out,
        idempotency_key="key-reuse",
    )
    existing_tx_in = _make_transaction(
        account_id=account_b_id,
        type=TransactionType.transfer_in,
        idempotency_key="key-reuse_in",
    )

    db = FakeAsyncSession()
    lock_mock = AsyncMock()

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(side_effect=[existing_tx_out, existing_tx_in]),
        ),
        patch(
            "app.services.transaction_service._lock_accounts_for_update",
            new=lock_mock,
        ),
    ):
        from app.services import transaction_service

        result_out, result_in = await transaction_service.execute_transfer(
            db,  # type: ignore[arg-type]
            from_account_id=account_a_id,
            to_account_id=account_b_id,
            amount=Decimal("500.00"),
            currency="MXN",
            idempotency_key="key-reuse",
            requesting_user_id=user_id,
        )

    # No locks acquired, no new rows created
    lock_mock.assert_not_called()
    assert result_out is existing_tx_out
    assert result_in is existing_tx_in


@pytest.mark.asyncio
async def test_transfer_currency_mismatch() -> None:
    """Transfer with mismatched currency raises UnsupportedCurrencyError."""
    user_id = uuid.uuid4()
    # Both accounts are in MXN, but transfer requests USD
    account_a = _make_account(user_id=user_id, balance=Decimal("1000.00"), currency="MXN")
    account_b = _make_account(balance=Decimal("0.00"), currency="MXN")

    db = FakeAsyncSession()
    db._execute_mock = _make_execute_returning(account_a)

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.transaction_service._lock_accounts_for_update",
            new=AsyncMock(return_value=(account_a, account_b)),
        ),
        patch("app.services.transaction_service._validate_account_active"),
        patch("app.services.transaction_service._validate_account_owner"),
    ):
        from app.services import transaction_service

        with pytest.raises(UnsupportedCurrencyError):
            await transaction_service.execute_transfer(
                db,  # type: ignore[arg-type]
                from_account_id=account_a.id,
                to_account_id=account_b.id,
                amount=Decimal("100.00"),
                currency="USD",  # accounts are MXN → mismatch
                idempotency_key="key-005",
                requesting_user_id=user_id,
            )


@pytest.mark.asyncio
async def test_transfer_unauthorized_account() -> None:
    """Transfer from an account owned by another user raises UnauthorizedResourceError."""
    requester_id = uuid.uuid4()
    owner_id = uuid.uuid4()  # different user
    account_a = _make_account(user_id=owner_id, balance=Decimal("1000.00"))
    account_b = _make_account(balance=Decimal("0.00"))

    db = FakeAsyncSession()
    db._execute_mock = _make_execute_returning(account_a)

    def raise_unauthorized(account: Any, user_id: Any) -> None:
        if account.user_id != user_id:
            raise UnauthorizedResourceError("Not your account.")

    with (
        patch(
            "app.services.transaction_service.TransactionRepository.get_by_idempotency_key",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.services.transaction_service._validate_account_owner",
            side_effect=raise_unauthorized,
        ),
    ):
        from app.services import transaction_service

        with pytest.raises(UnauthorizedResourceError):
            await transaction_service.execute_transfer(
                db,  # type: ignore[arg-type]
                from_account_id=account_a.id,
                to_account_id=account_b.id,
                amount=Decimal("100.00"),
                currency="MXN",
                idempotency_key="key-006",
                requesting_user_id=requester_id,  # not the owner
            )
