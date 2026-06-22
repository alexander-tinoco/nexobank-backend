"""Account ORM model.

Each bank account belongs to a single user, holds a balance in a specific
currency, and can be active, frozen, or closed.

Design decisions
----------------
- ``balance`` is ``Numeric(18, 2)`` — never ``float``.  Financial arithmetic
  must use ``Decimal`` end-to-end.
- ``account_number`` is generated application-side (format: currency code +
  12 random digits) and stored with a unique constraint.
- Foreign key to ``users.id`` is declared as a string literal so this module
  does not need to import the ``User`` model (avoiding circular imports).
"""

import enum
import uuid
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AccountStatus(str, enum.Enum):
    active = "active"
    frozen = "frozen"
    closed = "closed"


class AccountType(str, enum.Enum):
    checking = "checking"
    savings = "savings"


class Account(Base):
    """A bank account owned by a single user."""

    __tablename__ = "accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_number: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
    )
    # ISO 4217 currency code: "MXN", "USD", etc.
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    # NEVER float — financial amounts are always Decimal / Numeric(18,2).
    balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0.00"),
    )
    status: Mapped[AccountStatus] = mapped_column(
        sa.Enum(AccountStatus, name="account_status"),
        nullable=False,
        default=AccountStatus.active,
    )
    type: Mapped[AccountType] = mapped_column(
        sa.Enum(AccountType, name="account_type"),
        nullable=False,
        default=AccountType.checking,
    )

    __table_args__ = (
        Index("ix_accounts_user_id", "user_id"),
        Index("ix_accounts_account_number", "account_number", unique=True),
    )
