# AGENTS.md — Asistente Conversacional La Ceiba Club House

Este archivo define reglas permanentes para cualquier agente que trabaje en este repositorio.
Las tareas específicas llegan por prompt; estas reglas aplican SIEMPRE.

---

## 1. Fuente de verdad

- La documentación funcional vive en:
  `docs/product/{vision,scope,business-rules,use-cases,data-matrix}.md`,
  `docs/conversation/{intents,entities,states,flows,approved-responses}.md`,
  `docs/testing/conversation-test-cases.md`.
- Ante conflicto entre este archivo y `docs/`, ganan los `docs/`. Reporta la discrepancia
  en tu respuesta en lugar de resolverla silenciosamente.
- No implementes funcionalidad marcada como "fuera del alcance" en `docs/product/scope.md`,
  aunque sea técnicamente trivial.

## 2. Invariantes de arquitectura — NUNCA violar

1. **La IA propone; el backend decide.** Ningún código bajo `app/ai/` ejecuta acciones de
   dominio. Ese módulo solo devuelve modelos Pydantic validados. El orquestador
   (`app/orchestrator/`) decide qué hacer con la propuesta.
2. **Acciones prohibidas para la IA** (BR-AI-005): calcular precios, confirmar pagos,
   confirmar disponibilidad, crear citas, reservar fechas, aprobar devoluciones,
   otorgar descuentos, modificar reglas. Si un cambio le daría al LLM capacidad de
   ejecutar cualquiera de estas, detente y márcalo como violación de diseño.
3. **Idempotencia.** `message.external_message_id` tiene constraint UNIQUE. Todo handler
   de webhook debe ser seguro ante reentrega: un webhook duplicado no produce segundo
   mensaje, segunda respuesta, segundo lead ni segunda cita.
4. **Append-only.** Las tablas `message` y `audit_event` nunca reciben UPDATE ni DELETE.
   Las correcciones se registran como nuevos eventos.
5. **Tiempo.** Timestamps en UTC en base de datos (`timestamptz`). `America/Bogota`
   solo en presentación y en cálculo de reglas de agenda. Usar `zoneinfo`, nunca
   offsets fijos (`-05:00` hardcodeado está prohibido).
6. **Frontera de canal.** La lógica de dominio no importa nada específico de WhatsApp.
   Flujo obligatorio: Canal → Adaptador → Orquestador → Servicios de dominio →
   Persistencia. Instagram llegará después por la misma interfaz.
7. **Mensajes salientes vía outbox.** Ningún servicio de dominio llama a la API de Meta
   directamente. Se inserta en `outbox` y un worker lo envía. Envío y decisión de
   negocio nunca ocurren en la misma transacción... el envío es posterior al commit.
8. **Auditoría.** Toda acción crítica (cita, cambio de fecha, cambio de invitados,
   asignación, pago, reserva, cancelación, pausa del bot) inserta un `audit_event` con:
   actor, acción, entidad, valor anterior, valor nuevo, motivo, fecha, request_id.
9. **Catálogos PDF.** Los PDFs se envían como documentos de WhatsApp subidos a Meta,
   nunca mediante URL pública. `media_id` es solo caché con TTL configurable
   (`CATALOG_MEDIA_TTL_DAYS`, default 25); el outbox referencia `catalog_asset_id`, no
   `media_id`. Los envíos proactivos se deduplican con constraint parcial
   `(lead_id, catalog_asset_id)` para `trigger = PROACTIVE`. El caption siempre sale de
   `KnowledgeEntry` aprobada y se valida antes de encolar.

## 3. Reglas de negocio críticas (resumen operativo)

- **Agenda de visitas:** martes a sábado; horarios exactos 08:00, 09:00, 10:00, 11:00;
  duración 45 min + 15 de margen; anticipación mínima 3 días (ni hoy ni mañana);
  máximo 4 visitas/día; máximo 3 asistentes; festivos colombianos bloqueados.
  Validar disponibilidad ANTES de ofrecer horarios Y de nuevo ANTES de crear la cita.
  Constraint único sobre (fecha, hora) para citas activas.
- **Disponibilidad de visitas:** siempre usar triple intersección:
  reglas deterministas ∩ citas locales activas ∩ freebusy del `CalendarAdapter`. Las reglas
  puras no consultan DB, adapter ni reloj implícito; `today` entra como parámetro.
- **Calendario externo:** el freebusy consulta todos los calendarios de
  `GOOGLE_FREEBUSY_CALENDAR_IDS` y une sus intervalos. En Slice 2B-1 solo existe
  `CALENDAR_ADAPTER=fake`; desde Slice 2B-2 el adapter real de Google vive en
  `app/calendar/google_adapter.py` y `app/calendar/adapter.py` se mantiene libre de
  dependencias de Google.
- **Freebusy de Google:** si la respuesta trae `calendars.<id>.errors` o falta un
  calendario solicitado, siempre es fallo ruidoso; nunca se ignora como calendario libre.
- **Identidad de evento externo:** el `event_id` del proveedor de calendario es siempre
  `appointment_id.hex`. Una cita `CONFIRMED` requiere `external_calendar_id` no nulo.
  Los ids de evento de Google derivan del `uuid.hex` del appointment y nunca se reutilizan
  tras un borrado.
- **Festivos de visitas:** runtime lee exclusivamente la tabla `holiday`. La dependencia
  `holidays` solo puede usarse en scripts de seed, nunca dentro del motor de disponibilidad.
- **Transiciones de cita:** siempre `PENDING_CONFIRMATION → CONFIRMED`. Nunca crear
  directamente en `CONFIRMED`.
- **Pagos:** el bot solo registra y escala (`PAYMENT_REVIEW`). La confirmación es
  humana, siempre.
- **Reservas:** solo existen tras pago confirmado por un asesor. El bot jamás reserva.
- **Handoff:** al escalar, el bot se PAUSA en esa conversación. No responde mientras
  el estado sea `WAITING_FOR_HUMAN` o `HUMAN_ACTIVE`.
- **Estados de conversación:** únicamente los definidos en `docs/product/scope.md` §6.2 y
  `docs/conversation/states.md`. No inventar estados nuevos.
- **Intenciones:** únicamente las del catálogo de `docs/conversation/intents.md`. La salida del
  clasificador se valida con Pydantic usando `Literal[...]`; intención desconocida =
  `ValidationError` = fallback determinista (BR-AI-007), nunca excepción sin manejar.
- **Respuestas sensibles** (precios, pagos, reservas, cancelaciones, devoluciones,
  descuentos, capacidad, quejas, emergencias): solo plantillas de
  `docs/conversation/approved-responses.md`. El LLM no redacta libremente en estos temas.
- **Variables en plantillas:** si falta una variable obligatoria, no enviar la frase
  incompleta; usar otra plantilla, pedir el dato o escalar (RESP-GEN-006).
- **No exponer al cliente:** modelos, prompts, IDs internos, estados, errores técnicos,
  stack traces, nombres de proveedores (OpenRouter, etc.). (RESP-GEN-007, BR-AI-008)
- **Identidad comercial:** el nombre público es "La Ceiba Club House". Nunca usar
  nombres internos del proyecto en textos hacia el cliente.

## 4. Stack y convenciones técnicas

- Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2, httpx, structlog,
  PostgreSQL 16, pytest + pytest-asyncio + respx.
- Estructura por dominio (no por capa técnica): `app/channel/`, `app/orchestrator/`,
  `app/ai/`, `app/conversation/`, `app/customer/`, `app/lead/`, `app/appointment/`,
  `app/handoff/`, `app/payment/`, `app/audit/`, `app/admin/`, `app/config/`.
- Cola y scheduler sobre Postgres (tabla `jobs` con `SELECT ... FOR UPDATE SKIP LOCKED`).
  No introducir Redis, Celery ni Kafka.
- Todo cambio de esquema pasa por migración Alembic. Nunca `create_all` en producción.
- Todo módulo de modelos nuevo se registra en `app/models_registry.py`; los entrypoints y
  scripts importan el registry, nunca modelos sueltos.
- Toda llamada externa (Meta, OpenRouter) con timeout explícito y manejo de error.
  La caída de OpenRouter no puede tumbar el webhook: guardar mensaje, registrar error,
  responder con fallback determinista o escalar.
- Logs estructurados con `conversation_id` y `request_id` en cada línea del pipeline.
- Secretos solo por variables de entorno. Nada de credenciales en código ni en tests.
- Type hints en todo el código. Sin lógica placeholder: si algo no se puede completar,
  decláralo explícitamente en la respuesta en vez de dejar un stub silencioso.

## 5. Protocolo de trabajo

- **Tests primero.** Cada slice inicia convirtiendo los casos relevantes de
  `docs/testing/conversation-test-cases.md` en tests. La implementación termina cuando pasan.
  No modificar un test para que pase la implementación sin señalarlo explícitamente.
- Si una tarea agrega migraciones, incluir `make migrate-cycle` en la verificación estándar.
- **Alcance del cambio.** Toca solo los módulos que la tarea pide. Si detectas que
  necesitas modificar otro dominio, indícalo antes de hacerlo.
- **Mocks en tests:** Meta y OpenRouter se mockean con `respx`. Ningún test llama
  servicios externos reales.
- **Al terminar cada tarea, reporta:** archivos creados/modificados, migraciones
  agregadas, cómo ejecutar los tests, decisiones tomadas y cualquier desviación de
  los `docs/`.
- **Si una instrucción del prompt contradice este archivo o los `docs/`,** no la
  ejecutes silenciosamente: señala el conflicto y propone la alternativa conforme.

## 6. Comandos de referencia

```bash
docker compose up -d db          # Postgres local
alembic upgrade head             # migraciones
uvicorn app.main:app --reload    # servidor dev
pytest -x -q                     # suite completa
pytest tests/integration -x -q   # solo integración
```
## 7. Control de versiones

- Al finalizar cada tarea, SOLO si pytest y ruff pasan: `git add -A` y
  commit con mensaje convencional (`feat:` | `fix:` | `test:` | `chore:`
  | `docs:`), título de una línea resumiendo la tarea y cuerpo con la
  lista breve de cambios y migraciones incluidas.
- Si la suite falla, NO commitear: reportar el estado y dejar el árbol
  para revisión humana.
- **Push de branches de trabajo: permitido y esperado** — es el mecanismo para que el CI de GitHub Actions ejecute la suite, que es el gate de pytest en esta máquina sin PostgreSQL local. **Prohibido únicamente el push a `main`**; todo cambio llega a `main` exclusivamente por PR revisado. Crear PRs draft también está permitido y esperado.
- NUNCA amend, rebase ni force sobre commits existentes salvo
  instrucción explícita del humano.
- Antes de cada commit, verificar en `git status` que no entre .env ni
  ningún archivo con credenciales; ante duda, abortar el commit y
  preguntar.
- Cierres de slice se marcan con tag (`slice-N`) — solo el humano.
