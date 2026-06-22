"""Card ORM model.

A card is always linked to an account.  The full PAN (Primary Account Number)
is *never* stored — only the last 4 digits.

Design decisions
----------------
- ``last4`` is a 4-character string; no other card number data is persisted.
- ``expires_at`` is a ``date`` (not ``datetime``) matching the month/year on a
  physical card.  Day is stored as the last day of the expiry month.
- Foreign key references ``accounts.id`` as a string literal to avoid circular
  imports.
"""

import enum
import uuid
from datetime import date

import sqlalchemy as sa
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CardType(enum.StrEnum):
    debit = "debit"
    credit = "credit"


class CardStatus(enum.StrEnum):
    active = "active"
    frozen = "frozen"
    cancelled = "cancelled"


class Card(Base):
    """A debit or credit card linked to a bank account."""

    __tablename__ = "cards"

    account_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("accounts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # Only the last 4 digits of the card number are stored — never the full PAN.
    last4: Mapped[str] = mapped_column(String(4), nullable=False)
    type: Mapped[CardType] = mapped_column(
        sa.Enum(CardType, name="card_type"),
        nullable=False,
    )
    status: Mapped[CardStatus] = mapped_column(
        sa.Enum(CardStatus, name="card_status"),
        nullable=False,
        default=CardStatus.active,
    )
    # Date the card expires (month/year only — stored as last day of that month).
    expires_at: Mapped[date] = mapped_column(sa.Date, nullable=False)

    __table_args__ = (
        Index("ix_cards_account_id", "account_id"),
    )
