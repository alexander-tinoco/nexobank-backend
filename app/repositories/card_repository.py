"""Card repository — all database access for the Card model.

Rules
-----
- No business logic here; only query construction and result mapping.
- The full card number is never persisted; only the last 4 digits.
"""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.card import Card, CardStatus, CardType


class CardRepository:
    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        card_id: uuid.UUID,
    ) -> Card | None:
        """Return the card with the given primary key, or *None*."""
        result = await db.execute(
            select(Card).where(Card.id == card_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_account_id(
        db: AsyncSession,
        account_id: uuid.UUID,
    ) -> list[Card]:
        """Return all cards linked to *account_id*."""
        result = await db.execute(
            select(Card).where(Card.account_id == account_id)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        account_id: uuid.UUID,
        last4: str,
        type: CardType,
        expires_at: date,
    ) -> Card:
        """Insert a new card and return the persisted instance."""
        card = Card(
            account_id=account_id,
            last4=last4,
            type=type,
            expires_at=expires_at,
            status=CardStatus.active,
        )
        db.add(card)
        await db.flush()
        return card

    @staticmethod
    async def update_status(
        db: AsyncSession,
        card: Card,
        status: CardStatus,
    ) -> Card:
        """Persist a new *status* on *card* and return the updated instance."""
        card.status = status
        db.add(card)
        await db.flush()
        return card
