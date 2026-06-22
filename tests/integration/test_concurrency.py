"""Concurrency integration test — verifies SELECT … FOR UPDATE prevents double-spend.

This test is MANDATORY per CLAUDE.md rule 6 and the project brief.

WHY this test exists
--------------------
The ``SELECT ... FOR UPDATE`` guard in ``_lock_accounts_for_update`` is the
key mechanism that prevents a race condition where two concurrent requests both
read the same balance, both see enough funds, and both proceed — resulting in a
negative balance (double spend).

This test simulates exactly that scenario with two concurrent HTTP requests:
- Account A starts with 1000 MXN.
- Two simultaneous transfers of 600 MXN each are attempted.
- Only one should succeed (600 ≤ 1000); the other must get 422 INSUFFICIENT_FUNDS.
- The final balance must be exactly 400 (not 0 or negative).

Running this test
-----------------
Requires a real PostgreSQL instance (concurrent connections needed).
asyncio.gather is used to launch both HTTP requests simultaneously.

    TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost/nexobank_test \\
        pytest tests/integration/test_concurrency.py -v -s

Note: This test depends on the Account and User models being available
(Phase 3 integration).
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

pytest.importorskip("app.models.account", reason="Account model not yet available")
pytest.importorskip("app.models.user", reason="User model not yet available")


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_transfers.py to keep tests self-contained)
# ---------------------------------------------------------------------------


async def _create_user(db: AsyncSession) -> Any:
    from app.models.user import User  # noqa: PLC0415

    user = User(
        email=f"user-{uuid.uuid4()}@test.com",
        full_name="Concurrency Tester",
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
) -> Any:
    from app.models.account import Account, AccountStatus  # noqa: PLC0415

    account = Account(
        user_id=user_id,
        balance=balance,
        currency=currency,
        status=AccountStatus.active,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


def _auth_headers(user: Any) -> dict[str, str]:
    from app.core.security import create_access_token  # noqa: PLC0415

    token = create_access_token(subject=str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_transfers_no_double_spend(
    async_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Two simultaneous transfers of 600 from a 1000-balance account.

    Exactly one must succeed and one must fail with 422.
    The final balance must be 400.00 (not negative — no double spend).

    This test validates that ``SELECT ... FOR UPDATE`` in
    ``_lock_accounts_for_update`` correctly serialises concurrent writes.
    Without the lock, both requests could read balance=1000, both pass the
    ``balance >= amount`` check, and both deduct 600 — leaving -200.
    """
    # Setup: user A (owner) with 1000 MXN, user B (recipient) with 0 MXN
    user_a = await _create_user(db_session)
    user_b = await _create_user(db_session)
    account_a = await _create_account(db_session, user_id=user_a.id, balance=Decimal("1000.00"))
    account_b = await _create_account(db_session, user_id=user_b.id, balance=Decimal("0.00"))

    # Commit the setup so both concurrent requests see the same initial state
    await db_session.commit()

    auth = _auth_headers(user_a)

    async def do_transfer(key: str) -> Response:
        payload = {
            "from_account_id": str(account_a.id),
            "to_account_id": str(account_b.id),
            "amount": "600.00",
            "currency": "MXN",
            "idempotency_key": key,  # different keys to avoid idempotency short-circuit
        }
        return await async_client.post(
            "/api/v1/transfers",
            json=payload,
            headers=auth,
        )

    # Fire both requests concurrently
    r1, r2 = await asyncio.gather(
        do_transfer(key=str(uuid.uuid4())),
        do_transfer(key=str(uuid.uuid4())),
    )

    statuses = {r1.status_code, r2.status_code}

    # Exactly one success (201) and one failure (422)
    assert 201 in statuses, (
        f"Expected one 201 but got statuses: {r1.status_code}, {r2.status_code}"
    )
    assert 422 in statuses, (
        f"Expected one 422 but got statuses: {r1.status_code}, {r2.status_code}"
    )

    # Verify the 422 is specifically INSUFFICIENT_FUNDS (not another error)
    failed_response = r1 if r1.status_code == 422 else r2
    assert failed_response.json().get("error_code") == "INSUFFICIENT_FUNDS", (
        f"422 body was: {failed_response.text}"
    )

    # Final balance check — must be exactly 400 (1000 - 600), never negative
    await db_session.refresh(account_a)
    assert account_a.balance == Decimal("400.00"), (
        f"Expected final balance of 400.00 but got {account_a.balance}. "
        "This indicates a double-spend race condition — SELECT FOR UPDATE may not be working."
    )
