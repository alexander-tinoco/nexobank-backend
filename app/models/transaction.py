"""Transaction model — append-only ledger of all money movements.

Design decisions
----------------
- No UPDATE or DELETE methods exist for this model (CLAUDE.md rule 2).
  Corrections are handled via new reversal transactions with
  ``reference_transaction_id`` pointing to the original.
- ``idempotency_key`` has a unique constraint so the DB itself guarantees
  that a duplicate POST /transfers cannot create two entries even under race.
- Two indexes on ``(account_id, created_at)`` support efficient cursor-based
  pagination without a full table scan.
- ``counterparty_account_id`` is intentionally nullable: deposits and
  withdrawals have no counterparty, only transfers do.
- ``Numeric(18, 2)`` for amount — never float.
"""

import enum
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TransactionType(str, enum.Enum):
    """Enumeration of the four atomic movements in the double-entry ledger."""

    deposit = "deposit"
    withdrawal = "withdrawal"
    transfer_out = "transfer_out"  # debit from the source account
    transfer_in = "transfer_in"  # credit to the destination account


class TransactionStatus(str, enum.Enum):
    """Lifecycle status of a transaction."""

    pending = "pending"
    completed = "completed"
    reversed = "reversed"


class Transaction(Base):
    """Immutable record of a single monetary movement on an account.

    Every transfer creates two Transaction rows:
    - ``transfer_out`` on the source account (amount debited).
    - ``transfer_in``  on the destination account (amount credited).

    Both rows share the same ``idempotency_key`` base; the ``transfer_in``
    row uses ``<key>_in`` to keep the unique constraint intact while linking
    the pair conceptually.
    """

    __tablename__ = "transactions"

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    counterparty_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    type: Mapped[TransactionType] = mapped_column(nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        default=TransactionStatus.completed,
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(64),
        unique=True,
        nullable=True,
    )
    reference_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("transactions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        # Fast lookup of all transactions for a given account
        Index("ix_transactions_account_id", "account_id"),
        # Supports cursor-based pagination ordered by (account, time)
        Index("ix_transactions_account_id_created_at", "account_id", "created_at"),
        # Unique index on idempotency_key (DB-level guard against duplicates)
        Index(
            "ix_transactions_idempotency_key",
            "idempotency_key",
            unique=True,
        ),
    )
