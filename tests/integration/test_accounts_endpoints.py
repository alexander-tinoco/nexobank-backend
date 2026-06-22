"""Integration tests for account and card endpoints.

These tests exercise the full request/response cycle through the FastAPI app
but override the authentication dependency so they do not depend on a real User
model being available (the User model is owned by another module).

The database is a real PostgreSQL instance (see ``tests/conftest.py``).

Test coverage
-------------
- POST /api/v1/accounts                         → 201 Created
- GET  /api/v1/accounts                         → 200 list
- GET  /api/v1/accounts/{id}                    → 200 detail
- POST /api/v1/accounts/{id}/cards              → 201 Created
- PATCH /api/v1/cards/{id}/freeze               → 200 freeze / unfreeze
- GET  /api/v1/accounts/{id} by non-owner       → 403 Forbidden
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_current_active_user, get_db
from app.main import app

# ---------------------------------------------------------------------------
# Fake user — returned by the overridden dependency
# ---------------------------------------------------------------------------


def _make_fake_user(user_id: uuid.UUID) -> Any:
    """Return a minimal object that satisfies the User interface used in routers."""
    user = MagicMock()
    user.id = user_id
    user.is_active = True
    return user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def authenticated_client(
    db_session: AsyncSession,
) -> AsyncGenerator[tuple[AsyncClient, uuid.UUID], None]:
    """Yield (client, user_id) with auth dependency overridden to a fake user."""
    user_id = uuid.uuid4()
    fake_user = _make_fake_user(user_id)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _override_get_current_active_user() -> Any:
        return fake_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_active_user] = _override_get_current_active_user

    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as client:
        yield client, user_id

    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def second_user_client(
    db_session: AsyncSession,
) -> AsyncGenerator[tuple[AsyncClient, uuid.UUID], None]:
    """Yield (client, user_id) for a *second* user — used to test ownership checks."""
    user_id = uuid.uuid4()
    fake_user = _make_fake_user(user_id)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _override_get_current_active_user() -> Any:
        return fake_user

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_active_user] = _override_get_current_active_user

    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as client:
        yield client, user_id

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests: accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_account_and_list(
    authenticated_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    """Creating an account returns 201; listing accounts includes the new account."""
    client, _user_id = authenticated_client

    # Create a checking account in MXN
    create_resp = await client.post(
        "/api/v1/accounts",
        json={"currency": "MXN", "type": "checking"},
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    assert created["currency"] == "MXN"
    assert created["type"] == "checking"
    assert created["status"] == "active"
    assert created["balance"] == "0.00"
    assert "id" in created
    assert "account_number" in created

    # Listing should include the new account
    list_resp = await client.get("/api/v1/accounts")
    assert list_resp.status_code == 200, list_resp.text
    body = list_resp.json()
    assert body["total"] >= 1
    account_ids = [a["id"] for a in body["items"]]
    assert created["id"] in account_ids


@pytest.mark.asyncio
async def test_get_account_detail(
    authenticated_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    """GET /accounts/{id} returns the full account detail."""
    client, _user_id = authenticated_client

    create_resp = await client.post(
        "/api/v1/accounts",
        json={"currency": "USD", "type": "savings"},
    )
    assert create_resp.status_code == 201
    account_id = create_resp.json()["id"]

    detail_resp = await client.get(f"/api/v1/accounts/{account_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert detail["id"] == account_id
    assert detail["currency"] == "USD"
    assert detail["type"] == "savings"


@pytest.mark.asyncio
async def test_create_account_unsupported_currency(
    authenticated_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    """POST /accounts with an unsupported currency returns 422."""
    client, _user_id = authenticated_client

    resp = await client.post(
        "/api/v1/accounts",
        json={"currency": "EUR", "type": "checking"},
    )
    # Could be 422 from Pydantic validator or from service UnsupportedCurrencyError
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Tests: cards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_card_and_freeze_unfreeze(
    authenticated_client: tuple[AsyncClient, uuid.UUID],
) -> None:
    """Creating a card, then freezing and unfreezing it returns expected statuses."""
    client, _user_id = authenticated_client

    # First create an account
    acc_resp = await client.post(
        "/api/v1/accounts",
        json={"currency": "MXN", "type": "checking"},
    )
    assert acc_resp.status_code == 201
    account_id = acc_resp.json()["id"]

    # Issue a debit card
    card_resp = await client.post(
        f"/api/v1/accounts/{account_id}/cards",
        json={"type": "debit"},
    )
    assert card_resp.status_code == 201, card_resp.text
    card = card_resp.json()
    assert card["type"] == "debit"
    assert card["status"] == "active"
    assert len(card["last4"]) == 4
    assert "expires_at" in card
    card_id = card["id"]

    # List cards for the account
    list_resp = await client.get(f"/api/v1/accounts/{account_id}/cards")
    assert list_resp.status_code == 200
    cards = list_resp.json()
    assert any(c["id"] == card_id for c in cards)

    # Freeze the card
    freeze_resp = await client.patch(
        f"/api/v1/cards/{card_id}/freeze",
        json={"frozen": True},
    )
    assert freeze_resp.status_code == 200, freeze_resp.text
    assert freeze_resp.json()["status"] == "frozen"

    # Unfreeze the card
    unfreeze_resp = await client.patch(
        f"/api/v1/cards/{card_id}/freeze",
        json={"frozen": False},
    )
    assert unfreeze_resp.status_code == 200, unfreeze_resp.text
    assert unfreeze_resp.json()["status"] == "active"


# ---------------------------------------------------------------------------
# Tests: ownership checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cannot_access_another_users_account(
    authenticated_client: tuple[AsyncClient, uuid.UUID],
    db_session: AsyncSession,
) -> None:
    """A user cannot access another user's account — expects 403."""
    client_a, _user_id_a = authenticated_client

    # User A creates an account
    acc_resp = await client_a.post(
        "/api/v1/accounts",
        json={"currency": "MXN", "type": "checking"},
    )
    assert acc_resp.status_code == 201
    account_id = acc_resp.json()["id"]

    # User B tries to access user A's account using a separate client
    user_b_id = uuid.uuid4()
    fake_user_b = _make_fake_user(user_b_id)

    async def _override_get_db_b() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _override_user_b() -> Any:
        return fake_user_b

    app.dependency_overrides[get_db] = _override_get_db_b
    app.dependency_overrides[get_current_active_user] = _override_user_b

    from httpx import ASGITransport

    async with AsyncClient(
        transport=ASGITransport(app=app),  # type: ignore[arg-type]
        base_url="http://testserver",
    ) as client_b:
        resp = await client_b.get(f"/api/v1/accounts/{account_id}")

    # Restore original overrides for client_a (already yielded)
    app.dependency_overrides.clear()

    assert resp.status_code == 403, resp.text
