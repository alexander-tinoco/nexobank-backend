"""FastAPI dependency injection helpers shared across all v1 routers.

Concrete dependencies
---------------------
``get_db``
    Yields an ``AsyncSession`` per request; rolls back and closes on error.

``get_current_user``
    Reads the ``Authorization: Bearer <token>`` header, decodes the JWT, and
    fetches the corresponding ``User`` from the database.  Raises HTTP 401 on
    any authentication failure.

``get_current_active_user``
    Wraps ``get_current_user`` and raises HTTP 403 if the account is inactive.

``verify_internal_api_key``
    Validates the ``X-Internal-API-Key`` header for machine-to-machine
    endpoints under ``/internal/*``.

Circular import note
--------------------
The ``User`` model is imported inside the function body (or under
``TYPE_CHECKING``) to prevent a circular import between ``deps.py`` and the
model modules that may themselves import from ``app.core``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.models.base import AsyncSessionLocal

if TYPE_CHECKING:
    # Imported only for type-checking; not executed at runtime to avoid cycles.
    from app.models.user import User  # noqa: F401


_bearer_scheme = HTTPBearer(auto_error=True)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an ``AsyncSession`` for the duration of a single request.

    The session is rolled back and closed if an exception propagates; it is
    committed (implicitly, via ``expire_on_commit=False``) by the caller.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the JWT and return the authenticated ``User`` record.

    Raises ``HTTP 401`` if:
    - The token is missing, malformed, or expired.
    - The ``sub`` claim does not correspond to any user in the database.
    """
    # Inline import to avoid circular dependency at module load time.
    from app.models.user import User  # noqa: PLC0415

    subject = decode_access_token(credentials.credentials)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user: User | None = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ---------------------------------------------------------------------------
# Active user guard
# ---------------------------------------------------------------------------


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Return *current_user* only if the account is active.

    Raises ``HTTP 403`` for inactive / suspended accounts so that the client
    can distinguish "not authenticated" (401) from "authenticated but banned"
    (403).
    """
    if not current_user.is_active:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Internal API key
# ---------------------------------------------------------------------------


async def verify_internal_api_key(
    api_key: str = Header(..., alias="X-Internal-API-Key"),
) -> None:
    """Validate the shared secret used by internal services.

    This dependency is **not** meant for user-facing endpoints.  It enforces a
    static API key (from ``settings.INTERNAL_API_KEY``) on all
    ``/internal/*`` routes so that they are inaccessible without the key.

    Raises ``HTTP 403`` on mismatch — using 403 instead of 401 because these
    endpoints do not use the ``Bearer`` scheme.
    """
    if api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal API key.",
        )
