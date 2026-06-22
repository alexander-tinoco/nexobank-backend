"""Transactions router — read-only access to the immutable transaction ledger.

Endpoints
---------
GET /api/v1/accounts/{account_id}/transactions
    List transactions for an account with cursor-based pagination.
    Requires authentication; the authenticated user must own the account.

Design notes
------------
- Pagination uses a cursor (opaque base64 token) rather than offset to avoid
  the performance cliff on large transaction histories.
- Business logic (ownership check, DB query) lives in ``transaction_service``,
  not here.  The router only handles HTTP concerns.
- The ``limit`` query parameter is bounded to [1, 100] to prevent unbounded
  memory allocations.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.schemas.transaction import TransactionListResponse, TransactionResponse
from app.services import transaction_service

router = APIRouter(tags=["transactions"])


@router.get(
    "/accounts/{account_id}/transactions",
    response_model=TransactionListResponse,
    summary="List account transactions",
    description=(
        "Returns a cursor-paginated list of transactions for the given account. "
        "The authenticated user must own the account."
    ),
)
async def list_transactions(
    account_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100, description="Number of items per page."),
    cursor: str | None = Query(
        default=None,
        description="Opaque pagination cursor returned by the previous response.",
    ),
    current_user: object = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionListResponse:
    """Return a paginated list of transactions for *account_id*.

    Raises HTTP 403 if the authenticated user does not own the account,
    HTTP 404 if the account does not exist.
    """
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]

    items, next_cursor = await transaction_service.get_account_transactions(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
        limit=limit,
        cursor=cursor,
    )

    return TransactionListResponse(
        items=[TransactionResponse.model_validate(t) for t in items],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )
