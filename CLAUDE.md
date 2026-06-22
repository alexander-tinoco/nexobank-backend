# CLAUDE.md — NexoBank Backend

Este archivo define cómo debe comportarse cualquier IA (Claude Code u otra) al escribir, modificar o revisar código en este repositorio. Es un proyecto bancario de portafolio, pero se desarrolla **con el estándar de un backend financiero real**. Las reglas de aquí tienen prioridad sobre cualquier atajo de conveniencia.

---

## 0. Contexto del proyecto

- Backend de NexoBank: API de banco digital en **FastAPI + PostgreSQL + Redis + Celery**.
- Arquitectura en capas: `api/` (routers/schemas) → `services/` (casos de uso) → `repositories/` (acceso a datos) → `models/` (SQLAlchemy).
- Este backend será consumido por: app móvil, agentes de IA (Financial Coach, Voice Agent), motor de fraude/scoring, y reportes de analytics. **Cualquier cambio debe asumir que hay consumidores externos del contrato de la API.**
- Referencia de diseño completa: `nexobank_backend_planeacion.md` en este repo. Si hay duda sobre una decisión de arquitectura, ese documento manda.

---

## 1. Reglas no negociables (nunca se rompen)

1. **Nunca usar `float` para dinero.** Todos los montos son `Decimal` en Python y `Numeric(18,2)` en la base de datos. Si encuentras `float` en algo relacionado con balances, montos o tasas, es un bug y se corrige, no se ignora.
2. **Nunca borrar ni mutar una `Transaction` ya creada.** Las correcciones se hacen con transacciones de reverso (patrón contable append-only). No se implementa `UPDATE` ni `DELETE` sobre movimientos.
3. **Nunca loguear ni exponer en respuestas:** contraseñas, tokens completos, números de tarjeta completos (solo últimos 4 dígitos), CVV, ni el contenido de `password_hash`.
4. **Nunca commitear secretos.** Ninguna API key, contraseña de BD, o credencial va en código, `.env.example` debe tener solo placeholders. Si detectas un secreto real en el código durante una tarea, deténte y avisa antes de continuar.
5. **Toda operación sensible debe escribir en `AuditLog`** (login, cambio de contraseña, transferencia, congelar/descongelar tarjeta, cambio de datos personales). Si agregas un endpoint que modifica estado financiero o de seguridad y no escribe audit log, la tarea no está terminada.
6. **Toda escritura concurrente sobre saldo debe ser segura ante condiciones de carrera** (`SELECT ... FOR UPDATE` o locking optimista con columna de versión). No se acepta un endpoint de transferencia o retiro sin esta protección.
   - **Gotcha de SQLAlchemy — `FOR UPDATE` + identity map:** un `SELECT ... FOR UPDATE` sobre una fila que la sesión **ya cargó antes sin lock** (p. ej. un chequeo de propietario previo) devuelve el objeto **cacheado con saldo stale** y descarta la fila recién bloqueada. El lock serializa, pero la lógica lee el saldo viejo → **doble gasto**. Solución obligatoria: añadir `.execution_options(populate_existing=True)` a la query de `FOR UPDATE` para forzar el refresco con el estado committeado más reciente. Esto aplica a transferencias, retiros, depósitos y cualquier mutación de saldo. Lo detectó el test de concurrencia en `tests/integration/test_concurrency.py` (saldo 1000, dos transferencias de 600 → debe dar 201 + 422, no 201 + 201).
7. **No se rompe el contrato de la API sin versionar.** Cambiar un campo de respuesta, un código de error o el shape de un schema en `/v1` existente requiere crear `/v2` o coordinar el cambio explícitamente — nunca un cambio silencioso.

Si una petición del usuario entra en conflicto directo con alguna de estas reglas, la IA debe señalarlo explícitamente y proponer la alternativa segura, no ejecutar el atajo inseguro en silencio.

---

## 2. Estándares de código

### Python / FastAPI
- Python 3.12, tipado estricto en todo el código nuevo (`mypy` debe pasar sin `# type: ignore` salvo justificación en comentario).
- `ruff` para lint y formato; cero warnings antes de considerar una tarea terminada.
- Funciones cortas, con un solo nivel de responsabilidad. Si una función de servicio supera ~40 líneas, se evalúa dividirla.
- Nombres explícitos: `calculate_available_balance`, no `calc` o `do_thing`.
- Nunca lógica de negocio dentro de un router de FastAPI. El router solo: valida input, llama al servicio, devuelve output. La lógica vive en `services/`.
- Nunca acceso directo a SQLAlchemy desde `services/` o `api/`. Todo acceso a datos pasa por `repositories/`.
- Pydantic v2 para todos los schemas de entrada/salida. Nunca devolver el modelo de SQLAlchemy directamente en una respuesta HTTP.
- Manejo de errores con excepciones de dominio propias (`InsufficientFundsError`, `AccountNotFoundError`), capturadas en un exception handler central que las traduce a códigos HTTP. No usar `HTTPException` directamente dentro de `services/`.

### Base de datos
- Toda migración pasa por Alembic. Nunca modificar el esquema a mano en producción ni con `Base.metadata.create_all()` fuera de tests.
- Toda tabla nueva: revisar si necesita índice en las columnas usadas en `WHERE`/`JOIN` antes de cerrar la tarea.
- Las migraciones deben ser reversibles (`downgrade()` implementado, no vacío).

### API
- Todo endpoint nuevo debe quedar documentado (docstring + ejemplos en OpenAPI) y reflejado correctamente en `/docs`.
- Paginación basada en cursor en cualquier endpoint de listado que pueda crecer sin límite (transacciones, notificaciones, audit logs).
- Idempotency key obligatoria en endpoints que muevan dinero (`POST /transfers`).
- Respuestas de error siempre en el formato estándar `{"error_code", "message", "request_id"}`.

---

## 3. Seguridad — checklist obligatorio antes de cerrar cualquier tarea

Antes de marcar como terminada una tarea que toque autenticación, dinero, o datos personales, verificar:

- [ ] ¿Se valida que el usuario autenticado es dueño del recurso (cuenta, tarjeta) antes de operar sobre él?
- [ ] ¿El endpoint tiene rate limiting si es público o sensible (login, transferencias, reseteo de contraseña)?
- [ ] ¿La validación de entrada rechaza montos negativos o cero donde no corresponde, monedas no soportadas, IDs malformados?
- [ ] ¿Se usa hashing seguro (Argon2/bcrypt) para cualquier credencial nueva, nunca hash propio o reversible?
- [ ] ¿Los tokens (JWT, refresh) tienen expiración y, en el caso de refresh tokens, se almacenan hasheados y son revocables?
- [ ] ¿El cambio introduce algún dato sensible en logs, traces o mensajes de error visibles al cliente?

Si la respuesta a cualquier punto es "no" y debería ser "sí", la tarea no está completa.

---

## 4. Testing — reglas estrictas

- **Ningún código de `services/` se considera terminado sin tests unitarios** que cubran al menos: caso feliz, caso de error de negocio (ej. fondos insuficientes), y caso de borde (montos límite, cuenta inexistente).
- **Toda transferencia o escritura concurrente sobre saldo requiere un test de concurrencia** que simule dos operaciones simultáneas y verifique que el saldo final es correcto.
- Cobertura mínima de la capa `services/`: 80%. Si una tarea baja la cobertura por debajo de ese umbral, se deben agregar tests antes de cerrarla.
- Los tests de integración usan una base de datos de test real (vía Docker), nunca mocks de SQLAlchemy que oculten bugs de queries reales.
- No se aprueba ni se da por terminado código nuevo con tests en rojo, ni con tests comentados o saltados (`@pytest.mark.skip`) sin justificación explícita registrada.

---

## 5. Cómo debe trabajar la IA en este repo

1. **Antes de escribir código**, leer los archivos relevantes existentes (`services/`, `repositories/`, `models/` afectados) para mantener consistencia de estilo y evitar duplicar lógica ya existente.
2. **Explicar el plan brevemente antes de tocar código** cuando el cambio afecte más de un módulo (ej. nuevo endpoint que toca router + service + repository + migración).
3. **Cambios pequeños y verificables**, no refactors masivos sin que se pidan explícitamente. Si una tarea requiere tocar muchos archivos, dividirla y avisar.
4. **Nunca inventar campos, tablas o endpoints que no existen** para "que compile". Si falta algo, se señala y se propone agregarlo explícitamente, no se asume.
5. **Después de cualquier cambio:** correr (o indicar que se deben correr) `ruff`, `mypy` y `pytest` antes de considerar la tarea terminada. Si la IA no puede ejecutar estos comandos en el entorno actual, debe decirlo explícitamente en vez de asumir que pasan.
6. **No modificar migraciones ya aplicadas en otros entornos.** Una migración existente y mergeada no se edita; se crea una nueva.
7. **Commits y PRs descriptivos:** el mensaje de commit explica el "por qué", no solo el "qué" (ej. `fix: bloquear fila de cuenta en transferencias para evitar doble gasto`, no `fix bug`).
8. **Si una petición del usuario es ambigua respecto a una de las reglas de este archivo**, la IA debe preguntar o señalar la ambigüedad antes de decidir por su cuenta.

---

## 6. Fuera de alcance para la IA sin confirmación explícita

- Cambiar el motor de base de datos, el framework principal, o agregar una dependencia nueva de peso (ej. otro ORM, otro framework de auth).
- Eliminar o renombrar campos de modelos ya usados por otros módulos sin revisar impacto.
- Modificar la estructura de carpetas base definida en la planeación del proyecto.
- Tocar configuración de producción (variables de entorno, secretos, infraestructura) sin que se indique explícitamente que es esa la intención.

---

## 7. Definición de "terminado"

Una tarea de backend en NexoBank se considera terminada solo si:

- El código sigue la arquitectura en capas (router → service → repository).
- Pasa lint, tipado y tests (o se indica explícitamente que no se pudieron correr y por qué).
- Cubre el checklist de seguridad de la sección 3 si aplica.
- Tiene tests nuevos o actualizados con cobertura razonable.
- No rompe contratos de API existentes sin versionar.
- Cualquier operación sensible queda auditada en `AuditLog`.

Si alguno de estos puntos no se cumple, la tarea se reporta como **parcial**, no como completa.
