# Handoff CHAT_BOT_CEIBA — cierre 2026-08-21 (sesión PR-A observabilidad)

## Estado de producción (verificado en vivo)

`main` = producción, desplegado y verificado extremo a extremo. HEAD:
`6ad9310`. Alembic: `20260821_0022 (head)` — primera migración desde
`0021`, aplicada y confirmada en VPS. Contenedor `app` recreado (StartedAt
20:31:12Z).

**Slice desplegado: PR-A `ai-execution-observability`** (10 commits,
CI verde, PR cerrado por push a main):

1. **`ai_execution` evolucionada in-place** (era tabla legacy de `0006`,
   descubierta en censo G1.5 — no tabla nueva): rename `function`→`task` +
   CHECK, columnas nuevas nullable sin backfill (`request_id` UUID,
   `external_message_id`, `input_payload` JSONB, `raw_output`,
   `parsed_output` JSONB, `validation_status` + CHECK 5 valores, `error`).
   `validation_status IS NULL` ⇔ fila legacy. PK Integer y campos legacy
   conservados y aún escritos (continuidad).
2. **`request_id`**: UUID v4 generado en `receive_webhook`, propagado por
   parámetro explícito por la cadena real hasta el cliente; header
   `X-Request-ID` solo se loguea como `external_request_id`.
3. **Escritor best-effort**: persistencia en transacción propia post-HTTP,
   try/except con WARNING `ai_execution_persist_failed`; corregido el bug
   latente del `finally` que podía reemplazar la excepción original o
   convertir éxito en error.
4. **Sanitización allowlist**: `TELEMETRY_SAFE_KNOWN_FIELDS`
   (`event_type`, `preferred_visit_date`); fail-closed.
5. **Logging estructurado del orquestador**: record INFO
   `orchestrator_decision` con 7 campos (request_id, intent, state_before,
   state_after, transition, decision_source, pending_action), emitido en
   finally (uno por invocación).
6. **TC-PARITY-001**: paridad metadata↔Alembic contra DB efímera con la
   cadena completa 0001→0022; normalizado el falso positivo del PK serial.
7. **`presentation.py` migrado a structlog** (era el único emisor stdlib
   de eventos en app/ junto a `schemas.py`, que queda en backlog).
8. **Docs en repo**: `docs/product/ai-execution-observability.md`
   (rector v1.1; enmienda v1.1.1 pendiente de commit) y
   `docs/product/services-catalog.md` (catálogo canónico de servicios
   v1.0 APROBADO — 36 códigos con label, presentación, aliases,
   descripción; insumo de PR-B).

## Forense inaugural (el slice pagando su deuda el mismo día)

Conversación e2e real post-deploy (filas 531–532, ambas VALID, UUID,
wamid, payloads completos, known_fields={}):

- **Fila 531** ("quiero hacer una fiesta sorpresa"): el clasificador
  devolvió `event_type` raw="fiesta sorpresa",
  normalized_value="fiesta sorpresa" — fiel, sin inventar. El bot
  confirmó "una boda...": el label vino del ESTADO PERSISTIDO de la
  conversación antigua, no del clasificador. **Primer fallo de la
  historia del proyecto resuelto por SELECT y no por conjetura**, y es un
  fenómeno NUEVO para el backlog: arrastre de estado de conversaciones
  viejas sin re-confirmación de event_type.
- **Fila 532** ("Espacio y gastronomía"): capturado verbatim en
  `requested_services`, sin códigos — justificación empírica de PR-B.
- `SELECT DISTINCT model` → solo `google/gemini-2.5-flash-lite`;
  `DEFAULT_INTENT_MODEL` de client.py es letra muerta (backlog).
- Ventana de deploy observada: filas 529–530 (16:47–16:48Z) escritas por
  código viejo sobre esquema ya migrado — benigno, esperado, documentado.

## Pendiente INMEDIATO (siguiente sesión, 10 minutos)

1. Commit `docs:` directo a main: anexar enmienda v1.1.1 al rector
   (archivo `enmienda-rector-v1.1.1.md` de esta sesión) y este handoff.
2. Nada más bloquea PR-B.

## Cola decidida (sin cambios de orden)

1. **PR-B** `services-classification-and-event-type-extraction`: A7-bis
   determinista contra aliases del catálogo (longest-match-first, negación
   →LLM), tarea SERVICES_CLASSIFICATION (códigos cerrados, JSON),
   tarea EVENT_TYPE_EXTRACTION (normalización DENTRO del cliente → activa
   NORMALIZED/DISCARDED), RESP-SERVICES-RETRY-001 (texto aprobado en
   catálogo §5), composición determinista de requested_services_summary.
   Suite roja TC-SVC derivada del catálogo; casos literales del
   expediente + longest-match.
2. **Decisión clasificador con datos** (1–2 semanas de ai_execution
   poblado): prompt vs modelo vs determinismo extendido.
3. **CRUD de tipos de evento** (fusión boda/boda-civil como caso de
   aceptación).
4. Convergencia de compose.

## Backlog (nuevos de esta jornada arriba)

- **Arrastre de estado de conversación antigua** (event_type viejo
  contamina confirmaciones nuevas sin re-confirmación) — evidencia:
  fila 531.
- `app/ai/schemas.py`: emisor stdlib residual
  (`ai_invalid_information_category`) → unificar a structlog.
- `DEFAULT_INTENT_MODEL` muerto en client.py → alinear o eliminar.
- `.gitattributes` ausente (warnings LF/CRLF en Windows) → `* text=auto`.
- `review-*.txt` como patrón de gate → considerar entrada en .gitignore.
- Retención de ai_execution: ~66 filas/día, prioridad ínfima.
- Enforcement DB de append-only (trigger/permiso) para las 3 tablas.
- Ítems previos vigentes: fechas con día de semana, lockout /admin/login,
  polling panel admin, token Meta permanente, RESP-FOLLOWUP-005 residual,
  caption ×5 ROMANTIC_DINNER, "quiero información de X evento",
  Configuration §18.2, catalog_send.lead_id nullable, verificación
  oportunista e2e B (render de cotización real), identidad git corporativa
  (Emerson decidió no cambiarla — commits salen con correo EDEQ, asumido).

## Aprendizajes nuevos de esta jornada

- **El discovery gate salvó el slice**: el rector v1.0 asumía tabla nueva;
  el censo G1.5 reveló tabla legacy con escritor activo. "Auditar lo que
  el trabajo previo entregó de verdad" aplica también a lo que uno mismo
  diseñó sin censar.
- **El captor vive en el mismo pipeline que el emisor**: capsys frágil
  siempre; caplog solo para stdlib; capture_logs solo para structlog Y
  requiere cache_logger_on_first_use=False (condicionado a producción).
  Un test que cruza el puente stdlib↔structlog pasa por accidente — se
  demostró con un test del slice anterior que sobrevivió un CI entero
  verde siendo frágil.
- **Verificación empírica > relectura de diff en fixes repetidos**: la
  ronda de paridad se resolvió cuando se exigió imprimir ambas tuplas
  antes de reportar; la de caching, cuando se exigió reproducir el ORDEN
  exacto del fallo (emitir→cachear→capturar). Especificar la reproducción
  es parte del prompt.
- **El comparador de paridad debe normalizar representaciones**: metadata
  expresa PK serial como autoincrement=True; PostgreSQL reflejado como
  server_default=nextval — misma semántica, comparación literal falla.
- **Focal en Windows = solo tests sin DB; CI es el focal real**. Un focal
  que no puede pasar localmente corta la cadena && sin aportar señal
  (ocurrió: el push se frenó por ConnectionRefused, no por código).
- **Ventana de deploy**: migración se aplica antes de recrear contenedor;
  filas escritas en esa ventana tienen esquema nuevo + escritor viejo.
  Patrón benigno reconocible: columnas nuevas NULL con created_at previo
  al StartedAt del contenedor.
- **Denylist→allowlist para fronteras de privacidad**: fail-closed; el
  censo encontró la clave (`customer_phone`) que la denylist habría
  dejado pasar.
- **Codex pide autorización cuando la orden contradice el terreno** (el
  emisor stdlib que capture_logs no podía capturar): el patrón
  reporta-y-se-detiene funcionó; la contradicción era información, no
  fricción.

## Protocolo vigente (con la corrección de focal)

docs → suite adversarial roja → Codex (G1/G2/G3, desviaciones declaradas,
puede pushear ramas; main jamás) → revisión de diffs frontera por Claude
(con verificación empírica exigida en fixes repetidos) → PR → CI (focal
real para suites con DB) → merge ff-only con merge-base + focal local
SOLO sin-DB → push main → CD → verificación VPS → e2e WhatsApp + forense
ai_execution. Autoridad de textos a cliente: Emerson o Leandro,
indistintamente.
