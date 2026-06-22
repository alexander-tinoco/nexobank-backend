"""Shared pytest fixtures for NexoBank backend tests.

These fixtures provide:
- ``test_engine``:  An async SQLAlchemy engine pointing at the ``nexobank_test``
  database.  The schema is created fresh at the start of the test session and
  dropped at the end.
- ``async_client``:  An ``httpx.AsyncClient`` wired to the FastAPI app with the
  ``get_db`` dependency overridden to use the test database session.

Requirements
------------
A running PostgreSQL instance (the test DB URL defaults to
``postgresql+asyncpg://user:password@localhost:5432/nexobank_test`` but can be
overridden with the ``TEST_DATABASE_URL`` environment variable).

These fixtures use ``scope="session"`` for the engine (expensive to create) and
``scope="function"`` for the session/client so each test starts clean.
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.api.v1.deps import get_db
from app.main import app
from app.models.base import Base

# ---------------------------------------------------------------------------
# Test database URL
# ---------------------------------------------------------------------------

_DEFAULT_TEST_DB_URL = (
    "postgresql+asyncpg://user:password@localhost:5432/nexobank_test"
)
TEST_DATABASE_URL: str = os.getenv("TEST_DATABASE_URL", _DEFAULT_TEST_DB_URL)


# ---------------------------------------------------------------------------
# Engine — session-scoped (one engine for the whole test run)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create the test database schema and yield the engine.

    Drops and recreates all tables at the start of each test session so
    leftover state from previous runs never bleeds into new tests.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        # Drop and recreate to guarantee a clean slate
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: drop all tables and dispose the pool
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


# ---------------------------------------------------------------------------
# Session factory — derived from the test engine
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
def test_session_factory(
    test_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Return a session factory bound to the test engine."""
    return async_sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


# ---------------------------------------------------------------------------
# Per-test DB session (function scope — rolls back after every test)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def db_session(
    test_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transactional AsyncSession that is rolled back after each test.

    Using ``SAVEPOINT`` (nested transactions) ensures the test is fully isolated
    without needing to truncate tables between tests.
    """
    async with test_session_factory() as session:
        async with session.begin():
            yield session
            await session.rollback()


# ---------------------------------------------------------------------------
# HTTP client — overrides get_db to use the test session
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def async_client(
    db_session: AsyncSession,
) -> AsyncGenerator[AsyncClient, None]:
    """Yield an AsyncClient pointed at the FastAPI app with the test DB injected."""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
