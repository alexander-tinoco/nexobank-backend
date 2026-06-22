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


class ForgotPasswordRequest(BaseModel):
    """Payload for POST /auth/forgot-password."""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Response for POST /auth/forgot-password.

    In production the reset token is only sent via email.
    In development (ENVIRONMENT != 'production') the token is included in the
    response body so the flow can be tested without an email service.
    """

    message: str
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    """Payload for POST /auth/reset-password."""

    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long.")
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("Password must contain at least one letter.")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit.")
        return v
