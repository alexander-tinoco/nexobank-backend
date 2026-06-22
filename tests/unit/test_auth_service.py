"""Unit tests for ``app.services.auth_service``.

Repositories are replaced with lightweight fakes so these tests run
without a database.  Only the service's own logic is exercised.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import InvalidCredentialsError
from app.core.security import hash_password
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole, UserStatus
from app.services import auth_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    email: str = "user@example.com",
    status: UserStatus = UserStatus.active,
    role: UserRole = UserRole.customer,
) -> User:
    """Build a User ORM object without touching the database."""
    user = User.__new__(User)
    user.id = uuid.uuid4()
    user.email = email
    user.password_hash = hash_password("Password1")
    user.full_name = "Test User"
    user.phone = None
    user.status = status
    user.role = role
    user.created_at = datetime.now(UTC)
    user.updated_at = datetime.now(UTC)
    return user


def _make_refresh_token(
    *,
    user_id: uuid.UUID | None = None,
    token_hash: str = "fakehash",
    revoked: bool = False,
    expired: bool = False,
) -> RefreshToken:
    rt = RefreshToken.__new__(RefreshToken)
    rt.id = uuid.uuid4()
    rt.user_id = user_id or uuid.uuid4()
    rt.token_hash = token_hash
    rt.revoked = revoked
    rt.expires_at = datetime.now(UTC) + (
        timedelta(hours=-1) if expired else timedelta(days=30)
    )
    rt.created_at = datetime.now(UTC)
    rt.updated_at = datetime.now(UTC)
    return rt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> AsyncMock:
    """Return a mock AsyncSession that does nothing on commit/flush/add."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


# ---------------------------------------------------------------------------
# register_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_success(db: AsyncMock) -> None:
    """Successful registration returns a user plus a token pair."""
    new_user = _make_user(email="new@example.com")

    with (
        patch(
            "app.services.auth_service.UserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.auth_service.UserRepository.create",
            new_callable=AsyncMock,
            return_value=new_user,
        ),
        patch(
            "app.services.auth_service.RefreshTokenRepository.create",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new_callable=AsyncMock,
        ),
    ):
        user, access_token, refresh_token = await auth_service.register_user(
            db,
            email="new@example.com",
            password="Password1",
            full_name="New User",
        )

    assert user.email == "new@example.com"
    assert isinstance(access_token, str) and len(access_token) > 0
    assert isinstance(refresh_token, str) and len(refresh_token) > 0


@pytest.mark.asyncio
async def test_register_duplicate_email(db: AsyncMock) -> None:
    """Duplicate email raises InvalidCredentialsError (not HTTPException)."""
    existing = _make_user(email="taken@example.com")

    with patch(
        "app.services.auth_service.UserRepository.get_by_email",
        new_callable=AsyncMock,
        return_value=existing,
    ):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.register_user(
                db,
                email="taken@example.com",
                password="Password1",
                full_name="Some User",
            )


# ---------------------------------------------------------------------------
# login_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_success(db: AsyncMock) -> None:
    """Correct credentials return the user and a token pair."""
    user = _make_user()

    with (
        patch(
            "app.services.auth_service.UserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=user,
        ),
        patch(
            "app.services.auth_service.RefreshTokenRepository.create",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new_callable=AsyncMock,
        ),
    ):
        result_user, access_token, refresh_token = await auth_service.login_user(
            db,
            email="user@example.com",
            password="Password1",
        )

    assert result_user.id == user.id
    assert isinstance(access_token, str) and len(access_token) > 0
    assert isinstance(refresh_token, str) and len(refresh_token) > 0


@pytest.mark.asyncio
async def test_login_wrong_password(db: AsyncMock) -> None:
    """Wrong password raises InvalidCredentialsError, not a password-specific error."""
    user = _make_user()

    with (
        patch(
            "app.services.auth_service.UserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=user,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new_callable=AsyncMock,
        ),
    ):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login_user(
                db,
                email="user@example.com",
                password="wrongpassword",
            )


@pytest.mark.asyncio
async def test_login_user_not_found(db: AsyncMock) -> None:
    """Unknown email raises the same InvalidCredentialsError as wrong password.

    This prevents an attacker from discovering whether an email is registered.
    """
    with (
        patch(
            "app.services.auth_service.UserRepository.get_by_email",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new_callable=AsyncMock,
        ),
    ):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.login_user(
                db,
                email="ghost@example.com",
                password="Password1",
            )


# ---------------------------------------------------------------------------
# refresh_tokens
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_tokens_success(db: AsyncMock) -> None:
    """A valid refresh token produces a new access + refresh token pair."""
    user_id = uuid.uuid4()
    stored = _make_refresh_token(user_id=user_id)

    raw_token = "valid_raw_token"

    with (
        patch(
            "app.services.auth_service.RefreshTokenRepository.get_by_hash",
            new_callable=AsyncMock,
            return_value=stored,
        ),
        patch(
            "app.services.auth_service.RefreshTokenRepository.revoke",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.auth_service.RefreshTokenRepository.create",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new_callable=AsyncMock,
        ),
    ):
        new_access, new_refresh = await auth_service.refresh_tokens(
            db,
            refresh_token_raw=raw_token,
        )

    assert isinstance(new_access, str) and len(new_access) > 0
    assert isinstance(new_refresh, str) and len(new_refresh) > 0


@pytest.mark.asyncio
async def test_refresh_tokens_revoked(db: AsyncMock) -> None:
    """Attempting to refresh with a revoked token raises InvalidCredentialsError."""
    stored = _make_refresh_token(revoked=True)

    with patch(
        "app.services.auth_service.RefreshTokenRepository.get_by_hash",
        new_callable=AsyncMock,
        return_value=stored,
    ):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.refresh_tokens(db, refresh_token_raw="revoked_token")


@pytest.mark.asyncio
async def test_refresh_tokens_expired(db: AsyncMock) -> None:
    """Attempting to refresh with an expired token raises InvalidCredentialsError."""
    stored = _make_refresh_token(expired=True)

    with patch(
        "app.services.auth_service.RefreshTokenRepository.get_by_hash",
        new_callable=AsyncMock,
        return_value=stored,
    ):
        with pytest.raises(InvalidCredentialsError):
            await auth_service.refresh_tokens(db, refresh_token_raw="expired_token")


# ---------------------------------------------------------------------------
# logout_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_success(db: AsyncMock) -> None:
    """Logout revokes the token and writes an audit log entry."""
    user_id = uuid.uuid4()
    stored = _make_refresh_token(user_id=user_id)

    revoke_mock = AsyncMock()
    log_mock = AsyncMock()

    with (
        patch(
            "app.services.auth_service.RefreshTokenRepository.get_by_hash",
            new_callable=AsyncMock,
            return_value=stored,
        ),
        patch(
            "app.services.auth_service.RefreshTokenRepository.revoke",
            new=revoke_mock,
        ),
        patch(
            "app.services.auth_service.AuditLogRepository.log",
            new=log_mock,
        ),
    ):
        await auth_service.logout_user(
            db,
            refresh_token_raw="some_raw_token",
            user_id=user_id,
        )

    revoke_mock.assert_awaited_once()
    log_mock.assert_awaited_once()
