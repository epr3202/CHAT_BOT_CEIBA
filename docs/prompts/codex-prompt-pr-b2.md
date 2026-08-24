# Prompt Codex — PR-B.2: rescate de entidad en banda incierta de confianza

**Branch:** `pr-b2-confidence-entity-rescue` (desde `main` post-merge de PR-B.1). **Ubicación:** `docs/prompts/codex-prompt-pr-b2.md`. **Rectores:** régimen de confianza vigente (docs + settings `AI_CONFIDENCE_*`), prompts PR-B/PR-B.1 con enmiendas, `AGENTS.md` (política de push ya corregida: branches libres, `main` solo por PR).

## Causa raíz diagnosticada (forense de producción, 2026-08-24, fila `ai_execution` 3120)

"La boda" como respuesta al saludo produce clasificación general `primary_intent=EVENT_INFORMATION`, entidad `event_type` normalizable con confianza **0.9**, pero confianza global **0.65** → banda incierta (< `AI_CONFIDENCE_PROBABLE`=0.70) → el orquestador emite `RESP-FALLBACK-004` con `pending_action=CLASSIFY_MESSAGE` y **descarta la entidad**. El disparador de extracción de PR-B.1 correctamente no aplica (hay entidad válida) y el puente UNKNOWN correctamente no aplica (la intención no es UNKNOWN). El payload completo de entrada y salida está registrado en las filas 3119–3122; la 3120 es el caso canónico.

## Alcance (cerrado)

**R-B2-1 — Rescate determinista de entidad en posición dirigida.** En el mismo punto del pipeline donde vive `directed_event_type_bridge_classification`, agregar la regla: si la clasificación cae en banda incierta del régimen de confianza Y `last_question_code ∈ EVENT_TYPE_QUESTION_CODES` Y existe entidad `event_type` con `quality_status != "INVALID"`, confianza de entidad ≥ `AI_CONFIDENCE_SAFE` y `normalize_event_type` válido → la clasificación se promueve a despacho confiado de `EVENT_INFORMATION` con esa entidad, `reasoning_code="UNCERTAIN_ENTITY_RESCUE"` y trazabilidad en `context_reference` (confianza global original, confianza de entidad). Fuera de esas condiciones, el régimen de confianza actual queda EXACTAMENTE igual — el rescate es una excepción acotada a posición dirigida + entidad fuerte, no una relajación general de las bandas.

**R-B2-2 — Fixture de payload real.** El TC principal reproduce el turno con el `input_payload` y `parsed_output` LITERALES de la fila 3120 (contexto: `last_intent=GREETING`, `last_question_code=RESP-GREETING-001`, `pending_action=null`; salida: EVENT_INFORMATION@0.65 con entidad wedding@0.9 y `reasoning_code=CONTEXTUAL_EVENT_TYPE`). Copiarlos textuales de este prompt/expediente, no reconstruirlos.

## Fase G1 — Censo (solo lectura)

1. Punto exacto donde la banda incierta despacha hoy: dónde se compara `confidence` contra los umbrales, qué handler emite `RESP-FALLBACK-004` y fija `CLASSIFY_MESSAGE`, y si la entidad se descarta antes o después de esa decisión.
2. ¿El régimen de confianza está documentado en docs/ (bandas, semántica)? Ruta exacta — el rescate necesita su delta documental correspondiente.
3. ¿Existe ya alguna excepción o uplift al régimen de confianza (precedente de diseño)?
4. Confirmar que `normalize_event_type("wedding")` (minúscula, como lo devuelve el LLM) normaliza a `WEDDING` — y si no, reportarlo como sub-hallazgo.
5. ¿Qué pasa con `pending_action=CLASSIFY_MESSAGE` en el turno siguiente? (para entender el flujo que el rescate cortocircuita y verificar que no rompemos su reanudación).

**GATE G1: DETENTE y reporta**, incluyendo tu propuesta de inserción exacta.

## Fase G2 — Suite roja TC-B2 (tras aprobación)

- **TC-B2-001**: replay literal de la fila 3120 (R-B2-2) → entidad aplicada, evento con `event_type=WEDDING`, siguiente slot preguntado, sin `RESP-FALLBACK-004`; `reasoning_code=UNCERTAIN_ENTITY_RESCUE` en contexto persistido.
- **TC-B2-002**: misma posición, entidad con confianza 0.7 (< SAFE) → comportamiento actual intacto (aclaración).
- **TC-B2-003**: confianza global incierta SIN posición dirigida (`last_question_code` ajeno) → comportamiento actual intacto.
- **TC-B2-004**: confianza global ≥ PROBABLE → el rescate no interviene (camino confiado normal, cero cambios).
- **TC-B2-005**: entidad no normalizable en posición dirigida con banda incierta → aclaración actual (el rescate exige normalización).
- **TC-B2-006**: banda incierta con intención sensible y entidad `event_type` presente → flujo sensible intacto, sin rescate.
- Regresión: TC-B1-001/012/013 y el conjunto de PR-B intactos sin ediciones.

Mismo protocolo de gates que PR-B.1 (rojo por CI en PR draft, causas admitidas, cero verdes prematuros, certificación condicional, esqueleto mínimo si hace falta para colección). G3 tras certificación, reporte final con transición rojo→verde y desviaciones.

## Fuera de alcance

No tocar umbrales `AI_CONFIDENCE_*`, no generalizar el rescate a otras entidades o posiciones (si el censo sugiere generalización, reportarla como propuesta para decisión del arquitecto, no implementarla), no modificar el puente UNKNOWN ni el disparador de extracción de PR-B.1.

---

# Enmienda 1 al prompt PR-B.2 — Resoluciones G1 y autorización de G2

GATE G1 **APROBADO**. Censo adoptado como anexo normativo, incluida la inserción propuesta en `inbound.py` post-puente y la construcción de `IntentClassification` nueva (no `model_copy`) con solo la entidad rescatada.

## R-B2-3 — Calidad de entidad (resolución 1)

El rescate exige `quality_status ∈ {"PROVIDED", "CORRECTED"}` **y** `needs_confirmation == False`. `INFERRED` y `PENDING_CONFIRMATION` quedan EXCLUIDOS (coherente con el descarte existente de `event_type@INFERRED` en el orquestador y con la distinción extracción/confirmación de entities.md). La redacción `!= INVALID` de R-B2-1 queda sustituida por esta.

## R-B2-4 — Trazabilidad (resolución 2)

`audit_event` con `event_type_name = "AI_CONFIDENCE_DECISION"`, decisión `UNCERTAIN_ENTITY_RESCUE`, y payload con `original_global_confidence`, `rescued_entity_confidence`, `last_question_code`, `original_reasoning_code` y `conversation_id`/`request_id` según el patrón de `audit_domain_change`. La fila de `ai_execution` NO se toca: debe seguir reflejando el veredicto literal del LLM (confianza 0.65) — el rescate es decisión del backend y las dos capas deben ser distinguibles en el forense. TC-B2-001 aserta la fila de auditoría.

## R-B2-5 — Fixture literal de la fila 3120 (resolución 3)

Transcripción exacta del SELECT de producción (2026-08-24). Usar TEXTUAL en TC-B2-001; prohibido reconstruir o "mejorar":

`input_payload`:

```json
{"context": {"last_intent": "GREETING", "known_fields": {}, "pending_action": null, "last_question_code": "RESP-GREETING-001", "pending_confirmation": null, "failed_understanding_count": 0}, "message_text": "La boda"}
```

`parsed_output`:

```json
{"entities": {}, "priority": "NORMAL", "confidence": 0.65, "sub_intent": null, "needs_human": false, "handoff_reason": null, "missing_fields": [], "primary_intent": "EVENT_INFORMATION", "reasoning_code": "CONTEXTUAL_EVENT_TYPE", "requested_action": null, "context_reference": {"pending_action": null, "last_question_code": "RESP-GREETING-001"}, "secondary_intents": [], "extracted_entities": [{"entity": "event_type", "raw_value": "boda", "confidence": 0.9, "quality_status": "PROVIDED", "normalized_value": "wedding", "validation_errors": [], "needs_confirmation": false}], "needs_confirmation": false, "information_category": null}
```

El mock del clasificador general en TC-B2-001 devuelve `IntentClassification.model_validate(parsed_output)` de ese JSON, y el estado conversacional sembrado reproduce el `context` del `input_payload` (cliente con `last_question_code=RESP-GREETING-001` recién saludado).

## Casos ajustados/adicionales para G2

- TC-B2-001 según R-B2-5, asertando además la fila `audit_event` de R-B2-4 y que `ai_execution` conserva 0.65 sin alteración.
- **TC-B2-007**: entidad `event_type@INFERRED` con confianza 0.9 en posición dirigida y banda incierta → SIN rescate, aclaración actual (guarda R-B2-3).
- **TC-B2-008**: entidad `PROVIDED` pero `needs_confirmation=True` → SIN rescate.
- TC-B2-002…006 del prompt original sin cambios.

## Delta documental (commit docs de G3, primero)

`intents.md` §25.3 (excepción acotada con guardas exactas), `flows.md` FL-026 (rescate antes del fallback), `business-rules.md` BR-AI-004 (precisión), `conversation-test-cases.md` (TC-B2-001…008).

## Backlog registrado (NO implementar en B.2)

Bucle de confirmación a 0.65: una clasificación recuperada por `resolve_pending_confirmation` tras afirmación del cliente re-entra a la banda incierta y re-encola `RESP-FALLBACK-004`. Fix conceptual futuro: la confirmación humana es uplift definitivo — la clasificación confirmada debe saltar la evaluación de bandas. Requiere censo propio (afecta todas las intenciones). Anotar en `pending`/backlog del repo dentro del commit docs.

## Cierre

Con esto, G2 procede: branch `pr-b2-confidence-entity-rescue` desde `main` (`8ece540`), Commit 0 docs (prompt + enmienda), suite roja, push + PR draft (política de AGENTS.md vigente), certificación condicional idéntica a los ciclos anteriores (rojos por causas admitidas, cero verdes prematuros, preexistentes verdes → G3 directo sin nueva autorización; cualquier incumplimiento → DETENTE). Reporte final con transición rojo→verde y desviaciones.
