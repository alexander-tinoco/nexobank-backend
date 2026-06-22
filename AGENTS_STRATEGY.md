# Estrategia de agentes en paralelo — NexoBank Backend

## Resumen

El desarrollo se divide en 3 fases. Las fases 1 y 3 usan un solo agente (bloqueantes). La fase 2 usa 3-4 agentes en paralelo, cada uno en su propia rama de git (worktree aislado) para evitar conflictos.

---

## Fase 1 — Fundación (1 agente, bloqueante)

Debe completarse antes de lanzar la Fase 2. Produce todos los archivos compartidos.

**Entregables:**
- `pyproject.toml` + `requirements.txt`
- `Dockerfile` + `docker-compose.yml` (app + Postgres + Redis + Celery worker)
- `app/core/config.py` — variables de entorno con `pydantic-settings`
- `app/core/security.py` — hashing Argon2 + JWT (access 15 min + refresh rotativo)
- `app/core/logging.py` — logging estructurado (JSON)
- `app/core/exceptions.py` — excepciones de dominio (`InsufficientFundsError`, `AccountNotFoundError`, `CardNotFoundError`, `UnauthorizedError`, `DuplicateTransactionError`)
- `app/core/exception_handlers.py` — handler central → HTTP `{"error_code", "message", "request_id"}`
- `app/models/base.py` — clase base SQLAlchemy async con `id` (UUID), `created_at`, `updated_at`
- `app/api/v1/deps.py` — dependencias compartidas (sesión DB async, usuario autenticado, API key interna)
- `app/main.py` — app FastAPI con lifespan, CORS, rate limiting global, routers registrados (stubs)
- `alembic/` — setup completo (`alembic.ini`, `env.py` async-compatible)
- `tests/conftest.py` — fixtures base (BD de test con Docker, cliente HTTP async)

---

## Fase 2 — Módulos en paralelo (lanzar todos a la vez)

Cada agente trabaja en rama propia. Los archivos están particionados sin solapamiento.

### Agente A — Auth
| Capa | Archivos |
|------|----------|
| Model | `app/models/user.py`, `app/models/refresh_token.py` |
| Schema | `app/schemas/auth.py`, `app/schemas/user.py` |
| Repository | `app/repositories/user_repository.py` |
| Service | `app/services/auth_service.py` |
| Router | `app/api/v1/routers/auth.py` |
| Tests | `tests/unit/test_auth_service.py`, `tests/integration/test_auth_endpoints.py` |
| Migración | `alembic/versions/001_users_refresh_tokens.py` |

**Endpoints:** `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`

### Agente B — Accounts & Cards
| Capa | Archivos |
|------|----------|
| Model | `app/models/account.py`, `app/models/card.py` |
| Schema | `app/schemas/account.py`, `app/schemas/card.py` |
| Repository | `app/repositories/account_repository.py`, `app/repositories/card_repository.py` |
| Service | `app/services/account_service.py`, `app/services/card_service.py` |
| Router | `app/api/v1/routers/accounts.py`, `app/api/v1/routers/cards.py` |
| Tests | `tests/unit/test_account_service.py`, `tests/unit/test_card_service.py`, `tests/integration/test_accounts_endpoints.py` |
| Migración | `alembic/versions/002_accounts_cards.py` |

**Endpoints:** `GET/POST /accounts`, `GET /accounts/{id}`, `GET /accounts/{id}/cards`, `POST /accounts/{id}/cards`, `PATCH /cards/{id}/freeze`

### Agente C — Transactions & AuditLog
| Capa | Archivos |
|------|----------|
| Model | `app/models/transaction.py`, `app/models/audit_log.py` |
| Schema | `app/schemas/transaction.py` |
| Repository | `app/repositories/transaction_repository.py`, `app/repositories/audit_log_repository.py` |
| Service | `app/services/transaction_service.py` |
| Router | `app/api/v1/routers/transactions.py` |
| Tests | `tests/unit/test_transaction_service.py`, `tests/integration/test_transfers.py`, `tests/integration/test_concurrency.py` |
| Migración | `alembic/versions/003_transactions_audit_logs.py` |

**Endpoints:** `GET /accounts/{id}/transactions` (cursor pagination), `POST /transfers` (con idempotency key + SELECT FOR UPDATE)

### Agente D — Async & Tiempo real
| Capa | Archivos |
|------|----------|
| Workers | `app/workers/celery_app.py`, `app/workers/notification_tasks.py`, `app/workers/risk_tasks.py`, `app/workers/cleanup_tasks.py` |
| Router | `app/api/v1/routers/websockets.py`, `app/api/v1/routers/internal.py` |
| Tests | `tests/unit/test_celery_tasks.py` |

**Endpoints:** `WS /ws/notifications`, `GET /internal/users/{id}/context`, `POST /internal/risk-events`

---

## Fase 3 — Integración (1 agente, después de que terminen los 4)

1. Merge de las 4 ramas al main
2. Conectar routers en `main.py`
3. Consolidar y ordenar migraciones Alembic
4. Correr `ruff`, `mypy`, `pytest --cov` y corregir fallos
5. Verificar checklist de seguridad del `CLAUDE.md`

---

## Reglas para todos los agentes (del CLAUDE.md)

- Nunca `float` para dinero → siempre `Decimal` / `Numeric(18,2)`
- Nunca mutar `Transaction` → solo append + reverso
- Nunca loguear contraseñas, tokens completos, CVV, `password_hash`
- Toda operación sensible → `AuditLog`
- Escrituras concurrentes de saldo → `SELECT ... FOR UPDATE`
- Lógica de negocio solo en `services/`, nunca en routers ni repositories
- Acceso a BD solo en `repositories/`, nunca directo desde `services/` o `api/`
- Pydantic v2 para todos los schemas, nunca devolver modelos SQLAlchemy directo
- Excepciones de dominio propias, nunca `HTTPException` dentro de `services/`
- Toda migración tiene `downgrade()` implementado

---

## Orden de lanzamiento

```
[Ahora]     Fase 1: 1 agente (fundación)
[Tras merge] Fase 2: 4 agentes en paralelo (dominios)
[Tras merge] Fase 3: 1 agente (integración + hardening)
```
