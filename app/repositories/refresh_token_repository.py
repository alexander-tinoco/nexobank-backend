"""RefreshTokenRepository — all database access for the RefreshToken model.

Security notes
--------------
- Tokens are looked up by their SHA-256 hash, never the raw value.
- Revocation sets the ``revoked`` flag; rows are not deleted so that audit
  trail integrity is preserved until a scheduled cleanup removes expired rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.refresh_token import RefreshToken


class RefreshTokenRepository:
    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Persist a new hashed refresh token and flush."""
        token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            revoked=False,
        )
        db.add(token)
        await db.flush()
        return token

    @staticmethod
    async def get_by_hash(
        db: AsyncSession,
        token_hash: str,
    ) -> RefreshToken | None:
        """Return the RefreshToken whose hash matches, or None."""
        result = await db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def revoke(db: AsyncSession, token: RefreshToken) -> None:
        """Mark a single refresh token as revoked."""
        token.revoked = True
        db.add(token)
        await db.flush()

    @staticmethod
    async def revoke_all_for_user(
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> int:
        """Revoke every active refresh token for the given user.

        Returns the number of rows affected.
        """
        result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked == False,  # noqa: E712
            )
            .values(revoked=True)
        )
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    async def delete_expired(db: AsyncSession) -> int:
        """Delete all tokens whose ``expires_at`` is in the past.

        Intended for use by a scheduled cleanup task; returns the row count.
        """
        now = datetime.now(UTC)
        result = await db.execute(
            delete(RefreshToken).where(RefreshToken.expires_at < now)
        )
        return result.rowcount  # type: ignore[return-value]
