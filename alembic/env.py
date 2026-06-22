"""Alembic environment script for NexoBank async migrations.

Key points
----------
- Uses SQLAlchemy's async engine so that migrations run with the same driver
  (asyncpg) as the application — no need for a separate sync connection string.
- Reads ``DATABASE_URL`` from the environment (via ``app.core.config.settings``)
  so secrets are never hard-coded in source control.
- Imports ``app.models.Base`` (which in turn imports all model modules) so
  that Alembic can compare the current DB schema against the ORM metadata and
  auto-generate accurate migration scripts.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# ── Alembic config object — gives access to alembic.ini values ──────────────
config = context.config

# ── Logging ─────────────────────────────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Import application settings and ORM metadata ─────────────────────────────
from app.core.config import settings  # noqa: E402
from app.models import (  # noqa: E402, F401 — registra todas las tablas en Base.metadata
    Account,
    AuditLog,
    Card,
    RefreshToken,
    Transaction,
    User,
)
from app.models.base import Base  # noqa: E402

target_metadata = Base.metadata

# Override the URL in alembic.ini with the one from our settings so we never
# need to hard-code credentials anywhere.
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


# ---------------------------------------------------------------------------
# Offline migrations (no live DB connection)
# ---------------------------------------------------------------------------


def run_migrations_offline() -> None:
    """Run migrations without a live database connection.

    Useful for generating SQL scripts to review or apply manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migrations (async, using asyncpg)
# ---------------------------------------------------------------------------


def do_run_migrations(connection: Connection) -> None:
    """Run migrations inside an existing sync connection context."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations inside a sync wrapper."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # single-use connection for migrations
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migration mode."""
    asyncio.run(run_async_migrations())


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
