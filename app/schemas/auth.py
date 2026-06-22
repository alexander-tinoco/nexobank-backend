"""Auth-related Pydantic v2 request/response schemas.

SECURITY: None of these schemas expose ``password_hash``.  The password field
only appears on inbound requests and is consumed (hashed) immediately in the
service layer — it is never stored or returned.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, EmailStr, field_validator


class RegisterRequest(BaseModel):
    """Payload for POST /auth/register."""

    email: EmailStr
    password: str
    full_name: str
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """Enforce minimum password complexity rules."""
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        return v


class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token pair returned after successful auth."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    """Payload for POST /auth/refresh."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Payload for POST /auth/logout."""

    refresh_token: str
