"""Repository for DeviceToken — CRUD for push notification device tokens."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device_token import DevicePlatform, DeviceToken


class DeviceTokenRepository:

    @staticmethod
    async def upsert(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        token: str,
        platform: DevicePlatform,
    ) -> DeviceToken:
        """Register a token, or reactivate it if it already exists."""
        existing = await db.execute(
            select(DeviceToken).where(DeviceToken.token == token)
        )
        device_token = existing.scalar_one_or_none()

        if device_token is not None:
            device_token.user_id = user_id
            device_token.platform = platform
            device_token.active = True
            await db.flush()
            return device_token

        device_token = DeviceToken(
            user_id=user_id,
            token=token,
            platform=platform,
            active=True,
        )
        db.add(device_token)
        await db.flush()
        return device_token

    @staticmethod
    async def get_by_id(
        db: AsyncSession,
        token_id: uuid.UUID,
    ) -> DeviceToken | None:
        result = await db.execute(
            select(DeviceToken).where(DeviceToken.id == token_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_by_user(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[DeviceToken]:
        result = await db.execute(
            select(DeviceToken).where(
                DeviceToken.user_id == user_id,
                DeviceToken.active == True,  # noqa: E712
            )
        )
        return list(result.scalars().all())

    @staticmethod
    async def deactivate(db: AsyncSession, token: DeviceToken) -> None:
        token.active = False
        await db.flush()

    @staticmethod
    async def deactivate_all_for_user(db: AsyncSession, user_id: uuid.UUID) -> int:
        """Deactivate all active tokens for a user (e.g. on logout from all devices)."""
        result = await db.execute(
            update(DeviceToken)
            .where(DeviceToken.user_id == user_id, DeviceToken.active == True)  # noqa: E712
            .values(active=False)
        )
        return result.rowcount or 0
