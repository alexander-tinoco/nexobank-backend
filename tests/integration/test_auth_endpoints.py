"""Integration tests for the auth and users API endpoints.

These tests run against a real (test) PostgreSQL database via the ``async_client``
fixture from ``tests/conftest.py``.  Each test function gets a fresh DB transaction
that is rolled back after the test completes.

Prerequisites
-------------
A running PostgreSQL instance accessible at ``TEST_DATABASE_URL``
(default: ``postgresql+asyncpg://user:password@localhost:5432/nexobank_test``).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REGISTER_URL = "/api/v1/auth/register"
_LOGIN_URL = "/api/v1/auth/login"
_REFRESH_URL = "/api/v1/auth/refresh"
_LOGOUT_URL = "/api/v1/auth/logout"
_ME_URL = "/api/v1/users/me"


async def _register(
    client: AsyncClient,
    *,
    email: str = "test@nexobank.io",
    password: str = "Password1",
    full_name: str = "Test User",
) -> dict[str, str]:
    """Register a new user and return the parsed JSON response."""
    resp = await client.post(
        _REGISTER_URL,
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Full register → login → /me flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_and_login_flow(async_client: AsyncClient) -> None:
    """A newly registered user can log in and access /users/me."""
    tokens = await _register(async_client, email="flow@nexobank.io")
    assert "access_token" in tokens
    assert "refresh_token" in tokens
    assert tokens["token_type"] == "bearer"

    # Login with the same credentials
    login_resp = await async_client.post(
        _LOGIN_URL,
        json={"email": "flow@nexobank.io", "password": "Password1"},
    )
    assert login_resp.status_code == 200
    login_tokens = login_resp.json()
    access_token = login_tokens["access_token"]

    # Access /users/me with the access token
    me_resp = await async_client.get(
        _ME_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "flow@nexobank.io"
    assert "password_hash" not in me_data


# ---------------------------------------------------------------------------
# Rate limiting on /login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_rate_limit(async_client: AsyncClient) -> None:
    """More than 5 login attempts per minute from the same IP returns 429."""
    # Register the user first so login attempts can proceed normally
    await _register(async_client, email="ratelimit@nexobank.io")

    responses = []
    for _ in range(6):
        r = await async_client.post(
            _LOGIN_URL,
            json={"email": "ratelimit@nexobank.io", "password": "Password1"},
        )
        responses.append(r.status_code)

    # At least one request should have been rate-limited
    assert 429 in responses, f"Expected a 429 in: {responses}"


# ---------------------------------------------------------------------------
# Refresh token rotation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_token_rotation(async_client: AsyncClient) -> None:
    """Using a refresh token issues a new pair; the old refresh token is then invalid."""
    tokens = await _register(async_client, email="rotation@nexobank.io")
    original_refresh = tokens["refresh_token"]

    # Use the refresh token once
    refresh_resp = await async_client.post(
        _REFRESH_URL,
        json={"refresh_token": original_refresh},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    new_access = new_tokens["access_token"]
    new_refresh = new_tokens["refresh_token"]

    # New tokens work
    me_resp = await async_client.get(
        _ME_URL,
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me_resp.status_code == 200

    # Old refresh token is now revoked — must return 401
    reuse_resp = await async_client.post(
        _REFRESH_URL,
        json={"refresh_token": original_refresh},
    )
    assert reuse_resp.status_code == 401

    # Clean up: revoke new token too
    await async_client.post(
        _REFRESH_URL,
        json={"refresh_token": new_refresh},
    )


# ---------------------------------------------------------------------------
# Logout invalidates the refresh token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_invalidates_refresh_token(async_client: AsyncClient) -> None:
    """After logout, the refresh token can no longer be used to obtain new tokens."""
    tokens = await _register(async_client, email="logout@nexobank.io")
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # Log out (revokes the refresh token)
    logout_resp = await async_client.post(
        _LOGOUT_URL,
        json={"refresh_token": refresh_token},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert logout_resp.status_code == 204

    # Trying to refresh with the revoked token must fail
    refresh_resp = await async_client.post(
        _REFRESH_URL,
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 401
