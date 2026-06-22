"""Users router.

Endpoints
---------
- GET  /users/me   — return the authenticated user's profile
- PATCH /users/me  — update mutable profile fields (full_name, phone)

All mutation logic lives in ``app.services.auth_service.update_user_profile``.
This layer only validates input, delegates, and returns the response.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate
from app.services import auth_service

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the authenticated user's profile",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
) -> UserResponse:
    """Return the profile of the currently authenticated user.

    Requires a valid ``Authorization: Bearer <access_token>`` header.
    """
    return UserResponse.model_validate(current_user)


@router.patch(
    "/me",
    response_model=UserResponse,
    summary="Update the authenticated user's profile",
)
async def update_me(
    body: UserUpdate,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Update mutable profile fields (``full_name``, ``phone``).

    Only fields explicitly provided in the request body are updated.
    Every update is recorded in the audit log.
    """
    ip = request.client.host if request.client else None
    updated_user = await auth_service.update_user_profile(
        db,
        user=current_user,
        full_name=body.full_name,
        phone=body.phone,
        ip_address=ip,
    )
    return UserResponse.model_validate(updated_user)
