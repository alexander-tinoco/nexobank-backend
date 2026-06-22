"""Cards router.

Endpoints
---------
GET   /accounts/{account_id}/cards   List cards for a specific account.
POST  /accounts/{account_id}/cards   Issue a new card for a specific account.
PATCH /cards/{card_id}/freeze        Freeze or unfreeze a card.

All business logic lives in ``app.services.card_service``; this module only
handles HTTP concerns (parsing, dependency injection, response serialisation).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.schemas.card import CardCreate, CardFreezeRequest, CardResponse
from app.services import card_service

router = APIRouter(tags=["cards"])


@router.get(
    "/accounts/{account_id}/cards",
    response_model=list[CardResponse],
    summary="List cards",
    description="Return all cards issued for the specified account.",
)
async def list_cards(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> list[CardResponse]:
    """List all cards for the given account, verifying ownership."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    cards = await card_service.get_account_cards(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
    )
    return [CardResponse.model_validate(c) for c in cards]


@router.post(
    "/accounts/{account_id}/cards",
    response_model=CardResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue card",
    description="Issue a new debit or credit card for the specified account.",
)
async def create_card(
    account_id: uuid.UUID,
    payload: CardCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> CardResponse:
    """Issue a new card for the given account, verifying ownership."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    card = await card_service.create_card(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
        card_type=payload.type,
    )
    await db.commit()
    return CardResponse.model_validate(card)


@router.patch(
    "/cards/{card_id}/freeze",
    response_model=CardResponse,
    summary="Freeze / unfreeze card",
    description=(
        "Set ``frozen=true`` to freeze the card or ``frozen=false`` to unfreeze it. "
        "Every state change is written to the audit log."
    ),
)
async def freeze_card(
    card_id: uuid.UUID,
    payload: CardFreezeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> CardResponse:
    """Freeze or unfreeze a card, verifying that the caller owns it."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    ip_address: str | None = (
        request.client.host if request.client else None
    )
    card = await card_service.set_card_frozen(
        db,
        card_id=card_id,
        frozen=payload.frozen,
        requesting_user_id=user.id,
        ip_address=ip_address,
    )
    await db.commit()
    return CardResponse.model_validate(card)
