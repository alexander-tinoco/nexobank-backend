"""Authentication router.

Endpoints
---------
- POST /auth/register  — create account and receive initial token pair
- POST /auth/login     — exchange credentials for token pair (rate-limited)
- POST /auth/refresh   — rotate refresh token and get a new token pair
- POST /auth/logout    — revoke a refresh token

All business logic lives in ``app.services.auth_service``.  This layer only
validates input, delegates to the service, and maps the result to HTTP.
"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(
    body: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Create a new NexoBank account and return an initial token pair.

    - Duplicate emails do not reveal whether the address is registered.
    - Password is hashed (Argon2) before storage; the plaintext is never logged.
    """
    ip = request.client.host if request.client else None
    _user, access_token, refresh_token = await auth_service.register_user(
        db,
        email=str(body.email),
        password=body.password,
        full_name=body.full_name,
        phone=body.phone,
        ip_address=ip,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in with email and password",
)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: Annotated[LoginRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Authenticate and return a JWT access token plus a refresh token.

    Rate-limited to 5 requests per minute per IP to mitigate brute-force attacks.
    Both "user not found" and "wrong password" return 401 to prevent enumeration.
    """
    ip = request.client.host if request.client else None
    _user, access_token, refresh_token = await auth_service.login_user(
        db,
        email=str(body.email),
        password=body.password,
        ip_address=ip,
    )
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token and get a new token pair",
)
async def refresh(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange a valid refresh token for a new access + refresh token pair.

    The submitted refresh token is revoked immediately on success (token rotation).
    Using an already-revoked token returns 401.
    """
    new_access, new_refresh = await auth_service.refresh_tokens(
        db,
        refresh_token_raw=body.refresh_token,
    )
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke a refresh token (logout)",
)
async def logout(
    body: LogoutRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke the supplied refresh token, effectively logging the user out.

    The access token will expire naturally (short TTL); for immediate
    invalidation the client should discard it locally.
    Idempotent: calling logout with an already-revoked token is a no-op.
    """
    ip = request.client.host if request.client else None
    await auth_service.logout_user(
        db,
        refresh_token_raw=body.refresh_token,
        user_id=current_user.id,
        ip_address=ip,
    )


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    summary="Request a password reset link",
)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ForgotPasswordResponse:
    """Send a password reset token for the given email.

    Always returns HTTP 200 regardless of whether the email is registered —
    this prevents email enumeration attacks.

    In non-production environments the reset token is included in the response
    body so the flow can be tested without a configured email service.
    In production the token travels only via email (implement your email
    provider in ``auth_service.request_password_reset`` when ready).
    """
    ip = request.client.host if request.client else None
    raw_token, is_dev = await auth_service.request_password_reset(
        db,
        email=str(body.email),
        ip_address=ip,
    )
    return ForgotPasswordResponse(
        message="If that email is registered you will receive a reset link shortly.",
        reset_token=raw_token if is_dev else None,
    )


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Reset password using a one-time token",
)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Consume a reset token and update the account password.

    The token expires after 15 minutes and can only be used once.
    Returns 401 if the token is invalid, expired, or already used.
    """
    ip = request.client.host if request.client else None
    await auth_service.confirm_password_reset(
        db,
        raw_token=body.token,
        new_password=body.new_password,
        ip_address=ip,
    )
