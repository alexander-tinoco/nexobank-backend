"""Device tokens router — register and manage FCM/APNs push notification tokens.

Endpoints
---------
GET    /users/me/device-tokens              List active device tokens for current user.
POST   /users/me/device-tokens              Register (or reactivate) a device token.
DELETE /users/me/device-tokens/{token_id}   Remove a specific device token.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.models.user import User
from app.schemas.device_token import (
    DeviceTokenListResponse,
    DeviceTokenRegister,
    DeviceTokenResponse,
)
from app.services import device_token_service

router = APIRouter(prefix="/users/me/device-tokens", tags=["device-tokens"])


@router.get(
    "",
    response_model=DeviceTokenListResponse,
    summary="List device tokens",
    description="Return all active push notification tokens registered for the current user.",
)
async def list_device_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DeviceTokenListResponse:
    tokens = await device_token_service.list_device_tokens(db, user_id=current_user.id)
    return DeviceTokenListResponse(
        items=[DeviceTokenResponse.model_validate(t) for t in tokens],
        total=len(tokens),
    )


@router.post(
    "",
    response_model=DeviceTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register device token",
    description=(
        "Register an FCM (Android) or APNs (iOS) push notification token for this device. "
        "If the token already exists it is reactivated. "
        "Call this on every app launch so the token stays current."
    ),
)
async def register_device_token(
    body: DeviceTokenRegister,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DeviceTokenResponse:
    ip = request.client.host if request.client else None
    token = await device_token_service.register_device_token(
        db,
        user_id=current_user.id,
        token=body.token,
        platform=body.platform,
        ip_address=ip,
    )
    return DeviceTokenResponse.model_validate(token)


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Remove device token",
    description=(
        "Deactivate a specific device token (e.g. when the user logs out of one device "
        "while staying logged in on others). The token record is kept for audit purposes."
    ),
)
async def remove_device_token(
    token_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    ip = request.client.host if request.client else None
    await device_token_service.remove_device_token(
        db,
        token_id=token_id,
        requesting_user_id=current_user.id,
        ip_address=ip,
    )
