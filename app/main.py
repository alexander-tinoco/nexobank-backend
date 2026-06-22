"""NexoBank FastAPI application entry point.

This module wires together all the application-level concerns:
- Lifespan context (database connection pool startup/shutdown).
- CORS configuration.
- Request-ID middleware (injects ``X-Request-ID`` on every request/response).
- Global rate limiting via slowapi.
- Domain exception handlers.
- API routers mounted under ``/api/v1/``.
- Health-check endpoint at ``GET /health``.

Application startup and shutdown happen inside the ``lifespan`` async context
manager so that resources are properly acquired before the first request and
released after the last one.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.v1.routers import (
    accounts,
    auth,
    cards,
    internal,
    transactions,
    transfers,
    users,
    websockets,
)
from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.rate_limit import limiter
from app.models.base import engine

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown logic
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle resources.

    Startup:
    - Configure structured logging.
    - Verify the database connection pool is reachable.

    Shutdown:
    - Dispose the async engine (closes all pooled connections).
    """
    setup_logging()
    logger.info("NexoBank API starting up", extra={"environment": settings.ENVIRONMENT})

    # Verify DB connectivity early so a misconfiguration surfaces at startup
    # rather than on the first request.
    try:
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("Database connection pool ready")
    except Exception as exc:
        logger.error("Failed to connect to database at startup", extra={"error": str(exc)})
        raise

    yield  # application is running

    logger.info("NexoBank API shutting down")
    await engine.dispose()


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(
        title="NexoBank API",
        description="Digital banking backend API",
        version="1.0.0",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── Rate limiter ─────────────────────────────────────────────────────────
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # ── CORS ─────────────────────────────────────────────────────────────────
    # In production, restrict ``allow_origins`` to the actual frontend domain.
    origins = ["*"] if not settings.is_production else []
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request-ID middleware ─────────────────────────────────────────────────
    @app.middleware("http")
    async def inject_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Ensure every request carries an ``X-Request-ID`` header.

        If the client sends one it is re-used; otherwise a fresh UUID is
        generated.  The ID is echoed back in the response header so clients
        can correlate logs.
        """
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        # Attach to request state so downstream code (e.g. exception handlers)
        # can read it without re-parsing the header.
        request.state.request_id = request_id

        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # ── Domain exception handlers ─────────────────────────────────────────────
    register_exception_handlers(app)

    # ── Routers ──────────────────────────────────────────────────────────────
    _API_PREFIX = "/api/v1"
    app.include_router(auth.router, prefix=_API_PREFIX)
    app.include_router(users.router, prefix=_API_PREFIX)
    app.include_router(accounts.router, prefix=_API_PREFIX)
    app.include_router(cards.router, prefix=_API_PREFIX)
    app.include_router(transactions.router, prefix=_API_PREFIX)
    app.include_router(transfers.router, prefix=_API_PREFIX)
    app.include_router(websockets.router, prefix=_API_PREFIX)
    app.include_router(internal.router, prefix=_API_PREFIX)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health", tags=["ops"], summary="Health check")
    async def health() -> dict[str, str]:
        """Return the current health status and active environment."""
        return {"status": "ok", "environment": settings.ENVIRONMENT}

    return app


# ---------------------------------------------------------------------------
# Module-level app instance — used by uvicorn and tests
# ---------------------------------------------------------------------------
app = create_app()
