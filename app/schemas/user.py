"""User-related Pydantic v2 response/update schemas.

SECURITY: ``password_hash`` is intentionally absent from every class here.
This file is the authoritative definition of what user data the API exposes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole, UserStatus


class UserResponse(BaseModel):
    """Public representation of a NexoBank user — safe to serialize in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    status: UserStatus
    role: UserRole
    created_at: datetime


class UserUpdate(BaseModel):
    """Fields the user may update on their own profile."""

    full_name: str | None = None
    phone: str | None = None
