"""Cryptographic helpers for NexoBank.

Responsibilities:
- Password hashing / verification with Argon2 (via passlib).
- JWT creation and decoding for access tokens.
- Refresh token generation — the raw token is returned to the client while
  only its SHA-256 hash is stored in the database, so a leaked DB snapshot
  cannot be replayed.
- Generic token hashing utility (SHA-256).

Nothing in this module logs credentials or full token values.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# ---------------------------------------------------------------------------
# Passlib context — Argon2 as the primary scheme, bcrypt as deprecated fallback
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["argon2", "bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# JWT algorithm
# ---------------------------------------------------------------------------
_ALGORITHM = "HS256"


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """Return an Argon2 hash of *password* suitable for database storage."""
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*; False otherwise."""
    return bool(_pwd_context.verify(plain, hashed))


# ---------------------------------------------------------------------------
# Access token
# ---------------------------------------------------------------------------


def create_access_token(
    subject: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Encode a JWT access token whose ``sub`` claim is *subject*.

    Args:
        subject: Typically the user's UUID as a string.
        expires_delta: Override the default expiry from settings.

    Returns:
        A signed JWT string.
    """
    if expires_delta is None:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    expire = datetime.now(UTC) + expires_delta
    payload: dict[str, str | datetime] = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(UTC),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    """Decode *token* and return the ``sub`` claim, or None if invalid/expired.

    Never raises — callers receive None on any validation failure so they can
    return HTTP 401 without leaking details about why verification failed.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])
        token_type: str | None = payload.get("type")
        if token_type != "access":
            return None
        sub: str | None = payload.get("sub")
        return sub
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Refresh token
# ---------------------------------------------------------------------------


def create_refresh_token(subject: str) -> tuple[str, str]:
    """Generate a refresh token pair for *subject*.

    Returns:
        ``(token_raw, token_hash)`` where:
        - ``token_raw`` — the opaque random token sent to the client.
        - ``token_hash`` — the SHA-256 hex digest stored in the database.

    The raw token is never stored server-side; only the hash is persisted so
    that a database breach does not expose live refresh tokens.
    """
    token_raw = secrets.token_urlsafe(64)
    token_hash = hash_token(token_raw)
    return token_raw, token_hash


# ---------------------------------------------------------------------------
# Generic token hashing (SHA-256)
# ---------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of *token*.

    Used to transform any opaque token (e.g. refresh tokens, email
    verification tokens) into a value that can be safely stored in the DB.
    """
    return hashlib.sha256(token.encode()).hexdigest()
