"""Transaction repository — read/create access to the transactions table.

Architecture rules
------------------
- No ``update`` or ``delete`` methods exist here (CLAUDE.md rule 2).
  The ledger is append-only; corrections are new reversal rows.
- Cursor-based pagination is implemented via ``(created_at DESC, id DESC)``
  ordering with the cursor encoded as a base64 string of the last seen id.
  This avoids the ``OFFSET`` performance cliff on large tables.
- All write methods accept keyword-only arguments to prevent positional
  argument mistakes when the call site evolves.
"""

from __future__ import annotations

import base64
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transaction import Transaction, TransactionStatus, TransactionType


def _encode_cursor(transaction_id: uuid.UUID) -> str:
    """Encode a transaction UUID into an opaque cursor string."""
    return base64.urlsafe_b64encode(str(transaction_id).encode()).decode()


def _decode_cursor(cursor: str) -> uuid.UUID | None:
    """Decode an opaque cursor string back to a UUID.

    Returns ``None`` if the cursor is malformed so the caller can treat it
    as a missing cursor (start from the beginning).
    """
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
        return uuid.UUID(decoded)
    except Exception:
        return None


class TransactionRepository:
    """Data-access layer for Transaction records."""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        type: TransactionType,
        amount: Decimal,
        status: TransactionStatus = TransactionStatus.completed,
        counterparty_account_id: uuid.UUID | None = None,
        idempotency_key: str | None = None,
        reference_transaction_id: uuid.UUID | None = None,
        description: str | None = None,
    ) -> Transaction:
        """Insert a new Transaction row and flush to obtain the server-assigned id.

        ``flush()`` is used instead of ``commit()`` so the caller controls the
        transaction boundary — callers that create two rows (transfer_out +
        transfer_in) must commit after both rows are flushed.
        """
        tx = Transaction(
            account_id=account_id,
            type=type,
            amount=amount,
            status=status,
            counterparty_account_id=counterparty_account_id,
            idempotency_key=idempotency_key,
            reference_transaction_id=reference_transaction_id,
            description=description,
        )
        db.add(tx)
        await db.flush()
        await db.refresh(tx)
        return tx

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        transaction_id: uuid.UUID,
    ) -> Transaction | None:
        """Return the Transaction with the given id, or ``None`` if not found."""
        result = await db.execute(
            select(Transaction).where(Transaction.id == transaction_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_idempotency_key(
        db: AsyncSession,
        key: str,
    ) -> Transaction | None:
        """Return the Transaction whose idempotency_key matches ``key``.

        Used to detect duplicate calls before applying any side effects.
        """
        result = await db.execute(
            select(Transaction).where(Transaction.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_account_id_paginated(
        db: AsyncSession,
        account_id: uuid.UUID,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[Transaction], str | None]:
        """Return a page of transactions for *account_id* using cursor pagination.

        Ordering is ``(created_at DESC, id DESC)`` so the newest transactions
        appear first.  The cursor encodes the ``id`` of the last row returned
        on the previous page.

        Returns
        -------
        (items, next_cursor)
            ``next_cursor`` is ``None`` when there are no more pages.
        """
        stmt = (
            select(Transaction)
            .where(Transaction.account_id == account_id)
            .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        )

        if cursor is not None:
            cursor_id = _decode_cursor(cursor)
            if cursor_id is not None:
                # Subquery: find the created_at of the cursor row so we can
                # implement keyset pagination on (created_at, id) without
                # fetching the cursor row itself.
                cursor_stmt = select(Transaction.created_at, Transaction.id).where(
                    Transaction.id == cursor_id
                )
                cursor_result = await db.execute(cursor_stmt)
                cursor_row = cursor_result.one_or_none()
                if cursor_row is not None:
                    cursor_created_at, cursor_uuid = cursor_row
                    stmt = stmt.where(
                        (Transaction.created_at < cursor_created_at)
                        | (
                            (Transaction.created_at == cursor_created_at)
                            & (Transaction.id < cursor_uuid)
                        )
                    )

        # Fetch one extra row to determine if there is a next page
        stmt = stmt.limit(limit + 1)
        result = await db.execute(stmt)
        rows: list[Transaction] = list(result.scalars().all())

        has_more = len(rows) > limit
        items = rows[:limit]

        next_cursor: str | None = None
        if has_more and items:
            next_cursor = _encode_cursor(items[-1].id)

        return items, next_cursor
