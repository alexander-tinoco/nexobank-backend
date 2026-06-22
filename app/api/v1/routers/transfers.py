"""Transfers router — atomic money movement between two accounts.

Endpoints
---------
POST /api/v1/transfers
    Create a transfer between two accounts.
    Returns the ``transfer_out`` transaction (the debit on the source account).

Design notes
------------
- The ``Idempotency-Key`` is part of the request body (``TransferRequest``)
  rather than a header so it is validated with Pydantic and included in the
  OpenAPI schema.  Clients must generate a unique key per *logical* transfer
  attempt (e.g. a UUID v4) and reuse the same key on retries.
- HTTP 201 is returned on success.  On an idempotent replay (same key,
  same request), HTTP 201 is also returned — the client should not
  distinguish between "created now" and "already existed".
- Business logic and the SELECT … FOR UPDATE concurrency guard live in
  ``transaction_service``, not here.  The router only handles HTTP concerns.
- ``request.client.host`` can be ``None`` for unit-test clients; it is passed
  as-is to the service, which accepts ``None``.
- ``from __future__ import annotations`` is intentionally absent: slowapi's
  ``@limiter.limit`` decorator resolves parameter types at decoration time, and
  PEP 563 lazy evaluation causes FastAPI to lose the request body type.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.schemas.transaction import TransactionResponse, TransferRequest
from app.services import transaction_service
from app.workers.notification_tasks import send_transaction_notification_task

router = APIRouter(tags=["transfers"])


@router.post(
    "/transfers",
    response_model=TransactionResponse,
    status_code=201,
    summary="Create a transfer",
    description=(
        "Transfers money from one account to another atomically. "
        "Requires authentication; the authenticated user must own the source account. "
        "Provide a unique ``idempotency_key`` per logical transfer; repeating the same "
        "key returns the original response without re-applying the transfer. "
        "Rate-limited to 10 requests per minute per IP."
    ),
)
@limiter.limit("10/minute")
async def create_transfer(
    request: Request,
    body: Annotated[TransferRequest, Body()],
    current_user: object = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> TransactionResponse:
    """Execute a transfer and return the source-account debit transaction.

    Raises HTTP 422 if funds are insufficient or an account is frozen.
    Raises HTTP 403 if the authenticated user does not own the source account.
    Raises HTTP 404 if either account does not exist.
    """
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]

    ip_address: str | None = request.client.host if request.client else None

    tx_out, _ = await transaction_service.execute_transfer(
        db,
        from_account_id=body.from_account_id,
        to_account_id=body.to_account_id,
        amount=body.amount,
        currency=body.currency,
        idempotency_key=body.idempotency_key,
        requesting_user_id=user.id,
        description=body.description,
        ip_address=ip_address,
    )

    # Commit here — the router owns the transaction boundary for write endpoints
    await db.commit()

    # Fire-and-forget: notify both parties via Redis pub/sub → WebSocket
    send_transaction_notification_task.delay(
        sender_user_id=str(user.id),
        receiver_account_id=str(body.to_account_id),
        amount=str(body.amount),
        currency=body.currency,
        tx_id=str(tx_out.id),
        description=body.description,
    )

    return TransactionResponse.model_validate(tx_out)
