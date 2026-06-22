"""Pydantic schemas for device push-notification token endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.device_token import DevicePlatform


class DeviceTokenRegister(BaseModel):
    """Payload for POST /users/me/device-tokens."""

    token: str
    platform: DevicePlatform


class DeviceTokenResponse(BaseModel):
    """Response schema for a single device token record."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    token: str
    platform: DevicePlatform
    active: bool
    created_at: datetime


class DeviceTokenListResponse(BaseModel):
    """Response schema for GET /users/me/device-tokens."""

    items: list[DeviceTokenResponse]
    total: int
