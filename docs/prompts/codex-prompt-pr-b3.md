# Prompt Codex — PR-B.3: la confirmación humana como uplift definitivo de confianza

**Branch:** `pr-b3-confirmation-uplift` (desde `main` post-merge de PR #13). **Ubicación:** `docs/prompts/codex-prompt-pr-b3.md`. **Rectores:** `intents.md` §25 (bandas), `flows.md` FL-026, `business-rules.md` BR-AI-004, patrón de rescate de PR-B.2 (`AI_CONFIDENCE_DECISION` en `audit_event`), `AGENTS.md`.

## Bug diagnosticado (censo PR-B.2, punto 5)

Cuando la banda incierta guarda la clasificación en `pending_confirmation` y el cliente responde afirmativamente, `resolve_pending_confirmation` recupera la clasificación guardada — que conserva su confianza original (p. ej. 0.65) — y esta **re-entra a la evaluación de bandas**, cayendo de nuevo en la banda incierta y re-encolando `RESP-FALLBACK-004`. El cliente confirma y recibe la misma pregunta. El test existente usa 0.72 y no lo detecta.

## Principio rector del fix

La confirmación explícita del cliente es el uplift definitivo: una clasificación recuperada por afirmación NO se re-evalúa contra las bandas — se despacha como confiada, con decisión del backend auditada (`AI_CONFIDENCE_DECISION` / `CONFIRMATION_UPLIFT`, hermana simétrica del `UNCERTAIN_ENTITY_RESCUE` de B.2). El uplift aplica a TODAS las intenciones de manera uniforme, incluidas las sensibles: si el cliente confirma una `EMERGENCY@0.6`, el flujo sensible procede — eso es exactamente lo que la confirmación significa. La fila original de `ai_execution` no se toca (dos capas: el LLM propuso, el backend decidió tras confirmación humana).

## Fase G1 — Censo (solo lectura)

1. Mecánica exacta de `resolve_pending_confirmation`: cómo detecta la afirmación, qué recupera, dónde reinyecta la clasificación, y el punto preciso donde la recuperada re-entra a la evaluación de bandas.
2. ¿Existe hoy algún tope al bucle? (¿`failed_understanding_count` incrementa en la banda incierta? ¿escala a handoff tras N vueltas, o es infinito?). Reporta el peor caso actual con precisión.
3. ¿Qué respuesta del cliente cuenta como "afirmativa" para la resolución, y qué pasa con respuestas ambiguas ("sí, una boda")? ¿La clasificación nueva del turno afirmativo se descarta o se fusiona?
4. `RESP-FALLBACK-004` es pregunta abierta ("cuéntame un poquito más"), no sí/no. Reporta si existe evidencia (tests, docs, forense) de clientes respondiendo afirmativamente a esa pregunta abierta — para dimensionar si el bucle es teórico o activo. NOTA: el fix procede igual en ambos casos; esto solo calibra urgencia de un posible cambio de plantilla (que sería decisión de Leandro, NO de este PR).
5. Propuesta de inserción exacta del uplift (flag en la clasificación recuperada, marca de procedencia estilo `confidence_entity_rescued`, u otro mecanismo — con preferencia por procedencia backend explícita, no por mutar `confidence`), y sitio de la auditoría.
6. Inventario de tests existentes de `pending_confirmation`/bandas que deben permanecer intactos.

**GATE G1: DETENTE y reporta.**

## Fase G2/G3 — tras aprobación del censo

Suite roja TC-B3 con al menos: el bucle reproducido (clasificación@0.65 confirmada → hoy re-pregunta; esperado: despacho + auditoría `CONFIRMATION_UPLIFT`, sin segundo `RESP-FALLBACK-004`), fixture con confianza bajo 0.70 (el hueco del test de 0.72), respuesta no afirmativa → comportamiento actual intacto, intención sensible confirmada → flujo sensible procede, uplift NO aplica a clasificaciones no recuperadas (las bandas siguen intactas para turnos frescos), y regresión completa de TC-B2. Mismo protocolo de gates y certificación condicional de los ciclos anteriores. Los TC exactos se fijan en la enmienda post-censo.

## Fuera de alcance

Cambiar `RESP-FALLBACK-004` o su carácter abierto (decisión de producto), tocar umbrales, tocar el rescate B.2, generalizar más allá del camino de confirmación.

---

# Enmienda 1 al prompt PR-B.3 — Resoluciones G1 y autorización G2/G3

GATE G1 **APROBADO**; censo adoptado como anexo normativo.

## R-B3-1 — Inserción (propuesta del censo aprobada)

`PendingConfirmationResolution(classification, confirmation_uplifted)` como retorno estructurado de `resolve_pending_confirmation`. Con `confirmation_uplifted=True`: normalización de entidades normal, omisión COMPLETA de ambos gates de confianza (seguro por construcción: solo llegan a `pending_confirmation` clasificaciones en [UNCERTAIN, PROBABLE)), despacho por `route_classification` uniforme para todas las intenciones, sensibles incluidas. Sin mutación de `confidence` ni `reasoning_code` de la clasificación recuperada.

## R-B3-2 — Auditoría (aprobada como propuesta)

Se conserva `AI_CONFIRMATION_ACCEPTED` y se agrega `AI_CONFIDENCE_DECISION` con `reason=CONFIRMATION_UPLIFT` y payload: `decision`, `confirmed_intent`, `original_global_confidence`, `original_reasoning_code`, `last_question_code`, `conversation_id`; `request_id` en su columna. Las filas de `ai_execution` (la original Y la del turno afirmativo descartado) permanecen intactas — tres capas visibles en el forense: lo que el LLM propuso dos veces, y lo que el backend decidió por confirmación humana.

## R-B3-3 — `pending_action`

Si al aceptar la confirmación `pending_action` sigue en `CLASSIFY_MESSAGE`, se limpia antes del despacho; el handler destino fija la siguiente. La restauración de la `pending_action` PREVIA al turno incierto queda EXPRESAMENTE fuera de alcance → entrada de backlog: "persistir/restaurar pending_action previa en el payload de pending_confirmation".

## R-B3-4 — Vocabulario intocado + backlog

`is_affirmative` no se modifica. Entrada de backlog: "«Sí.» con puntuación no es afirmativo — normalización de puntuación en is_affirmative requiere censo de semántica de confirmaciones (candidato M2)". Ambas entradas de backlog van en el commit docs de G3.

## Suite TC-B3 (G2)

- **TC-B3-001** (el bucle, caso canónico): clasificación `EVENT_INFORMATION@0.65` con entidad almacenada en `pending_confirmation`, `pending_action=CLASSIFY_MESSAGE`; turno "sí" → la clasificación recuperada se despacha (entidad aplicada al evento), auditorías `AI_CONFIRMATION_ACCEPTED` + `CONFIRMATION_UPLIFT` presentes, **cero** segundo `RESP-FALLBACK-004`, **cero** segundo `ASK_CONFIRMATION`, `pending_confirmation` limpio, `pending_action` ya no es `CLASSIFY_MESSAGE`.
- **TC-B3-002**: segundo "sí" posterior al uplift (sin `pending_confirmation` vigente) → tratamiento fresco normal, sin crash ni re-uplift.
- **TC-B3-003**: respuesta NO afirmativa ("es para diciembre") → clasificación nueva del turno gobierna, `pending_confirmation` descartado, comportamiento actual intacto.
- **TC-B3-004**: `EMERGENCY@0.6` (o sensible equivalente) almacenada y confirmada → flujo sensible procede con uplift auditado — la confirmación vence a las bandas también aquí.
- **TC-B3-005**: clasificación fresca en banda incierta (sin origen en confirmación) → `ASK_CONFIRMATION` + `RESP-FALLBACK-004` como hoy; el uplift NO alcanza turnos no recuperados.
- **TC-B3-006**: las dos filas de `ai_execution` del ciclo (original y turno afirmativo) conservan sus valores literales tras el uplift.
- Confianza de los fixtures: **bajo 0.70** (cierra el hueco del test de 0.72).
- Inventario de regresión del censo (los siete grupos listados) sin ediciones.

## Protocolo

Idéntico a los ciclos anteriores: Commit 0 docs (prompt + enmienda + entradas de backlog), suite roja, push + PR draft, rojos por causas admitidas con conteo del CI, cero verdes prematuros, preexistentes verdes → certificación condicional → G3 directo. Esqueleto mínimo (`PendingConfirmationResolution` con firma) autorizado si la colección lo exige, sin lógica. Reporte final con transición rojo→verde y desviaciones.
