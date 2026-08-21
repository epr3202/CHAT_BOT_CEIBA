# Slice PR-A — Observabilidad de ejecuciones de IA (`ai_execution`)

**Estado:** APROBADO para G1 — Emerson, 2026-08-21.
**Ubicación propuesta:** `docs/product/ai-execution-observability.md`.
**Motivación:** expediente de 3 fallos de clasificación diagnosticados a ciegas
(handoff 2026-08-21): `event_type` no extraído de "la boda de siglo que quiero
realizar"; "Solo espacio" ×2 no clasificado como respuesta de servicios;
colapso "boda civil"→WEDDING del 2026-08-20. Sexta jornada mordida por la
falta de persistencia del output del clasificador.
**Suite roja de partida:** TC-AIEXEC-001..004 en la rama
`rescue-adversarial-suites` (commit `13c0e9f`), a extender según §5.

---

## 1. Tabla `ai_execution`

Append-only (mismo régimen que `message` y `audit_event`). Modelo registrado
en `app/models_registry.py`. Primera migración desde `20260819_0021`.

| Campo | Tipo | Nullable | Notas |
| --- | --- | --- | --- |
| `id` | UUID PK | no | |
| `created_at` | timestamptz | no | default now(), no editable |
| `request_id` | UUID | sí | nace en el webhook handler; NULL solo para ejecuciones fuera de ciclo HTTP (scripts, backfills) |
| `external_message_id` | texto | sí | referencia lógica al mensaje disparador; SIN FK dura (decisión: tabla append-only, la integridad la garantiza el flujo; el censo G1 debe confirmar que no existe patrón FK previo contra `message` que convenga imitar) |
| `task` | enum | no | `INTENT_CLASSIFICATION`, `SERVICES_CLASSIFICATION`, `EVENT_TYPE_EXTRACTION` — extensible por migración |
| `model` | texto | no | string del modelo OpenRouter usado |
| `prompt_version` | texto | no | etiqueta versionada del prompt (§3) |
| `input_payload` | JSONB | no | texto del usuario + contexto: pregunta pendiente, estado conversacional. SIN datos de contacto (teléfono/nombre) — el vínculo es `external_message_id` |
| `raw_output` | texto | sí | output crudo sin parsear; NULL solo si la llamada falló antes de respuesta |
| `parsed_output` | JSONB | sí | resultado post-validación; NULL si no parseable |
| `validation_status` | enum | no | `VALID`, `INVALID_SCHEMA`, `NORMALIZED`, `DISCARDED`, `HTTP_ERROR` |
| `latency_ms` | entero | sí | |
| `error` | texto | sí | mensaje de excepción si aplica |

### Semántica de `validation_status`

* `VALID`: output parseó y pasó validación sin transformación.
* `NORMALIZED`: pasó por fallback (p. ej. `normalize_event_type` en cascada).
* `INVALID_SCHEMA`: output no cumple el esquema esperado (JSON malformado,
  códigos fuera de catálogo); el valor se descarta aguas arriba.
* `DISCARDED`: esquema válido pero valor rechazado por regla de negocio.
* `HTTP_ERROR`: la llamada a OpenRouter falló; `raw_output` NULL, `error`
  poblado.

## 2. Contrato de persistencia

1. La llamada HTTP a OpenRouter ocurre FUERA de toda transacción DB abierta
   (invariante AGENTS.md vigente; TC-AIEXEC lo asertará explícitamente).
2. La persistencia de `ai_execution` es una transacción propia, posterior al
   retorno (o fallo) HTTP. Best-effort: envuelta en try/except; un fallo de
   persistencia emite WARNING estructurado
   (`ai_execution_persist_failed`, con `request_id` y `task`) y NUNCA
   interrumpe la clasificación ni el flujo del usuario.
3. Sin constraint UNIQUE sobre `external_message_id`: un mensaje puede
   disparar varias tareas de IA legítimamente. La idempotencia del handler
   vive aguas arriba y no cambia.
4. Se persiste TODA ejecución, incluidas las fallidas (`HTTP_ERROR`): los
   fallos son precisamente el dato que el expediente necesita.

## 3. `request_id` y versionado de prompts

* `request_id` se genera en el webhook handler (UUID v4, uno por request
  entrante) y se propaga como PARÁMETRO EXPLÍCITO por la cadena
  orquestador → cliente de IA. Prohibido contextvar/global. Callers fuera de
  ciclo HTTP pasan `None` visible.
* Cada prompt vive con una constante `PROMPT_VERSION` adyacente (formato
  `<task>-vN`, p. ej. `intent-v3`). Cambiar el texto del prompt sin subir la
  versión es una desviación reportable. Esto habilita la comparación
  prompt-viejo vs prompt-nuevo que motiva el slice.

## 4. Logging estructurado del orquestador

Un record por decisión de orquestación, logger `ceiba.orchestrator`,
nivel INFO, campos fijos:

```text
request_id, intent, state_before, state_after, transition,
decision_source (DETERMINISTIC | LLM | FALLBACK), pending_action
```

`pending_action` se loguea tal como lo fija el orquestador desde el catálogo
oficial (invariante vigente: nunca copiado del clasificador). La suite
aserta sobre records vía `caplog.at_level` — NUNCA `capsys` (aprendizaje
del slice anterior).

## 5. Suite roja (G1 → G2)

Base: TC-AIEXEC-001..004 rescatados. Extensiones requeridas:

* TC-AIEXEC-005: `HTTP_ERROR` se persiste con `error` poblado y
  `raw_output` NULL.
* TC-AIEXEC-006: `prompt_version` y `model` presentes en toda fila.
* TC-AIEXEC-007: `request_id` propagado extremo a extremo desde el webhook
  (aserción sobre la fila persistida, no sobre mocks intermedios).
* TC-AIEXEC-008: dos tareas del mismo mensaje → dos filas con el mismo
  `external_message_id` (sin colisión UNIQUE).
* TC-LOG-001..N: esquema de campos del logging del orquestador (§4) para
  al menos un camino DETERMINISTIC, uno LLM y uno FALLBACK.
* TC-PARITY-001: paridad metadata SQLAlchemy ↔ migración Alembic para la
  tabla nueva (gate obligatorio; ya reprodujimos un P0 por divergencia).

## 6. Fuera de alcance de PR-A

* Cualquier cambio de prompts o de modelo (bloqueado hasta tener datos).
* Clasificación de servicios y extracción de event_type (PR-B; requiere
  este PR mergeado).
* Panel/consulta de `ai_execution` en admin (backlog; SQL directo basta
  para el expediente).
* Retención/purga de `ai_execution` (backlog; anotar volumen estimado en
  G3 para dimensionar).
