"""DeviceToken model — stores FCM/APNs push notification tokens per device.

Design
------
- One user can have multiple device tokens (phone + tablet + web, etc.).
- ``active`` flag lets us soft-disable a token on logout without losing history.
- The token itself is stored plaintext because FCM/APNs require the exact value
  to send pushes; it is not a secret in the same sense as a password or JWT.
- Unique constraint on ``token`` prevents duplicate registrations.
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DevicePlatform(enum.StrEnum):
    ios = "ios"
    android = "android"
    web = "web"


class DeviceToken(Base):
    """FCM/APNs device token registered by the mobile/web client.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at`` from Base.
    """

    __tablename__ = "device_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        unique=True,
    )
    platform: Mapped[DevicePlatform] = mapped_column(
        SAEnum(DevicePlatform, name="device_platform"),
        nullable=False,
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_device_tokens_user_id", "user_id"),
        Index("ix_device_tokens_token", "token", unique=True),
    )
