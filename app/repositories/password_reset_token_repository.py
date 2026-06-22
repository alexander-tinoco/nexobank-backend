"""Repository for PasswordResetToken — only insert and read; never update/delete."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.password_reset_token import PasswordResetToken


class PasswordResetTokenRepository:

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            used=False,
        )
        db.add(token)
        await db.flush()
        return token

    @staticmethod
    async def get_by_hash(
        db: AsyncSession,
        token_hash: str,
    ) -> PasswordResetToken | None:
        result = await db.execute(
            select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_used(db: AsyncSession, token: PasswordResetToken) -> None:
        token.used = True
        await db.flush()
