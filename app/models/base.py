"""SQLAlchemy declarative base and async database engine / session factory.

All ORM models in ``app/models/`` inherit from ``Base`` defined here.  The
engine and session factory are also created here so they are available as a
single import::

    from app.models.base import Base, engine, AsyncSessionLocal

Design decisions
----------------
- UUIDs as primary keys — avoids leaking sequential IDs and plays nicely with
  distributed inserts.
- ``created_at`` / ``updated_at`` managed by the ORM so every table gets
  consistent audit timestamps without per-model boilerplate.
- ``AsyncAttrs`` mixin from SQLAlchemy 2.0 lets async code ``await`` lazy
  relationships without explicit ``selectinload``.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import settings

# ---------------------------------------------------------------------------
# Async engine
# ---------------------------------------------------------------------------
# ``pool_pre_ping=True`` ensures that stale connections from the pool are
# detected and replaced before a request tries to use them.
engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    # Tune pool size for typical API workloads; override via DATABASE_URL params
    # or by subclassing if needed.
    pool_size=10,
    max_overflow=20,
    echo=not settings.is_production,  # log SQL only in non-production
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # avoid lazy-load errors after commit
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# Declarative base — all models inherit from this
# ---------------------------------------------------------------------------


class Base(AsyncAttrs, DeclarativeBase):
    """Abstract base for every ORM model in NexoBank.

    Provides:
    - ``id``: UUID primary key (generated client-side for predictability in tests).
    - ``created_at``: set once on INSERT via the DB default.
    - ``updated_at``: updated automatically on every UPDATE via ``onupdate``.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
