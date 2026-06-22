"""Accounts router.

Endpoints
---------
GET  /accounts                   List all accounts for the authenticated user.
POST /accounts                   Open a new bank account.
GET  /accounts/{id}              Retrieve details of a specific account.
POST /accounts/{id}/deposit      Deposit funds into an account.

All business logic lives in ``app.services.account_service``; this module only
handles HTTP concerns (parsing, dependency injection, response serialisation).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.schemas.account import (
    AccountCreate,
    AccountListResponse,
    AccountResponse,
    DepositRequest,
)
from app.schemas.transaction import TransactionResponse
from app.services import account_service

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get(
    "",
    response_model=AccountListResponse,
    summary="List accounts",
    description="Return all bank accounts belonging to the authenticated user.",
)
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> AccountListResponse:
    """List all accounts owned by the current user."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    accounts = await account_service.get_user_accounts(db, user_id=user.id)
    return AccountListResponse(
        items=[AccountResponse.model_validate(a) for a in accounts],
        total=len(accounts),
    )


@router.post(
    "",
    response_model=AccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create account",
    description="Open a new checking or savings account in the requested currency.",
)
async def create_account(
    payload: AccountCreate,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> AccountResponse:
    """Create a new bank account for the current user."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    account = await account_service.create_account(
        db,
        user_id=user.id,
        currency=payload.currency,
        account_type=payload.type,
    )
    await db.commit()
    return AccountResponse.model_validate(account)


@router.get(
    "/{account_id}",
    response_model=AccountResponse,
    summary="Get account",
    description="Retrieve details of a specific account owned by the authenticated user.",
)
async def get_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> AccountResponse:
    """Retrieve a single account by ID, verifying ownership."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    account = await account_service.get_account(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
    )
    return AccountResponse.model_validate(account)


@router.post(
    "/{account_id}/deposit",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Deposit funds",
    description=(
        "Credit funds into an account owned by the authenticated user. "
        "This simulates an incoming external transfer (e.g. SPEI/ACH). "
        "The operation is atomic and writes an immutable AuditLog entry."
    ),
)
async def deposit(
    account_id: uuid.UUID,
    payload: DepositRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: object = Depends(get_current_active_user),
) -> TransactionResponse:
    """Deposit funds into the specified account."""
    from app.models.user import User  # noqa: PLC0415

    user: User = current_user  # type: ignore[assignment]
    ip = request.client.host if request.client else None

    tx = await account_service.deposit_funds(
        db,
        account_id=account_id,
        requesting_user_id=user.id,
        amount=payload.amount,
        description=payload.description,
        ip_address=ip,
    )
    await db.commit()
    return TransactionResponse.model_validate(tx)
