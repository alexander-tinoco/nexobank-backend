"""UserRepository — all database access for the User model.

Rules enforced here
-------------------
- No business logic: this layer only reads/writes data.
- Always returns ORM instances or None; never raises HTTPException.
- Callers (services) are responsible for committing the session.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
        """Return the User with the given primary key, or None if not found."""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        """Return the User whose email matches (case-sensitive), or None."""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        email: str,
        password_hash: str,
        full_name: str,
        phone: str | None = None,
    ) -> User:
        """Persist a new User and flush to populate server-generated fields."""
        user = User(
            email=email,
            password_hash=password_hash,
            full_name=full_name,
            phone=phone,
        )
        db.add(user)
        await db.flush()
        return user

    @staticmethod
    async def update(db: AsyncSession, user: User, **fields: object) -> User:
        """Apply *fields* to *user* and flush.

        Only non-None values in *fields* are written; callers should filter
        before calling so that an explicit ``None`` (cleared phone) vs. an
        absent key (not touching the field) can be distinguished if needed.
        """
        for key, value in fields.items():
            setattr(user, key, value)
        db.add(user)
        await db.flush()
        return user
