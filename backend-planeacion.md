# Planeación del Backend — NexoBank

**Proyecto:** NexoBank · Portafolio de banco digital con IA
**Capa:** Backend y base de datos
**Perfil objetivo:** Backend Developer / API Engineer
**Duración estimada:** 8 semanas (Mes 1–2), con soporte continuo en meses 3–8

---

## 1. Objetivo de la capa

Construir el núcleo transaccional de NexoBank: una API robusta, segura y escalable que sirva como única fuente de verdad para clientes, cuentas, tarjetas, movimientos y autenticación, y que además exponga los puntos de integración que necesitarán las capas de IA (Financial Coach, Voice Agent, scoring de crédito, detección de fraude), seguridad/compliance y analítica.

El backend no se diseña como un CRUD aislado: se diseña como la base sobre la que se conectará todo el resto del roadmap de 9 meses, así que las decisiones de arquitectura de este mes deben anticipar esos consumidores.

---

## 2. Alcance (qué entra y qué no)

**Entra en esta fase:**
- API REST versionada (`/api/v1`) con FastAPI
- Modelo de datos relacional en PostgreSQL (clientes, cuentas, tarjetas, movimientos, auditoría)
- Autenticación y autorización (JWT + OAuth2, refresh tokens, RBAC básico)
- Caché y sesiones con Redis
- Tareas en background con Celery + Redis (broker)
- Notificaciones en tiempo real vía WebSockets
- Logging estructurado y auditoría inmutable de operaciones sensibles
- Documentación OpenAPI/Swagger generada automáticamente
- Contenedorización con Docker para desarrollo local

**No entra en esta fase (se conecta después):**
- Lógica de IA (RAG, scoring, voice) → mes 3 en adelante, consumiendo endpoints que el backend deja preparados
- KYC/AML real y pentesting formal → mes 7 (este mes solo se deja el modelo de datos y los hooks necesarios)
- Pipelines de CI/CD completos y observabilidad con Grafana/Sentry → mes 7 (en esta fase solo tests locales y lint)
- Dashboards de Power BI → mes 6

---

## 3. Stack tecnológico

| Componente | Tecnología | Versión sugerida | Propósito |
|---|---|---|---|
| Lenguaje | Python | 3.12 | Mismo lenguaje que la capa de IA, facilita reutilizar código |
| Framework API | FastAPI | 0.115+ | Async nativo, validación con Pydantic, OpenAPI automático |
| Servidor ASGI | Uvicorn + Gunicorn | uvicorn 0.30+, gunicorn 22+ | Uvicorn con workers de Gunicorn en producción |
| ORM | SQLAlchemy | 2.0+ (estilo async) | Mapeo objeto-relacional, migraciones tipadas |
| Migraciones | Alembic | 1.13+ | Versionado del esquema de BD |
| Validación | Pydantic | v2 | Schemas de entrada/salida, separación de capas |
| Base de datos | PostgreSQL | 16 | Transaccional, integridad referencial, JSONB para flexibilidad |
| Caché / sesiones | Redis | 7.x | Sesiones, rate limiting, caché de queries |
| Cola de tareas | Celery + Redis broker | Celery 5.4+ | Notificaciones, jobs async, futura integración con fraude/scoring |
| Auth | python-jose / authlib + passlib | última estable | JWT, hashing de contraseñas (bcrypt/argon2) |
| Tiempo real | FastAPI WebSockets / Socket.IO | nativo | Notificaciones push de movimientos |
| Contenedores | Docker + Docker Compose | última estable | Entorno reproducible local |
| Testing | Pytest + pytest-asyncio + coverage | última estable | Pruebas unitarias e integración |
| Linting/Tipado | Ruff + mypy | última estable | Calidad de código, gate de CI |

---

## 4. Arquitectura del backend

Se recomienda una **arquitectura en capas (clean/hexagonal ligera)**, no porque sea moda, sino porque este backend va a recibir consumidores muy distintos (app móvil, agentes de IA, jobs de fraude, analytics) y necesita que la lógica de negocio no dependa de FastAPI ni de SQLAlchemy directamente.

```
Cliente (app móvil / web / agente de IA)
            │
            ▼
   ┌─────────────────────┐
   │   API Layer (FastAPI)│  → routers, schemas Pydantic, dependencias (auth, db session)
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │  Service Layer       │  → casos de uso: crear cuenta, transferir, congelar tarjeta
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │ Repository Layer      │  → acceso a datos, abstrae SQLAlchemy
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │ PostgreSQL / Redis    │
   └─────────────────────┘

   Celery Workers ◄──── eventos (transferencia creada, login sospechoso, etc.)
```

**Por qué esta separación importa para el portafolio:** permite mostrar en una entrevista que el código de negocio (p. ej. "transferir dinero entre cuentas con validación de saldo") se puede testear sin levantar una base de datos real, usando repositorios falsos. Es la diferencia entre un proyecto de tutorial y uno que se ve como producción real.

---

## 5. Modelo de datos (entidades principales)

| Entidad | Campos clave | Relaciones |
|---|---|---|
| `User` | id, email, password_hash, full_name, phone, status, role, created_at | 1—N con `Account`, `AuditLog` |
| `Account` | id, user_id, account_number, currency, balance, status, type | N—1 con `User`; 1—N con `Transaction`, `Card` |
| `Card` | id, account_id, last4, type (débito/crédito), status, expires_at | N—1 con `Account` |
| `Transaction` | id, account_id, type (depósito/retiro/transferencia), amount, status, counterparty_account_id, created_at | N—1 con `Account` |
| `AuditLog` | id, user_id, action, entity, entity_id, ip_address, metadata (JSONB), created_at | N—1 con `User`; **inmutable** (solo insert) |
| `KYCRecord` (placeholder para mes 7) | id, user_id, status, provider_ref, verified_at | N—1 con `User` |
| `RefreshToken` | id, user_id, token_hash, expires_at, revoked | N—1 con `User` |

Recomendaciones de diseño:
- Montos en `Numeric(18,2)`, nunca `float`, para evitar errores de redondeo en dinero.
- `Transaction` nunca se borra ni se actualiza el monto: las correcciones se hacen con transacciones de reverso (patrón contable, append-only).
- `AuditLog` se escribe en cada operación sensible (login, transferencia, cambio de datos) — esto es lo que en el mes 7 se conecta con seguridad/compliance.
- Índices en `account_number`, `user_id` en `Transaction`, y `created_at` para queries de historial.

---

## 6. Diseño de la API (v1)

| Recurso | Endpoints principales | Notas |
|---|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout` | JWT access (corta duración) + refresh token (rotativo, almacenado hasheado) |
| Users | `GET /users/me`, `PATCH /users/me` | Solo el propio usuario o admin |
| Accounts | `GET /accounts`, `POST /accounts`, `GET /accounts/{id}` | Un usuario puede tener varias cuentas |
| Cards | `GET /accounts/{id}/cards`, `POST /accounts/{id}/cards`, `PATCH /cards/{id}/freeze` | Acciones de bloqueo/desbloqueo |
| Transactions | `GET /accounts/{id}/transactions`, `POST /transfers` | `POST /transfers` es transaccional (atómica entre dos cuentas) |
| Notifications (WS) | `WS /ws/notifications` | Push de eventos en vivo al móvil |
| Internal (para IA) | `GET /internal/users/{id}/context`, `POST /internal/risk-events` | Endpoints internos, autenticados con API key de servicio, que usará el Financial Coach y el motor de fraude |

Buenas prácticas a aplicar desde ya:
- Paginación basada en cursor en endpoints de listado (`transactions`, especialmente, crecerá mucho).
- Idempotency keys en `POST /transfers` para evitar transferencias duplicadas por reintentos de red.
- Respuestas de error estandarizadas (`{"error_code", "message", "request_id"}`) para que el móvil y los agentes de IA puedan manejarlas de forma consistente.

---

## 7. Seguridad (lo que se construye ahora, no en el mes 7)

Aunque la capa formal de "Seguridad y compliance" está planeada para el mes 7, varias decisiones **deben tomarse desde el backend base** porque después es muy costoso agregarlas:

- **Hashing de contraseñas:** Argon2 o bcrypt, nunca SHA simple.
- **JWT:** access token de vida corta (15 min), refresh token rotativo almacenado hasheado en BD, revocación por logout.
- **RBAC básico:** roles `customer` y `admin` desde el día uno, aunque solo se use `customer` por ahora.
- **Rate limiting:** Redis + middleware (p. ej. `slowapi`) en `/auth/login` y `/transfers` desde el inicio, para no exponer el portafolio a fuerza bruta cuando se haga el demo público.
- **Validación estricta de entrada:** Pydantic con `strict=True` y validadores de negocio (montos positivos, monedas soportadas).
- **Audit log inmutable:** se implementa desde el primer sprint, no se posterga, porque es la base de la auditoría de compliance del mes 7.
- **Variables sensibles:** nunca en código; `.env` + `pydantic-settings`, y secretos reales fuera del repo (se conecta con DevOps en mes 7/8).

---

## 8. Procesamiento asíncrono (Celery)

Tareas que conviene dejar como jobs desde ahora, aunque su lógica avanzada (fraude, scoring) llegue después:

- `send_notification_task` — push/email tras una transacción.
- `evaluate_transaction_risk_task` — placeholder que en mes 5–6 se conecta al motor de detección de fraude.
- `generate_monthly_statement_task` — útil también para analytics (mes 6).
- `cleanup_expired_refresh_tokens_task` — tarea periódica (Celery beat).

Diseñar las tareas como funciones puras que reciben IDs (no objetos completos) evita problemas de serialización y deja la puerta abierta a que el motor de IA las dispare también.

---

## 9. Estructura de carpetas propuesta

```
nexobank-backend/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── routers/        # auth.py, accounts.py, transactions.py, cards.py
│   │       └── deps.py         # dependencias compartidas (auth, db session)
│   ├── core/
│   │   ├── config.py           # settings con pydantic-settings
│   │   ├── security.py         # hashing, JWT
│   │   └── logging.py
│   ├── models/                 # modelos SQLAlchemy
│   ├── schemas/                # modelos Pydantic (request/response)
│   ├── services/                # lógica de negocio (casos de uso)
│   ├── repositories/            # acceso a datos
│   ├── workers/                 # tareas Celery
│   └── main.py
├── alembic/                     # migraciones
├── tests/
│   ├── unit/
│   └── integration/
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## 10. Estrategia de testing

| Tipo | Herramienta | Meta de cobertura | Qué cubre |
|---|---|---|---|
| Unitarias | Pytest | ≥80% en `services/` | Lógica de negocio sin BD real (repos falsos) |
| Integración | Pytest + BD de test (Docker) | Endpoints críticos | Auth, transferencias, concurrencia de saldo |
| Contrato | Esquemas Pydantic + OpenAPI | 100% de endpoints documentados | Que el móvil y la IA no se rompan por cambios silenciosos |
| Carga (mes 8, con QA) | Locust | — | Transferencias concurrentes, login masivo |

Gate mínimo desde el sprint 1: ningún PR se aprueba sin tests verdes y sin que `ruff`/`mypy` pasen.

---

## 11. Cronograma del backend (8 semanas)

| Semana | Entregable | Detalle |
|---|---|---|
| 1 | Setup del proyecto | Repo, estructura de carpetas, Docker Compose (app + Postgres + Redis), CI mínima (lint + test en GitHub Actions) |
| 2 | Modelo de datos | Modelos SQLAlchemy, migraciones Alembic, seeds de datos de prueba |
| 3 | Auth | Registro, login, JWT + refresh tokens, hashing seguro, tests de auth |
| 4 | Cuentas y tarjetas | Endpoints CRUD de `Account` y `Card`, RBAC básico |
| 5 | Transacciones | `POST /transfers` transaccional, manejo de concurrencia (locks/optimistic locking), audit log |
| 6 | Async y tiempo real | Celery + Redis broker, primera tarea (notificaciones), WebSocket de notificaciones |
| 7 | Endpoints internos para IA | `/internal/*` con API key de servicio, contrato de datos que usará el Financial Coach |
| 8 | Hardening y documentación | Rate limiting, OpenAPI pulido, README técnico, cobertura de tests ≥80%, demo interna |

A partir del mes 3, el backend entra en **modo soporte**: cada nueva capa (IA, seguridad, analytics, DevOps) consumirá o extenderá esta API, así que se recomienda dejar 1 día por semana reservado a partir de entonces para esos cambios de integración.

---

## 12. Criterios de aceptación de esta fase

- La API levanta con un solo comando (`docker compose up`).
- Existe documentación OpenAPI navegable en `/docs`.
- Un usuario puede registrarse, loguearse, crear una cuenta, recibir una tarjeta y hacer una transferencia exitosa entre dos cuentas, con el saldo actualizado correctamente y sin condiciones de carrera.
- Toda operación sensible queda en `AuditLog`.
- Cobertura de tests ≥80% en la capa de servicios.
- Endpoints `/internal/*` listos para que el Financial Coach (mes 3) pueda leer contexto del usuario sin tocar la lógica de negocio.

---

## 13. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Condiciones de carrera en transferencias (doble gasto) | Bloqueo a nivel de fila (`SELECT ... FOR UPDATE`) o locking optimista con versión, cubierto con test de concurrencia |
| Cambios de esquema rompen a la app móvil o a la IA | Versionado de API (`/v1`) y contratos Pydantic estables desde el inicio |
| Acumulación de deuda técnica por prisa en el demo | Gate de CI obligatorio (lint + tests) desde la semana 1, no al final |
| Secretos expuestos en el repo | `.env` fuera de git, revisión en CI con `gitleaks` o similar |

---

¿Quieres que profundice en alguna parte específica — por ejemplo, el diagrama ERD completo, el flujo de autenticación con código real, o el diseño detallado del endpoint de transferencias con manejo de concurrencia?
