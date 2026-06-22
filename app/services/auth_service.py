"""Auth service — business logic for registration, login, token management.

Rules
-----
- Never raises ``HTTPException``; only domain exceptions from
  ``app.core.exceptions`` are raised so the central handler can translate them.
- Never accesses SQLAlchemy directly; all data access goes through repositories.
- Never logs passwords, password hashes, or complete token values.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import InvalidCredentialsError
from app.core.logging import get_logger
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.user import User, UserStatus
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.password_reset_token_repository import (
    PasswordResetTokenRepository,
)
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository

logger = get_logger(__name__)


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str | None = None,
    ip_address: str | None = None,
) -> tuple[User, str, str]:
    """Register a new user and issue an initial token pair.

    We return ``InvalidCredentialsError`` on a duplicate email rather than a
    409/email-already-exists response so that the API does not reveal whether
    a given email is registered (enumeration protection).

    Returns:
        ``(user, access_token, refresh_token_raw)``
    """
    existing = await UserRepository.get_by_email(db, email)
    if existing is not None:
        logger.warning(
            "Registration attempted with duplicate email",
            extra={"ip_address": ip_address},
        )
        raise InvalidCredentialsError("Invalid registration details.")

    pw_hash = hash_password(password)
    user = await UserRepository.create(
        db,
        email=email,
        password_hash=pw_hash,
        full_name=full_name,
        phone=phone,
    )

    refresh_token_raw, refresh_token_hash = create_refresh_token(str(user.id))
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await RefreshTokenRepository.create(
        db,
        user_id=user.id,
        token_hash=refresh_token_hash,
        expires_at=expires_at,
    )

    access_token = create_access_token(str(user.id))

    await AuditLogRepository.log(
        db,
        action="USER_REGISTERED",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
        metadata={"email": email},
    )

    await db.commit()

    logger.info("User registered", extra={"user_id": str(user.id)})
    return user, access_token, refresh_token_raw


async def login_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip_address: str | None = None,
) -> tuple[User, str, str]:
    """Authenticate a user with email/password and issue a fresh token pair.

    Both "user not found" and "wrong password" raise the same
    ``InvalidCredentialsError`` to prevent email enumeration.

    Returns:
        ``(user, access_token, refresh_token_raw)``
    """
    user = await UserRepository.get_by_email(db, email)
    if user is None:
        await AuditLogRepository.log(
            db,
            action="LOGIN_FAILED",
            user_id=None,
            entity_type="user",
            entity_id=None,
            ip_address=ip_address,
            metadata={"reason": "user_not_found"},
        )
        await db.commit()
        logger.warning("Login failed: user not found", extra={"ip_address": ip_address})
        raise InvalidCredentialsError()

    if not verify_password(password, user.password_hash):
        await AuditLogRepository.log(
            db,
            action="LOGIN_FAILED",
            user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip_address=ip_address,
            metadata={"reason": "wrong_password"},
        )
        await db.commit()
        logger.warning(
            "Login failed: wrong password",
            extra={"user_id": str(user.id), "ip_address": ip_address},
        )
        raise InvalidCredentialsError()

    if user.status != UserStatus.active:
        logger.warning(
            "Login failed: account not active",
            extra={"user_id": str(user.id), "status": user.status.value},
        )
        raise InvalidCredentialsError()

    refresh_token_raw, refresh_token_hash = create_refresh_token(str(user.id))
    expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await RefreshTokenRepository.create(
        db,
        user_id=user.id,
        token_hash=refresh_token_hash,
        expires_at=expires_at,
    )

    access_token = create_access_token(str(user.id))

    await AuditLogRepository.log(
        db,
        action="LOGIN_SUCCESS",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
        metadata={"email": email},
    )

    await db.commit()

    logger.info("Login successful", extra={"user_id": str(user.id)})
    return user, access_token, refresh_token_raw


async def refresh_tokens(
    db: AsyncSession,
    *,
    refresh_token_raw: str,
) -> tuple[str, str]:
    """Rotate a refresh token and issue a new access+refresh token pair.

    The old refresh token is revoked on successful rotation so that each token
    can only be used once (refresh token rotation pattern).

    Returns:
        ``(new_access_token, new_refresh_token_raw)``

    Raises:
        ``InvalidCredentialsError`` if the token is invalid, revoked, or expired.
    """
    token_hash = hash_token(refresh_token_raw)
    stored = await RefreshTokenRepository.get_by_hash(db, token_hash)

    if stored is None or stored.revoked:
        logger.warning("Refresh attempt with invalid or revoked token")
        raise InvalidCredentialsError("Refresh token is invalid or has been revoked.")

    now = datetime.now(UTC)
    # Ensure expires_at is timezone-aware for comparison
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)

    if expires_at < now:
        logger.warning(
            "Refresh attempt with expired token",
            extra={"user_id": str(stored.user_id)},
        )
        raise InvalidCredentialsError("Refresh token has expired.")

    # Revoke the old token before issuing a new one (rotation)
    await RefreshTokenRepository.revoke(db, stored)

    new_refresh_raw, new_refresh_hash = create_refresh_token(str(stored.user_id))
    new_expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    await RefreshTokenRepository.create(
        db,
        user_id=stored.user_id,
        token_hash=new_refresh_hash,
        expires_at=new_expires_at,
    )

    new_access_token = create_access_token(str(stored.user_id))

    await AuditLogRepository.log(
        db,
        action="TOKEN_REFRESHED",
        user_id=stored.user_id,
        entity_type="user",
        entity_id=stored.user_id,
    )

    await db.commit()

    logger.info("Tokens refreshed", extra={"user_id": str(stored.user_id)})
    return new_access_token, new_refresh_raw


async def logout_user(
    db: AsyncSession,
    *,
    refresh_token_raw: str,
    user_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Invalidate the given refresh token and write an audit log entry.

    If the token is not found or already revoked this is treated as a no-op
    (idempotent logout) so that double-tapping logout on the client does not
    return an error.
    """
    token_hash = hash_token(refresh_token_raw)
    stored = await RefreshTokenRepository.get_by_hash(db, token_hash)

    if stored is not None and not stored.revoked:
        await RefreshTokenRepository.revoke(db, stored)

    await AuditLogRepository.log(
        db,
        action="LOGOUT",
        user_id=user_id,
        entity_type="user",
        entity_id=user_id,
        ip_address=ip_address,
    )

    await db.commit()

    logger.info("User logged out", extra={"user_id": str(user_id)})


async def request_password_reset(
    db: AsyncSession,
    *,
    email: str,
    ip_address: str | None = None,
) -> tuple[str | None, bool]:
    """Generate a one-time password reset token for the given email.

    Returns ``(raw_token, is_dev_mode)``.  The raw token is ``None`` in
    production — it must travel only via email, never in the response body.

    Always returns without error even if the email does not exist (prevents
    enumeration).  The caller decides whether to expose the token.
    """
    import secrets  # noqa: PLC0415

    user = await UserRepository.get_by_email(db, email)

    if user is None:
        logger.info("Password reset requested for unknown email", extra={"ip": ip_address})
        return None, not settings.is_production

    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(UTC) + timedelta(minutes=15)

    await PasswordResetTokenRepository.create(
        db,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )

    await AuditLogRepository.log(
        db,
        action="PASSWORD_RESET_REQUESTED",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
    )

    await db.commit()

    logger.info("Password reset token created", extra={"user_id": str(user.id)})
    is_dev = not settings.is_production
    return (raw_token if is_dev else None), is_dev


async def confirm_password_reset(
    db: AsyncSession,
    *,
    raw_token: str,
    new_password: str,
    ip_address: str | None = None,
) -> None:
    """Consume a reset token and update the user's password.

    Raises ``InvalidCredentialsError`` if the token is invalid, expired, or
    already used.
    """
    token_hash = hash_token(raw_token)
    stored = await PasswordResetTokenRepository.get_by_hash(db, token_hash)

    if stored is None or stored.used:
        raise InvalidCredentialsError("Reset token is invalid or has already been used.")

    now = datetime.now(UTC)
    expires_at = stored.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        raise InvalidCredentialsError("Reset token has expired.")

    user = await UserRepository.get_by_id(db, stored.user_id)
    if user is None:
        raise InvalidCredentialsError("Reset token is invalid.")

    new_hash = hash_password(new_password)
    await UserRepository.update(db, user, password_hash=new_hash)

    await PasswordResetTokenRepository.mark_used(db, stored)

    await AuditLogRepository.log(
        db,
        action="PASSWORD_RESET_COMPLETED",
        user_id=stored.user_id,
        entity_type="user",
        entity_id=stored.user_id,
        ip_address=ip_address,
    )

    await db.commit()

    logger.info("Password reset completed", extra={"user_id": str(stored.user_id)})


async def update_user_profile(
    db: AsyncSession,
    *,
    user: User,
    full_name: str | None = None,
    phone: str | None = None,
    ip_address: str | None = None,
) -> User:
    """Update mutable profile fields for the authenticated user.

    Only fields that are explicitly provided (non-None) are written to avoid
    accidentally clearing a value that was not part of the update payload.

    Returns:
        The updated ``User`` instance.
    """
    fields_to_update: dict[str, object] = {}
    if full_name is not None:
        fields_to_update["full_name"] = full_name
    if phone is not None:
        fields_to_update["phone"] = phone

    if fields_to_update:
        user = await UserRepository.update(db, user, **fields_to_update)

    await AuditLogRepository.log(
        db,
        action="PROFILE_UPDATED",
        user_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
        metadata={"updated_fields": list(fields_to_update.keys())},
    )

    await db.commit()

    logger.info(
        "Profile updated",
        extra={"user_id": str(user.id), "fields": list(fields_to_update.keys())},
    )
    return user
