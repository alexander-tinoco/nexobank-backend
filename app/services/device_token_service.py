"""Device token service — manage FCM/APNs push notification tokens."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedResourceError
from app.core.logging import get_logger
from app.models.device_token import DevicePlatform, DeviceToken
from app.repositories.audit_log_repository import AuditLogRepository
from app.repositories.device_token_repository import DeviceTokenRepository

logger = get_logger(__name__)


async def register_device_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    token: str,
    platform: DevicePlatform,
    ip_address: str | None = None,
) -> DeviceToken:
    """Register or reactivate a push notification device token for the user.

    If the same token already exists (possibly from a previous install), it is
    reactivated and associated with the current user.
    """
    device_token = await DeviceTokenRepository.upsert(
        db,
        user_id=user_id,
        token=token,
        platform=platform,
    )

    await AuditLogRepository.log(
        db,
        action="DEVICE_TOKEN_REGISTERED",
        user_id=user_id,
        entity_type="device_token",
        entity_id=device_token.id,
        ip_address=ip_address,
        metadata={"platform": platform.value},
    )

    await db.commit()

    logger.info(
        "Device token registered",
        extra={"user_id": str(user_id), "platform": platform.value},
    )
    return device_token


async def list_device_tokens(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
) -> list[DeviceToken]:
    """Return all active device tokens for the user."""
    return await DeviceTokenRepository.get_active_by_user(db, user_id)


async def remove_device_token(
    db: AsyncSession,
    *,
    token_id: uuid.UUID,
    requesting_user_id: uuid.UUID,
    ip_address: str | None = None,
) -> None:
    """Deactivate a specific device token, verifying ownership.

    Raises ``UnauthorizedResourceError`` if the token does not belong to the
    requesting user.
    """
    token = await DeviceTokenRepository.get_by_id(db, token_id)

    if token is None or token.user_id != requesting_user_id:
        raise UnauthorizedResourceError("Device token not found or access denied.")

    await DeviceTokenRepository.deactivate(db, token)

    await AuditLogRepository.log(
        db,
        action="DEVICE_TOKEN_REMOVED",
        user_id=requesting_user_id,
        entity_type="device_token",
        entity_id=token_id,
        ip_address=ip_address,
    )

    await db.commit()

    logger.info(
        "Device token removed",
        extra={"user_id": str(requesting_user_id), "token_id": str(token_id)},
    )
