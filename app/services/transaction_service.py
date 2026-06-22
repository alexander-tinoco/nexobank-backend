"""Transaction service — business logic for transfers and transaction queries.

Concurrency safety
------------------
All balance mutations go through ``_lock_accounts_for_update``, which issues
a ``SELECT ... FOR UPDATE`` on both account rows inside the active database
transaction.  The two accounts are always locked in ascending UUID order to
prevent circular deadlocks when two concurrent transfers touch the same pair
of accounts in opposite directions.

Example: concurrent T1 (A→B) and T2 (B→A) both sort [A, B] the same way,
so T1 and T2 acquire the lock on A first and then on B — they serialize
naturally instead of deadlocking.

Idempotency
-----------
When a ``transfer`` call arrives with an already-used ``idempotency_key``,
the service looks up the original ``transfer_out`` row and its companion
``transfer_in`` (stored with ``<key>_in`` suffix) and returns them without
applying any side effects.  This lets clients safely retry on network errors.

AuditLog
--------
Every successful transfer writes an ``AuditLog`` entry with action
``TRANSFER_COMPLETED``.  The log is written inside the same DB transaction,
so if the commit fails the audit row is also rolled back — no phantom audits.

Domain exceptions (never HTTPException)
----------------------------------------
All error conditions raise exceptions from ``app.core.exceptions``.
The central handler in ``app.core.exception_handlers`` translates them to
the correct HTTP status code.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.account import Account

from app.core.exceptions import (
    AccountFrozenError,
    AccountNotFoundError,
    InsufficientFundsError,
    UnauthorizedResourceError,
    UnsupportedCurrencyError,
)
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.transaction_repository import TransactionRepository
from app.schemas.transaction import SUPPORTED_CURRENCIES

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _lock_accounts_for_update(
    db: AsyncSession,
    id1: uuid.UUID,
    id2: uuid.UUID,
) -> tuple[Account, Account]:
    """Lock both account rows with SELECT … FOR UPDATE in a deterministic order.

    Acquiring locks in ascending UUID order eliminates the classic A→B / B→A
    circular-wait deadlock when two concurrent transfers touch the same pair
    of accounts.

    The ``Account`` model is imported lazily to decouple this module from the
    accounts module during the parallel-agent development phase (Phase 2).
    At integration time (Phase 3), ``app.models.account`` is available.

    Returns
    -------
    (account_for_id1, account_for_id2)
        The two locked Account instances in the order the caller passed them.
    """
    from app.models.account import Account  # noqa: PLC0415

    # Canonical lock order: always smaller UUID first to prevent deadlocks
    first_id, second_id = sorted([id1, id2])

    stmt = (
        select(Account)
        .where(Account.id.in_([first_id, second_id]))
        .with_for_update()
        .order_by(Account.id)
    )
    result = await db.execute(stmt)
    accounts = list(result.scalars().all())

    if len(accounts) != 2:
        raise AccountNotFoundError("One or both accounts were not found.")

    by_id: dict[uuid.UUID, Account] = {a.id: a for a in accounts}
    return by_id[id1], by_id[id2]


def _validate_account_active(account: Account, label: str) -> None:
    """Raise AccountFrozenError if *account*.status is not 'active'."""
    from app.models.account import AccountStatus  # noqa: PLC0415

    if account.status != AccountStatus.active:
        raise AccountFrozenError(f"Account '{label}' is frozen and cannot process transactions.")


def _validate_account_owner(account: Account, user_id: uuid.UUID) -> None:
    """Raise UnauthorizedResourceError if *account* is not owned by *user_id*."""
    if account.user_id != user_id:
        raise UnauthorizedResourceError(
            "You are not authorized to transfer funds from this account."
        )


# ---------------------------------------------------------------------------
# Public service functions
# ---------------------------------------------------------------------------


async def execute_transfer(
    db: AsyncSession,
    *,
    from_account_id: uuid.UUID,
    to_account_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    idempotency_key: str,
    requesting_user_id: uuid.UUID,
    description: str | None = None,
    ip_address: str | None = None,
) -> tuple[Transaction, Transaction]:
    """Transfer *amount* from one account to another atomically.

    All reads and writes happen inside the caller-supplied ``db`` session.
    The caller is responsible for committing (or rolling back) the session.

    Parameters
    ----------
    db:
        Active ``AsyncSession`` with an open transaction.
    from_account_id:
        UUID of the account to debit.
    to_account_id:
        UUID of the account to credit.
    amount:
        Positive ``Decimal`` with at most 2 decimal places.
    currency:
        ISO 4217 code; must match both accounts' currency.
    idempotency_key:
        Client-generated key (max 64 chars).  Duplicate calls return the
        existing transactions without re-applying any side effects.
    requesting_user_id:
        Must be the owner of ``from_account``.
    description:
        Optional free-text memo stored on both transaction rows.
    ip_address:
        Remote IP for the audit log entry.

    Returns
    -------
    (tx_out, tx_in)
        The ``transfer_out`` Transaction (debit on source) and the
        ``transfer_in`` Transaction (credit on destination).
    """
    # ------------------------------------------------------------------
    # Step 1 — idempotency check (fast path, no locks needed)
    # ------------------------------------------------------------------
    existing_tx_out = await TransactionRepository.get_by_idempotency_key(
        db, idempotency_key
    )
    if existing_tx_out is not None:
        # Also retrieve the companion transfer_in row
        existing_tx_in = await TransactionRepository.get_by_idempotency_key(
            db, idempotency_key + "_in"
        )
        if existing_tx_in is not None:
            return existing_tx_out, existing_tx_in
        # Edge case: tx_out exists but tx_in is missing (interrupted write).
        # Surface this so it can be investigated rather than silently retrying.
        raise AccountNotFoundError(
            "Partial transfer detected: transfer_out exists but transfer_in is missing."
        )

    # ------------------------------------------------------------------
    # Step 2 — validate inputs
    # ------------------------------------------------------------------
    if amount <= Decimal("0"):
        raise InsufficientFundsError("Transfer amount must be greater than zero.")

    currency_upper = currency.upper()
    if currency_upper not in SUPPORTED_CURRENCIES:
        raise UnsupportedCurrencyError(
            f"Currency '{currency}' is not supported. Supported: "
            + ", ".join(sorted(SUPPORTED_CURRENCIES))
        )

    if from_account_id == to_account_id:
        raise AccountNotFoundError("Source and destination accounts must be different.")

    # ------------------------------------------------------------------
    # Step 3 — ownership check (before locking to fail fast cheaply)
    # ------------------------------------------------------------------
    from app.models.account import Account  # noqa: PLC0415

    owner_result = await db.execute(
        select(Account).where(Account.id == from_account_id)
    )
    from_account_check = owner_result.scalar_one_or_none()
    if from_account_check is None:
        raise AccountNotFoundError(f"Source account '{from_account_id}' not found.")

    _validate_account_owner(from_account_check, requesting_user_id)

    # ------------------------------------------------------------------
    # Step 4 — lock both rows for UPDATE (deadlock-safe ordering)
    # ------------------------------------------------------------------
    from_account, to_account = await _lock_accounts_for_update(
        db, from_account_id, to_account_id
    )

    # ------------------------------------------------------------------
    # Step 5 — business rule validations (after lock, on fresh data)
    # ------------------------------------------------------------------
    _validate_account_active(from_account, "source")
    _validate_account_active(to_account, "destination")

    if from_account.currency != currency_upper:
        raise UnsupportedCurrencyError(
            f"Source account currency is '{from_account.currency}', "
            f"but transfer requested in '{currency_upper}'."
        )

    if to_account.currency != currency_upper:
        raise UnsupportedCurrencyError(
            f"Destination account currency is '{to_account.currency}', "
            f"but transfer requested in '{currency_upper}'."
        )

    if from_account.balance < amount:
        raise InsufficientFundsError(
            f"Insufficient funds: balance is {from_account.balance}, "
            f"attempted to transfer {amount}."
        )

    # ------------------------------------------------------------------
    # Step 6 — apply balance mutations
    # ------------------------------------------------------------------
    from_account.balance -= amount
    to_account.balance += amount

    # Flush the balance updates so the DB sees them before the transaction rows
    await db.flush()

    # ------------------------------------------------------------------
    # Step 7 — create transaction records
    # ------------------------------------------------------------------
    tx_out = await TransactionRepository.create(
        db,
        account_id=from_account_id,
        type=TransactionType.transfer_out,
        amount=amount,
        status=TransactionStatus.completed,
        counterparty_account_id=to_account_id,
        idempotency_key=idempotency_key,
        description=description,
    )

    tx_in = await TransactionRepository.create(
        db,
        account_id=to_account_id,
        type=TransactionType.transfer_in,
        amount=amount,
        status=TransactionStatus.completed,
        counterparty_account_id=from_account_id,
        idempotency_key=idempotency_key + "_in",
        description=description,
    )

    # ------------------------------------------------------------------
    # Step 8 — audit log (inside the same transaction)
    # ------------------------------------------------------------------
    await AuditLogRepository.log(
        db,
        action="TRANSFER_COMPLETED",
        user_id=requesting_user_id,
        entity_type="transaction",
        entity_id=tx_out.id,
        ip_address=ip_address,
        metadata={
            "amount": str(amount),
            "currency": currency_upper,
            "from_account": str(from_account_id),
            "to_account": str(to_account_id),
            "tx_out_id": str(tx_out.id),
            "tx_in_id": str(tx_in.id),
        },
    )

    return tx_out, tx_in


async def get_account_transactions(
    db: AsyncSession,
    *,
    account_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[Transaction], str | None]:
    """Return a paginated list of transactions for a given account.

    Raises
    ------
    UnauthorizedResourceError
        If ``requesting_user_id`` does not own ``account_id``.
    AccountNotFoundError
        If ``account_id`` does not exist.

    Returns
    -------
    (items, next_cursor)
        ``next_cursor`` is ``None`` when there are no more pages.
    """
    from app.models.account import Account  # noqa: PLC0415

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        raise AccountNotFoundError(f"Account '{account_id}' not found.")

    if account.user_id != requesting_user_id:
        raise UnauthorizedResourceError(
            "You are not authorized to view transactions for this account."
        )

    return await TransactionRepository.get_by_account_id_paginated(
        db,
        account_id,
        limit=limit,
        cursor=cursor,
    )
