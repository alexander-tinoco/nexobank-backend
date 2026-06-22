# NexoBank Backend

Digital banking API built with FastAPI, PostgreSQL, Redis, and Celery. Designed as a portfolio project with production-grade standards: strict type safety, append-only ledger, concurrency-safe transfers, and a layered architecture ready for AI agent integration.

## Tech Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115+ (async, Pydantic v2) |
| Database | PostgreSQL 16 via SQLAlchemy 2.0 async + asyncpg |
| Migrations | Alembic |
| Cache / broker | Redis 7 |
| Background jobs | Celery 5 (worker + beat scheduler) |
| Auth | Argon2 password hashing, JWT access tokens (15 min) + rotating refresh tokens |
| Rate limiting | slowapi (Redis-backed) |
| Testing | pytest + pytest-asyncio + httpx, real PostgreSQL (no SQLAlchemy mocks) |
| Lint / types | ruff + mypy (strict, zero `# type: ignore`) |
| CI | GitHub Actions |

## Architecture

```
Mobile app / AI agents / analytics
             │
             ▼
   ┌─────────────────────┐
   │    API layer         │  routers, Pydantic schemas, auth deps
   │  app/api/v1/         │
   └─────────────────────┘
             │
             ▼
   ┌─────────────────────┐
   │    Service layer     │  business logic, domain exceptions
   │  app/services/       │
   └─────────────────────┘
             │
             ▼
   ┌─────────────────────┐
   │  Repository layer    │  data access, SQLAlchemy queries
   │  app/repositories/   │
   └─────────────────────┘
             │
             ▼
   ┌────────────────────────────┐
   │  PostgreSQL 16 · Redis 7   │
   └────────────────────────────┘
              ▲
   ┌──────────┴──────────┐
   │   Celery workers     │  notifications, risk evaluation, token cleanup
   │  app/workers/        │
   └─────────────────────┘
```

No business logic lives in routers. No SQLAlchemy access from services. Domain exceptions are raised in services and translated to HTTP status codes by a central handler — never raw `HTTPException` inside business logic.

## Project Structure

```
nexobank-backend/
├── app/
│   ├── api/v1/
│   │   ├── routers/        # auth, accounts, cards, transfers, transactions,
│   │   │                   # users, device_tokens, websockets, internal
│   │   └── deps.py         # DB session, current user, internal API key
│   ├── core/
│   │   ├── config.py       # pydantic-settings (typed env vars)
│   │   ├── security.py     # Argon2 hashing, JWT factory
│   │   ├── exceptions.py   # domain exceptions (InsufficientFundsError, …)
│   │   └── exception_handlers.py  # translates domain → HTTP
│   ├── models/             # SQLAlchemy ORM models
│   ├── schemas/            # Pydantic v2 request/response schemas
│   ├── services/           # business logic (use cases)
│   ├── repositories/       # data access layer
│   ├── workers/            # Celery tasks
│   └── main.py             # app factory, middleware, routers
├── alembic/                # schema migrations
├── tests/
│   ├── unit/               # service-layer tests (fast, no real DB)
│   └── integration/        # full request cycle against real PostgreSQL
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

## API Endpoints

All endpoints live under `/api/v1`. Interactive docs at `http://localhost:8000/docs` (development only).

### Auth

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Login, receive JWT access + refresh tokens |
| POST | `/auth/refresh` | Rotate refresh token, get new access token |
| POST | `/auth/logout` | Revoke refresh token |
| POST | `/auth/forgot-password` | Request password reset link |
| POST | `/auth/reset-password` | Complete password reset |

### Users

| Method | Path | Description |
|--------|------|-------------|
| GET | `/users/me` | Get authenticated user's profile |
| PATCH | `/users/me` | Update profile (name, phone) |

### Accounts

| Method | Path | Description |
|--------|------|-------------|
| GET | `/accounts` | List authenticated user's accounts |
| POST | `/accounts` | Open a new account |
| GET | `/accounts/{id}` | Get account detail |
| POST | `/accounts/{id}/deposit` | Deposit funds |

### Cards

| Method | Path | Description |
|--------|------|-------------|
| GET | `/accounts/{id}/cards` | List cards for an account |
| POST | `/accounts/{id}/cards` | Issue a new debit card |
| PATCH | `/cards/{id}/freeze` | Freeze or unfreeze a card |

### Transactions & Transfers

| Method | Path | Description |
|--------|------|-------------|
| GET | `/accounts/{id}/transactions` | Paginated transaction history (cursor-based) |
| POST | `/transfers` | Execute a transfer between two accounts |

`POST /transfers` requires an `idempotency_key` header. Duplicate requests with the same key return the original transaction without re-applying the transfer.

### Notifications

| Method | Path | Description |
|--------|------|-------------|
| POST | `/device-tokens` | Register a push notification token |
| DELETE | `/device-tokens/{token}` | Unregister a device token |
| WS | `/ws/notifications` | Real-time notification stream (Redis pub/sub) |

### Internal (AI agents / services)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/internal/users/{id}/context` | Internal API key | Full user context for AI agents |
| POST | `/internal/risk-events` | Internal API key | Submit a risk event from fraud engine |

Internal endpoints require the `X-Internal-API-Key` header.

### Ops

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |

## Error Format

All errors return a consistent JSON body:

```json
{
  "error_code": "INSUFFICIENT_FUNDS",
  "message": "Insufficient funds: balance is 100.00, attempted to transfer 500.00.",
  "request_id": "a1b2c3d4-..."
}
```

Every response includes an `X-Request-ID` header for log correlation.

## Local Setup

**Prerequisites:** Docker and Docker Compose.

```bash
git clone https://github.com/<you>/nexobank-backend.git
cd nexobank-backend

# Copy and fill environment variables
cp .env.example .env
# Edit .env — at minimum set SECRET_KEY and INTERNAL_API_KEY

# Start everything (app + postgres + redis + celery worker + celery beat)
docker compose up --build
```

The API will be available at `http://localhost:8000`.
Swagger UI: `http://localhost:8000/docs`

To apply database migrations:

```bash
docker compose exec app alembic upgrade head
```

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | asyncpg connection string | — (required) |
| `REDIS_URL` | Redis connection string | — (required) |
| `SECRET_KEY` | JWT signing key (min 32 chars) | — (required) |
| `INTERNAL_API_KEY` | Key for `/internal/*` endpoints | — (required) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT access token TTL | `15` |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Refresh token TTL | `30` |
| `ENVIRONMENT` | `development` or `production` | `development` |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Used by docker-compose | — |

Generate a secret key:

```bash
openssl rand -hex 32
```

## Running Tests

Tests require a running PostgreSQL instance (the test suite runs real queries — no SQLAlchemy mocks):

```bash
# With Docker Compose running:
docker compose exec app pytest -v

# Or locally with TEST_DATABASE_URL pointing at a test database:
TEST_DATABASE_URL=postgresql+asyncpg://user:password@localhost/nexobank_test pytest -v
```

The CI pipeline runs `ruff`, `mypy`, and `pytest` (with PostgreSQL 16 + Redis 7 service containers) on every push.

Current state: **49 tests passing**, **75% coverage**, `ruff` and `mypy` clean.

## Design Decisions

### Money is always `Decimal`

All balances and amounts are stored as `Numeric(18,2)` in PostgreSQL and handled as Python `Decimal`. No `float` anywhere in the codebase.

### Append-only ledger

`Transaction` rows are never updated or deleted. Corrections are applied as reversal transactions. This is the standard accounting pattern and is a hard rule enforced in `CLAUDE.md`.

### Concurrency-safe transfers (`SELECT FOR UPDATE`)

`POST /transfers` locks both account rows with `SELECT ... FOR UPDATE` before reading or modifying balances. Locks are acquired in ascending UUID order to prevent circular deadlocks when two transfers touch the same pair of accounts in opposite directions.

A critical implementation detail: SQLAlchemy's identity map caches the first non-locking read of an Account row. If the ownership pre-check loads the row before the `FOR UPDATE` query runs, SQLAlchemy returns the cached (stale) object and the lock is effectively bypassed. The fix is `.execution_options(populate_existing=True)` on the locking query, which forces SQLAlchemy to overwrite the cached instance with the freshly-locked committed data.

This is verified by a mandatory concurrency test that fires two simultaneous HTTP requests (600 MXN each from a 1000 MXN account) and asserts exactly one 201 and one 422, with a final balance of 400.

### Idempotency keys on transfers

Clients send a unique `idempotency_key` with each transfer request. Duplicate requests return the original transaction without applying the transfer again — safe to retry on network errors.

### Audit log

Every sensitive operation (login, password change, transfer, card freeze/unfreeze) writes an immutable row to `AuditLog` inside the same database transaction. If the main operation rolls back, the audit entry rolls back with it — no phantom audit records.

### Domain exceptions → central HTTP translation

Services raise typed domain exceptions (`InsufficientFundsError`, `AccountNotFoundError`, `UnauthorizedResourceError`, etc.). A central exception handler in `app/core/exception_handlers.py` maps them to the correct HTTP status code and the standard error body. Routers and services never import `HTTPException`.

## Planned Integrations (roadmap)

This backend was designed to be the single source of truth for a multi-layer system:

- **AI Financial Coach** — consumes `/internal/users/{id}/context` to build personalized advice
- **Voice Agent** — calls REST endpoints to execute actions spoken by the user
- **Fraud / scoring engine** — submits risk events via `/internal/risk-events`; Celery's `evaluate_transaction_risk_task` stub is ready to be wired in
- **Analytics / Power BI** — reads from read replicas or a data warehouse fed from the `Transaction` and `AuditLog` tables
- **Mobile app** — Flutter/React Native client consuming this API (in development)

## CI

GitHub Actions pipeline on every push:

1. `ruff check` — lint and format
2. `mypy` — strict type checking
3. `pytest` with PostgreSQL 16 + Redis 7 service containers

See `.github/workflows/ci.yml`.
