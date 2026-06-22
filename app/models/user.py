"""User model — core identity entity for NexoBank.

Each registered user has exactly one record here.  Auth tokens (JWT access
tokens + opaque refresh tokens) are linked to the user's ``id``.

Security notes
--------------
- ``password_hash`` is NEVER included in any Pydantic response schema.
- ``status`` allows soft-disabling accounts without data loss.
- ``role`` gates admin-only endpoints at the service layer.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserStatus(str, enum.Enum):
    """Lifecycle state of a user account."""

    active = "active"
    inactive = "inactive"
    suspended = "suspended"


class UserRole(str, enum.Enum):
    """Coarse-grained permission level."""

    customer = "customer"
    admin = "admin"


class User(Base):
    """Registered NexoBank user.

    Inherits ``id`` (UUID PK), ``created_at``, and ``updated_at`` from
    :class:`app.models.base.Base`.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status"),
        nullable=False,
        default=UserStatus.active,
        server_default=UserStatus.active.value,
    )
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="user_role"),
        nullable=False,
        default=UserRole.customer,
        server_default=UserRole.customer.value,
    )

    __table_args__ = (
        Index("ix_users_email", "email", unique=True),
        Index("ix_users_status", "status"),
    )

    @property
    def is_active(self) -> bool:
        """Return True when the account status is ``active``."""
        return self.status == UserStatus.active
