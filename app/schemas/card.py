"""Pydantic v2 schemas for card-related endpoints.

``CardCreate`` — input for issuing a new card.
``CardResponse`` — serialised output for a single card.
``CardFreezeRequest`` — input for PATCH /cards/{card_id}/freeze.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.card import CardStatus, CardType


class CardCreate(BaseModel):
    """Input schema for POST /accounts/{account_id}/cards."""

    type: CardType


class CardResponse(BaseModel):
    """Output schema for a single card."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    last4: str
    type: CardType
    status: CardStatus
    expires_at: date
    created_at: datetime


class CardFreezeRequest(BaseModel):
    """Input schema for PATCH /cards/{card_id}/freeze.

    ``frozen=True``  → freeze the card (status becomes ``frozen``).
    ``frozen=False`` → unfreeze the card (status becomes ``active``).
    """

    frozen: bool
