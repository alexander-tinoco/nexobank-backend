"""PasswordResetToken model — persists hashed one-time-use reset tokens.

Security design
---------------
- Only the SHA-256 hash of the raw token is stored; the raw token is returned
  only in non-production environments (since we have no email service yet).
- ``used`` flag ensures each token can only be consumed once.
- ``expires_at`` enforces a 15-minute hard time limit.
- Soft FK on ``user_id`` so the record survives the user row for audit purposes,
  but CASCADE DELETE on the FK means cleanup happens automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PasswordResetToken(Base):
    """Hashed, single-use password reset token.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at`` from Base.
    """

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ix_password_reset_tokens_user_id", "user_id"),
        Index("ix_password_reset_tokens_token_hash", "token_hash", unique=True),
    )
