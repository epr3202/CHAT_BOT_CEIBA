# Prompt Codex — PR-B.1: disparador de extracción e interrupciones en captura de servicios

**Branch:** `pr-b1-extraction-trigger-and-interruptions` (desde `main` post-merge de PR-B).
**Ubicación:** `docs/prompts/codex-prompt-pr-b1.md`.
**Rectores:** `docs/conversation/flows.md` (FLOW-GEN-005), `docs/product/services-catalog.md`, prompt PR-B + enmiendas 1–4, `AGENTS.md`.

## Motivación empírica (jornada 2026-08-24)

- `EVENT_TYPE_EXTRACTION` tiene **cero filas** en `ai_execution` de producción: el disparador (`pending_action == COLLECT_EVENT_TYPE`) nunca se cumple en los caminos reales. "La boda" falló dos veces en el primer turno post-saludo, donde ese pending_action no existe.
- Durante `COLLECT_SERVICES`, el camino dirigido puentea al clasificador general: pagos, quejas, emergencias, cancelaciones y solicitudes de asesor caen en repregunta de servicios (FLOW-GEN-005 violado). El parche `is_explicit_visit_request` de `6b25359` es síntoma de este diseño.
- El summary de confirmación no respeta el orden de captura del cliente ("Espacio y gastronomía" → "la gastronomía y el espacio").
- La repregunta de servicios comparte `failed_understanding_count` con el entendimiento general: fallos previos del turno general pueden saltar la repregunta directo a `OTHER`.

## Decisión de negocio registrada (NO tocar)

"Todo incluido" y expresiones de modalidad total se clasifican vía `SERVICES_CLASSIFICATION` con el comportamiento actual (expansión a códigos que el LLM determine). Decisión de Leandro/Emerson 2026-08-24: aceptado como está. Commit docs: agregar esta nota a `services-catalog.md` (v1.1, nota en §4) para que quede como comportamiento documentado, no como gap.

## Alcance (cerrado)

1. **Disparador ampliado de `EVENT_TYPE_EXTRACTION` (R-B1-1).** `should_extract_event_type` deja de anclarse solo en `pending_action == COLLECT_EVENT_TYPE` y pasa a: (clasificación general por camino LLM sin entidad `event_type` válida) AND (posición conversacional que espera tipo de evento, definida por `last_question_code` ∈ conjunto de plantillas que preguntan el tipo — incluye el saludo — OR `pending_action == COLLECT_EVENT_TYPE`). El conjunto exacto de códigos sale del censo G1 y queda como constante nombrada con comentario que referencia este prompt.
2. **Interrupciones prioritarias en `COLLECT_SERVICES` (R-B1-2).** Reordenar el turno dirigido: matcher determinista → (sin match) → clasificador GENERAL (`classify_intent`) → gate por intención:
   - Intención de FLOW-GEN-005 (`PAYMENT_MESSAGE`, `COMPLAINT`, `EMERGENCY`, `EVENT_CANCELLATION`, `HUMAN_REQUEST`) o intención de visita → despachar al flujo correspondiente con la clasificación general; `pending_action = COLLECT_SERVICES` se conserva para reanudación donde el flujo interrumpido lo permita (mismo régimen que FAQ intermedia).
   - Cualquier otra intención (respuesta de servicios en lenguaje libre, UNKNOWN) → `SERVICES_CLASSIFICATION` como hoy, y de ahí la cadena repregunta → `OTHER` sin cambios.
   - **Eliminar `is_explicit_visit_request`** y su llamada: el clasificador general cubre visitas. TC-WIRE-002/003 deben seguir verdes sin editar sus tests.
   - El matcher determinista conserva precedencia absoluta: si hay match, no hay ninguna llamada LLM (invariante de PR-B intacto).
3. **Contador propio de repregunta de servicios (R-B1-3).** La cadena repregunta→`OTHER` deja de leer/escribir `failed_understanding_count` y usa un contador dedicado. Preferencia: campo en JSON existente de la conversación si el censo encuentra uno idóneo; si se requiere columna nueva, DETENTE en G1 y propón la migración mínima (una columna aditiva nullable) para autorización explícita.
4. **Orden de captura en el summary (R-B1-4).** `compose_requested_services_summary` recibe los códigos en el orden de captura del cliente y lo respeta. El censo identifica dónde se pierde hoy el orden (query, matcher o composición).

## Invariantes (sin cambios, re-enunciados)

Determinista precede a LLM; la IA solo propone; HTTP fuera de transacciones; plantillas aprobadas únicamente; append-only; idempotencia; instrumentación `ai_execution` en todo camino nuevo; prohibido push a `main`; el CI es el gate de pytest (Enmienda 2 de PR-B rige igual aquí, esqueletos autorizados bajo las mismas condiciones); desviaciones declaradas o DETENTE.

## Fase G1 — Censo (solo lectura)

1. Valores reales de `last_question_code` cuando el bot pregunta el tipo de celebración: código del saludo (RESP-GREETING-001 u otro), código(s) de `COLLECT_EVENT_TYPE` en slot_filling, y cualquier otra plantilla que elicite tipo. Lista exacta.
2. ¿El orquestador consume `directed_event_type` en posiciones fuera de `COLLECT_EVENT_TYPE` (p. ej. primer turno con creación de lead)? Ruta exacta del consumo y qué falta para que la propuesta extraída se aplique en el turno del saludo.
3. Intenciones exactas del enum/clasificador para las cinco interrupciones de FLOW-GEN-005 y las de visita, y el punto del orquestador donde cada una despacha hoy — el gate de R-B1-2 debe reutilizar ese despacho, no duplicarlo.
4. Referencias actuales a `is_explicit_visit_request` (código y tests).
5. Almacenamiento para el contador R-B1-3: ¿existe JSON de conversación apto o se necesita columna?
6. ¿Dónde se pierde el orden de captura del summary? (orden del matcher, orden de inserción, `order_by` de la query, o composición).
7. Reanudación post-interrupción: ¿qué mecanismo existente restaura `COLLECT_SERVICES` tras una FAQ (TC-COLLECT-011) y aplica igual tras las interrupciones nuevas?

**GATE G1: DETENTE y reporta.**

## Fase G2 — Suite roja TC-B1 (tras aprobación de G1)

Derivada de flows.md y de este prompt; mínimos:

- **TC-B1-001**: "La boda" como respuesta al saludo (literal del fallo) → `EVENT_TYPE_EXTRACTION` invocada → `WEDDING` aplicado, sin repregunta genérica; fila `ai_execution` con task y `prompt_version=event_type_extraction_v1`.
- **TC-B1-002**: "Una boda" al saludo → el general resuelve → extracción NO invocada (cero LLM extra).
- **TC-B1-003**: regresión — el camino `COLLECT_EVENT_TYPE` formal sigue disparando (TC-EXT-004/005 de PR-B intactos, sin editar).
- **TC-B1-004**: "Ya pagué" durante `COLLECT_SERVICES` → flujo de pago (comprobante/`PAYMENT_REVIEW`/handoff según flujo vigente), NO repregunta de servicios.
- **TC-B1-005**: "quiero hablar con un asesor" durante `COLLECT_SERVICES` → handoff; conversación no pierde el contexto de captura.
- **TC-B1-006**: solicitud de visita durante `COLLECT_SERVICES` → flujo de visita, con `is_explicit_visit_request` ya eliminado; TC-WIRE-002/003 verdes sin ediciones.
- **TC-B1-007**: "quiero cancelar el evento" durante `COLLECT_SERVICES` → flujo de cancelación (la válvula del backlog).
- **TC-B1-008**: respuesta libre de servicios sin match ("quiero que todo se vea inolvidable") → general → gate → `SERVICES_CLASSIFICATION`; exactamente una llamada a cada tarea.
- **TC-B1-009**: match determinista → cero llamadas LLM (regresión del invariante, TC-SVC-001 intacto).
- **TC-B1-010**: aislamiento del contador — `failed_understanding_count` preexistente > 0 no salta la repregunta de servicios; primera falla de servicios → `RESP-SERVICES-RETRY-001`, segunda → `OTHER`.
- **TC-B1-011**: orden — "Espacio y gastronomía" → summary "el espacio y la gastronomía"; tres servicios conservan orden de mención.
- Paridad de instrumentación: las interrupciones despachadas registran su clasificación general en `ai_execution` como cualquier turno LLM.

Commit de suite, **GATE G2**: rojo por aserciones/NotImplementedError vía CI en PR draft, conteo exacto, cero verdes prematuros en TC nuevos, DETENTE. Certificación condicional idéntica a Enmienda 4 §3 de PR-B: condiciones cumplidas → procede a G3 sin nueva autorización.

## Fase G3 — Implementación

Corte propuesto (ajustable en reporte G1): (1) docs — nota "todo incluido" v1.1 + este prompt; (2) disparador ampliado; (3) gate de interrupciones + eliminación de `is_explicit_visit_request`; (4) contador dedicado; (5) orden del summary. Verde total en CI, reporte final con tabla rojo→verde, run del CI, desviaciones declaradas o ninguna.

---

# Enmienda 1 al prompt PR-B.1 — Aprobación G1 y autorización G2

GATE G1 **APROBADO** con las resoluciones siguientes. El censo se adopta como anexo normativo.

## 0. Precondición de rama — resolución

`origin/main` SÍ contiene el merge de PR-B (verificado empíricamente: producción registra `SERVICES_CLASSIFICATION`/`services_v1` en `ai_execution`). El `main` local está rancio. Secuencia:

```bash
git fetch origin
git log --oneline origin/main -3   # debe mostrar el merge de PR #11 encima de 30ab668
git checkout main && git pull --ff-only
git checkout -b pr-b1-extraction-trigger-and-interruptions
```

Si `origin/main` NO contiene el merge de PR #11: DETENTE y reporta — sería una inconsistencia grave entre remoto y producción.

## R-B1-5 — Migración 0023 aprobada, con DOS columnas

Una única migración aditiva:

1. `conversation.services_failed_understanding_count INTEGER NULL` — semántica propuesta en el censo aceptada (NULL ≡ 0; reinicio al capturar con éxito o salir de la captura).
2. `event_service_request.position INTEGER NULL` — orden de mención del cliente (0-based por captura). Se RECHAZA la alternativa de timestamps sintéticos monotónicos: `created_at` conserva semántica de auditoría pura. `requested_services_summary()` ordena por `position NULLS LAST, created_at, id`; filas legacy (position NULL) degradan al orden actual.

Ambas columnas en el modelo SQLAlchemy Y en la migración (paridad metadata↔migración, trampa conocida). Downgrade incluido. Nada más en 0023.

## R-B1-6 — Puente contextual UNKNOWN → EVENT_INFORMATION

Aprobado el puente determinista del censo (punto 2), con guardas obligatorias:

1. Aplica ÚNICAMENTE cuando la clasificación general es `UNKNOWN` — jamás reinterpreta intenciones sensibles (`SENSITIVE_HANDOFF_INTENTS`), de visita (`VISIT_INTENTS`), ni ninguna otra.
2. Requiere `directed_event_type` válido (no None) Y `last_question_code ∈ EVENT_TYPE_QUESTION_CODES`.
3. La clasificación puenteada lleva `reasoning_code = "DIRECTED_EVENT_TYPE_BRIDGE"` para trazabilidad forense en `ai_execution`/contexto persistido.
4. Estructuralmente análogo a `services_turn_classification` (construcción determinista de `IntentClassification` con la entidad dirigida); el despacho posterior es el normal del orquestador, sin handlers nuevos.

## R-B1-7 — Conjunto del disparador

`EVENT_TYPE_QUESTION_CODES = frozenset({"RESP-GREETING-001", "RESP-EVENT-DATA-013", "RESP-PRICE-001"})` — aprobado tal como lo propone el censo. `RESP-CATALOG-002` EXCLUIDO (su flujo prohíbe inferencia libre; regla de flows.md citada en el censo). Los códigos documentados pero no emitidos (`RESP-DISCOVERY-*`, `RESP-PRICE-002`) quedan fuera; si algún día se emiten, la constante se revisa — deja comentario que lo diga.

## R-B1-8 — Redefinición de TC-B1-004/005 (interrupciones sensibles)

"No pierde contexto" significa: lead activo y `pending_fields` (incluido `requested_services`) sobreviven al handoff. `pending_action` pasa a `WAIT_FOR_HUMAN` conforme al diseño de pausa; NO se aserta conservación de `COLLECT_SERVICES` durante `HUMAN_ACTIVE`. Sin restauración automática post-retorno administrativo (comportamiento vigente, documentado). Para visitas SÍ se aserta el ciclo completo: interrupción → flujo de visita → `clear_visit_draft_and_resume_capture` reinstala `COLLECT_SERVICES` (TC-B1-006 lo cubre de punta a punta).

## Casos adicionales para G2

- **TC-B1-012**: `UNKNOWN` en posición de pregunta de tipo pero SIN `directed_event_type` (extracción devolvió None/DISCARDED) → `handle_unknown` normal, sin puente, sin entidad aplicada.
- **TC-B1-013**: intención sensible (p. ej. "Ya pagué") en respuesta al saludo → flujo sensible, el puente NO se evalúa aunque la posición sea de pregunta de tipo.
- **TC-B1-014**: paridad metadata↔migración de 0023 (las dos columnas existen en ambos lados; el patrón TC-PARITY vigente del repo).
- **TC-B1-015**: filas legacy de `event_service_request` con `position NULL` conviven con filas nuevas — el summary ordena nuevas por posición y legacy detrás, sin excepción.

## Cierre

Con `main` local actualizado y branch creado: Commit 0 (`docs:` prompt + esta enmienda + nota "todo incluido" v1.1 del catálogo), luego G2 bajo las mismas reglas de PR-B (Enmiendas 2–4 rigen: esqueletos acotados, rojo por CI en PR draft, certificación condicional, evidencia escalonada si aplica — aquí el escalón natural es la migración 0023, que puede viajar en G2 como scaffolding autorizado dado que los tests de paridad y contador la requieren para colectar). Conteo exacto de rojos, cero verdes prematuros, DETENTE solo si alguna condición falla.
