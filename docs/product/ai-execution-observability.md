# Slice PR-A — Observabilidad de ejecuciones de IA (`ai_execution`)

**Estado:** APROBADO v1.1 — Emerson, 2026-08-21. Sustituye a v1.0 tras los
censos G1 y G1.5 (hallazgo: `ai_execution` legacy existe desde la migración
`0006` con escritor activo en `client.py::_record_execution`).
**Naturaleza del slice (enmendada):** EVOLUCIÓN in-place del esquema legacy,
no creación de tabla nueva.
**Motivación:** expediente de 3 fallos de clasificación diagnosticados a
ciegas (handoff 2026-08-21). La telemetría legacy registra éxito/fallo y
latencia pero NO persiste input completo, output crudo ni output parseado:
un clasificador que "funciona" devolviendo contenido incorrecto es invisible.

---

## 1. Esquema objetivo de `ai_execution`

Evolución desde el esquema de `0006` mediante UNA migración nueva desde
`20260819_0021`. Sin backfill de filas existentes (sería UPDATE sobre tabla
append-only). Regla de lectura: `validation_status IS NULL` ⇔ fila legacy
pre-slice.

### Columnas que se conservan sin cambio

| Campo | Tipo | Nullable | Notas |
| --- | --- | --- | --- |
| `id` | Integer PK | no | DECISIÓN v1.1: se conserva Integer; UUID no aporta y cambiar PK reescribe la tabla |
| `created_at` | timestamptz | no | `server_default=now()` |
| `model` | String(255) | no | |
| `latency_ms` | Integer | no | DECISIÓN v1.1: conserva NOT NULL (medible en todos los caminos, incluidos errores) |
| `success` | Boolean | no | derivable de `validation_status`; se sigue escribiendo por continuidad histórica |
| `error_reason` | String(64) | sí | catálogo aplicativo TIMEOUT/HTTP_ERROR/INVALID_JSON/SCHEMA_VIOLATION; se sigue escribiendo |
| `conversation_id` | Integer FK→conversation.id, indexada | sí | DECISIÓN v1.1: se conserva; correlación valiosa omitida en v1.0 |
| `input_character_count` | Integer | no | derivable; se sigue escribiendo |
| `prompt_version` | String(64) | no | convención `<task>_vN` (underscore, adoptando el separador legacy ya presente en datos: `intent_v3`) |

### Renombre

| Antes | Después | Notas |
| --- | --- | --- |
| `function` | `task` | + CHECK constraint contra el catálogo: `INTENT_CLASSIFICATION`, `SERVICES_CLASSIFICATION`, `EVENT_TYPE_EXTRACTION`. Los valores existentes ya cumplen. Extensión del catálogo = migración |

### Columnas nuevas (todas nullable en DB; NOT NULL para escrituras nuevas se garantiza en capa de aplicación y se aserta en tests)

| Campo | Tipo | Notas |
| --- | --- | --- |
| `request_id` | UUID | generado en el webhook handler; NULL para ejecuciones fuera de ciclo HTTP (scripts) y filas legacy |
| `external_message_id` | Text | referencia lógica al mensaje disparador; SIN FK y SIN UNIQUE (varias tareas por mensaje son legítimas); patrón análogo a `message_provider_status.provider_message_id` |
| `input_payload` | JSONB | texto del usuario + contexto (pregunta pendiente, estado). SIN datos de contacto |
| `raw_output` | Text | output crudo sin parsear; NULL si la llamada falló antes de respuesta |
| `parsed_output` | JSONB | resultado post-validación; NULL si no parseable |
| `validation_status` | Text + CHECK | `VALID`, `NORMALIZED`, `INVALID_SCHEMA`, `DISCARDED`, `HTTP_ERROR`. NULL ⇔ fila legacy |
| `error` | Text | detalle de excepción; complementa el código corto de `error_reason` |

### Semántica de `validation_status`

* `VALID`: parseó y validó sin transformación.
* `NORMALIZED`: pasó por fallback (p. ej. `normalize_event_type`).
* `INVALID_SCHEMA`: JSON malformado, estructura inválida o violación
  Pydantic (absorbe INVALID_JSON y SCHEMA_VIOLATION del catálogo corto).
* `DISCARDED`: esquema válido, valor rechazado por regla de negocio.
* `HTTP_ERROR`: llamada fallida (absorbe TIMEOUT y HTTP_ERROR);
  `raw_output` NULL, `error` poblado.

## 2. Contrato de persistencia

1. HTTP a OpenRouter FUERA de toda transacción DB abierta (invariante
   vigente; el censo G1 confirmó que hoy se cumple — TC-AIEXEC-003 queda
   como guardia de regresión, declarado verde-en-G1).
2. La persistencia (`_record_execution` evolucionado) es transacción propia
   posterior al HTTP, best-effort: try/except que emite WARNING estructurado
   `ai_execution_persist_failed` (con `request_id`, `task`) y NUNCA
   interrumpe la clasificación. HALLAZGO G1.5 A CORREGIR: el `finally`
   actual puede reemplazar la excepción original o convertir un éxito en
   error — TC-AIEXEC-004 rojo lo confirma; es bug latente en producción.
3. Sin UNIQUE sobre `external_message_id`.
4. Se persiste TODA ejecución, incluidas fallidas. Se mantiene el
   comportamiento legacy de una fila por invocación (no por reintento HTTP).

## 3. `request_id` (enmendado por censo G1)

* Se genera en `receive_webhook()` (`app/channel/webhook.py`): UUID v4
  propio, uno por request HTTP. El header `X-Request-ID` NO lo sustituye
  (no es UUID garantizado); si está presente puede loguearse como
  correlación adicional, nunca persistirse en la columna.
* Varios mensajes del mismo payload comparten `request_id`;
  `external_message_id` desambigua.
* Propagación por PARÁMETRO EXPLÍCITO por la cadena real:
  `receive_webhook → store_webhook_event → process_webhook_event →
  persist_payload_phase_a → classify_and_orchestrate_phase_b_c →
  OpenRouterIntentClient.classify_intent`. Prohibido contextvar/global.
* `process_whatsapp_webhook()` (entrada interna) y
  `scripts/smoke_openrouter.py` pasan `request_id=None` explícito.
* DECISIÓN D1: la cadena real (coordinador de canal invoca al cliente antes
  del orquestador) se ACEPTA; mover esa responsabilidad es rediseño fuera
  de alcance.

## 4. Logging estructurado del orquestador (enmendado por censo G1)

* Logger: el existente por convención structlog
  (`app.orchestrator.service`). DECISIÓN D3: no se introduce
  `ceiba.orchestrator`; los tests asertan sobre evento y campos, no sobre
  el nombre del logger.
* Un record INFO por decisión de orquestación, evento
  `orchestrator_decision`, campos fijos:

```text
request_id, intent, state_before, state_after, transition,
decision_source (DETERMINISTIC | LLM | FALLBACK), pending_action
```

* `pending_action` se loguea tal como lo fija el orquestador desde el
  catálogo oficial. Aserciones vía `caplog.at_level` sobre records; `capsys`
  prohibido para logs.

## 5. Suite (estado tras G1)

Escrita y roja (salvo TC-AIEXEC-003, guardia declarada):
TC-AIEXEC-001..008, TC-LOG-001..003, TC-PARITY-001 (paridad contra DB
efímera con `alembic upgrade head`).

Pendiente G2: adaptar la suite rescatada a la nomenclatura v1.1
(`raw_output`/`parsed_output`, `INVALID_SCHEMA`, WARNING
`ai_execution_persist_failed`) — adaptación declarada; la suite original
fue escrita contra el esquema legacy y v1.1 es el contrato vigente.

## 6. Fuera de alcance de PR-A

* Cambios de prompts o de modelo (bloqueado hasta tener datos).
* Clasificación de servicios y extracción de event_type (PR-B).
* Panel/consulta admin de `ai_execution` (backlog; SQL directo basta).
* Backfill de filas legacy (prohibido: append-only).
* Retención/purga (backlog; anotar volumen estimado en G3).
* Enforcement DB de append-only (trigger/permiso): anotado como candidato
  de backlog para las tres tablas append-only a la vez, no solo esta.
  # Enmienda v1.1.1 — anexar al final de docs/product/ai-execution-observability.md


## 7. Enmiendas v1.1.1 (decisiones de implementación y post-deploy, 2026-08-21)

1. **Semántica de `INVALID_SCHEMA` en excepciones inesperadas:** una
   excepción que no es HTTP ni de parseo persiste `validation_status=
   'INVALID_SCHEMA'` por el default del escritor. El caso es distinguible
   forensicamente: `error_reason` NULL + `error` poblado. Aceptado; no se
   introduce un sexto estado para un camino excepcional.
2. **Representación de `transition`:** string `"STATE_BEFORE->STATE_AFTER"`;
   `None` cuando el estado no cambia.
3. **`NORMALIZED` y `DISCARDED` sin escritor en `INTENT_CLASSIFICATION`:**
   la normalización ocurre en el orquestador, después del cliente. Ambos
   estados quedan reservados; PR-B los activa diseñando sus tareas
   (`SERVICES_CLASSIFICATION`, `EVENT_TYPE_EXTRACTION`) con la validación y
   normalización dentro del camino del cliente antes de persistir.
   Confirmado en producción (fila 531): el clasificador devuelve
   `normalized_value` igual al `raw_value` — no normaliza a enum.
4. **Sanitización de `input_payload` por allowlist:**
   `TELEMETRY_SAFE_KNOWN_FIELDS` (hoy: `event_type`,
   `preferred_visit_date`). Política fail-closed: clave no listada no se
   persiste, sea de contacto o no. Añadir claves a telemetría es decisión
   explícita, no efecto colateral.
5. **Caching de structlog condicionado:** `cache_logger_on_first_use` solo
   en producción. Precondición documentada de
   `structlog.testing.capture_logs`: loggers no cacheados.
6. **Regla de captura en tests:** el captor vive en el mismo pipeline que
   el emisor — stdlib se aserta con `caplog`, structlog con
   `capture_logs`; todo test que cruce el puente depende de config global
   y orden de ejecución (pasa por accidente). `caplog` quedó erradicado de
   aserciones de eventos structlog. Emisor stdlib residual conocido:
   `app/ai/schemas.py` (`ai_invalid_information_category`) — backlog,
   nadie lo aserta hoy.
7. **Focal en Windows:** el pytest focal pre-push solo incluye tests
   colectables sin PostgreSQL; para la suite con DB, CI del PR ES el focal
   (los SHAs validados llegan bit a bit idénticos al merge ff-only). Un
   focal que no puede pasar localmente no es gate.
8. **`DEFAULT_INTENT_MODEL` es letra muerta:** producción usa
   `google/gemini-2.5-flash-lite` vía settings (confirmado por
   `SELECT DISTINCT model`); el default `openai/gpt-4o-mini` en `client.py`
   nunca aplica. Backlog: alinearlo o eliminarlo.

## 8. Garantía W2-a para entradas no-texto (2026-08-25)

`input_character_count = 0` es inalcanzable desde W2-a: los mensajes no-texto sin caption
se resuelven antes del cliente de IA; los que tienen caption clasifican únicamente texto no
vacío. Como defensa adicional, `OpenRouterIntentClient` lanza
`EmptyClassificationInput` antes de HTTP y antes de insertar `ai_execution` si recibe una
cadena vacía o compuesta solo por espacios.
