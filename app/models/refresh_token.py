"""RefreshToken model — persists hashed refresh tokens for rotation & revocation.

Security design
---------------
- Only the SHA-256 hash of the raw token is stored; the raw token is returned
  to the client and never persisted, so a DB breach cannot replay tokens.
- ``revoked`` flag enables instant invalidation (e.g. on logout or compromise).
- ``expires_at`` enforces a hard time limit independent of the revoked flag.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RefreshToken(Base):
    """Hashed refresh token record.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at`` from
    :class:`app.models.base.Base`.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),  # SHA-256 hex digest is always 64 chars
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    revoked: Mapped[bool] = mapped_column(nullable=False, default=False)

    __table_args__ = (
        Index("ix_refresh_tokens_user_id", "user_id"),
        Index("ix_refresh_tokens_token_hash", "token_hash", unique=True),
    )
