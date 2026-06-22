"""Integration tests for the transfers endpoint.

These tests require a real PostgreSQL instance (nexobank_test database).
They depend on the Account and User models being available — run them after
Phase 3 integration when all modules are merged.

To run locally:
    TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost/nexobank_test \\
        pytest tests/integration/test_transfers.py -v

Test isolation
--------------
Each test uses the ``db_session`` fixture from ``conftest.py``, which wraps
the test in a transaction that is rolled back on teardown.  This means the DB
is always in a clean state — no manual truncation needed.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

# These imports resolve after Phase 3 integration (Account + User agents done)
# Mark the whole module to skip if the models are not yet available.
pytest.importorskip("app.models.account", reason="Account model not yet available")
pytest.importorskip("app.models.user", reason="User model not yet available")


# ---------------------------------------------------------------------------
# Helpers — create fixture data directly in the DB
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession) -> Any:
    """Insert a minimal User row and return it."""
    from app.models.user import User  # noqa: PLC0415

    user = User(
        email=f"user-{uuid.uuid4()}@test.com",
        full_name="Test User",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$fake",
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _create_account(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    balance: Decimal = Decimal("1000.00"),
    currency: str = "MXN",
    status: str = "active",
) -> Any:
    """Insert an Account row and return it."""
    from app.models.account import Account, AccountStatus  # noqa: PLC0415

    account = Account(
        user_id=user_id,
        balance=balance,
        currency=currency,
        status=AccountStatus(status),
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


def _auth_headers(user: Any) -> dict[str, str]:
    """Return a Bearer token header for *user* using the test JWT factory."""
    from app.core.security import create_access_token  # noqa: PLC0415

    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_transfer_flow(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Happy path: transfer 500 MXN, verify both account balances in the DB."""
    user_a = await _create_user(db_session)
    user_b = await _create_user(db_session)
    account_a = await _create_account(db_session, user_id=user_a.id, balance=Decimal("1000.00"))
    account_b = await _create_account(db_session, user_id=user_b.id, balance=Decimal("0.00"))

    payload = {
        "from_account_id": str(account_a.id),
        "to_account_id": str(account_b.id),
        "amount": "500.00",
        "currency": "MXN",
        "idempotency_key": str(uuid.uuid4()),
        "description": "Test transfer",
    }

    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers=_auth_headers(user_a),
    )

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["type"] == "transfer_out"
    assert Decimal(data["amount"]) == Decimal("500.00")

    # Refresh accounts and verify balances
    await db_session.refresh(account_a)
    await db_session.refresh(account_b)
    assert account_a.balance == Decimal("500.00")
    assert account_b.balance == Decimal("500.00")


@pytest.mark.asyncio
async def test_idempotent_transfer(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Same idempotency key → same response, saldo changes only once."""
    user_a = await _create_user(db_session)
    user_b = await _create_user(db_session)
    account_a = await _create_account(db_session, user_id=user_a.id, balance=Decimal("1000.00"))
    account_b = await _create_account(db_session, user_id=user_b.id, balance=Decimal("0.00"))

    idempotency_key = str(uuid.uuid4())
    payload = {
        "from_account_id": str(account_a.id),
        "to_account_id": str(account_b.id),
        "amount": "300.00",
        "currency": "MXN",
        "idempotency_key": idempotency_key,
    }

    r1 = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers=_auth_headers(user_a),
    )
    r2 = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers=_auth_headers(user_a),
    )

    assert r1.status_code == 201, r1.text
    assert r2.status_code == 201, r2.text
    # Both responses should return the same transaction id
    assert r1.json()["id"] == r2.json()["id"]

    # Balance should only have changed once
    await db_session.refresh(account_a)
    assert account_a.balance == Decimal("700.00"), (
        f"Expected 700.00 but got {account_a.balance} — transfer was applied twice"
    )


@pytest.mark.asyncio
async def test_transfer_insufficient_funds_returns_422(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Transferring more than the available balance returns HTTP 422."""
    user_a = await _create_user(db_session)
    user_b = await _create_user(db_session)
    account_a = await _create_account(db_session, user_id=user_a.id, balance=Decimal("100.00"))
    account_b = await _create_account(db_session, user_id=user_b.id, balance=Decimal("0.00"))

    payload = {
        "from_account_id": str(account_a.id),
        "to_account_id": str(account_b.id),
        "amount": "500.00",
        "currency": "MXN",
        "idempotency_key": str(uuid.uuid4()),
    }

    response = await async_client.post(
        "/api/v1/transfers",
        json=payload,
        headers=_auth_headers(user_a),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error_code"] == "INSUFFICIENT_FUNDS"


@pytest.mark.asyncio
async def test_transfer_requires_auth(async_client: AsyncClient) -> None:
    """Attempting a transfer without an Authorization header returns HTTP 403 or 401."""
    payload = {
        "from_account_id": str(uuid.uuid4()),
        "to_account_id": str(uuid.uuid4()),
        "amount": "100.00",
        "currency": "MXN",
        "idempotency_key": str(uuid.uuid4()),
    }

    response = await async_client.post("/api/v1/transfers", json=payload)
    assert response.status_code in (401, 403), response.text
