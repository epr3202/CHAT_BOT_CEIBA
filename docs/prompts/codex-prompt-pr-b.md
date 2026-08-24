# Prompt Codex — PR-B: services classification + event_type extraction

**Branch:** `services-classification-and-event-type-extraction` (desde `main`, que debe incluir `6ad9310` + el commit docs con la enmienda v1.1.1 del rector).
**Ubicación de este prompt en el repo:** `docs/prompts/codex-prompt-pr-b.md`.
**Documentos rectores:** `docs/product/services-catalog.md` (v1.0, fuente única), `docs/product/ai-execution-observability.md` (rector v1.1 + enmienda v1.1.1), `docs/conversation/entities.md` §13.2, `AGENTS.md`.

## Contexto y motivación empírica

Tres fallos de producción diagnosticados por SELECT sobre `ai_execution`:

1. Fila 532: respuesta "Espacio y gastronomía" a la pregunta directa de servicios quedó capturada **verbatim** en `requested_services`, sin códigos.
2. "Solo espacio" no se clasificó como respuesta de servicios.
3. "la boda de siglo que quiero realizar" falló la extracción de `event_type` (el label mostrado después vino de estado persistido viejo, no del clasificador — ese arrastre es ítem de backlog aparte, NO lo toques en este PR).

## Alcance (cerrado)

1. **Match determinista A7-bis para servicios** contra los aliases de `services-catalog.md`, activo **solo** cuando hay pregunta directa de servicios pendiente en el estado conversacional. Reglas exactas del catálogo §4: normalización (lowercase, sin tildes, sin puntuación terminal), match por palabra completa, **longest-match-first**, múltiples servicios por respuesta válidos, **negación adyacente a un alias ("no", "sin", "excepto", "menos") → NO resolver determinista, pasa al LLM con contexto completo**.
2. **Tarea `SERVICES_CLASSIFICATION`** en el cliente de IA: salida JSON de conjunto cerrado (códigos de `entities.md` §13.2 exclusivamente). Descripciones del prompt derivadas del campo Descripción del catálogo. Código fuera del conjunto → descartado y registrado; nunca propaga a dominio.
3. **Tarea `EVENT_TYPE_EXTRACTION`**: la normalización a enum canónico ocurre **DENTRO del cliente** (reusa `normalize_event_type`/`resolve_catalog_event_type_label` existentes), activando los estados `NORMALIZED`/`DISCARDED` del rector v1.1.1 en `ai_execution`.
4. **`RESP-SERVICES-RETRY-001`**: alta en `docs/review/approved-responses.md` con el texto exacto aprobado en catálogo §5, y en el seed de conocimiento como `APPROVED`. **Verifica que el código NO caiga en `NON_RENDERABLE_CODES` de `data/knowledge_seed.py`** (incidente previo con RESP-CATALOG-00x forzados a DRAFT).
5. **Composición determinista de `requested_services_summary`**: serialización con las formas de Presentación del catálogo, coma y "y" final, sin coma de Oxford. La composición vive del lado determinista de la frontera de presentación (`render_response` en `app/conversation/knowledge.py`); el LLM jamás compone texto a cliente.
6. **Test de paridad doc↔código**: los códigos del catálogo contra el enum/dict del módulo. Divergencia = rojo.

## Invariantes innegociables (AGENTS.md, re-enunciados)

- La IA solo propone códigos; toda ejecución y todo texto saliente es determinista desde plantillas aprobadas.
- Interpretación determinista SIEMPRE precede a la clasificación LLM (A7-bis/ter).
- Ninguna llamada HTTP (OpenRouter incluida) dentro de una transacción de DB abierta.
- `message` y `audit_event` append-only; handlers idempotentes por `external_message_id`.
- Todo modelo nuevo en `app/models_registry.py` (este PR no debería necesitar modelos nuevos ni migración — si descubres que sí, DETENTE y repórtalo en G1, no improvises).
- Instrumentación en `ai_execution` desde el día uno para ambas tareas nuevas: los propios tests e2e de este PR generan filas.
- Prohibido push a `main`; todo por PR. El CI de GitHub Actions es el gate verde (máquina sin Postgres local).
- NO toques: el arrastre de event_type de conversaciones viejas, `DEFAULT_INTENT_MODEL`, el emisor stdlib de `app/ai/schemas.py`, ni nada del backlog. Desviación fuera de alcance = desviación declarada en el reporte, no commit silencioso.

## Fase G1 — Censo (solo lectura, cero código)

Reporta con rutas y líneas:

1. Dónde se emite la pregunta directa de servicios y cómo se captura hoy la respuesta (el camino que produjo el verbatim de la fila 532). Qué marcador de estado/`pending_action` identifica "pregunta de servicios pendiente" — el guard del match determinista depende de esto.
2. Estructura post-PR-A del cliente de IA: cómo se registra una tarea nueva, firma, cómo se instrumenta en `ai_execution` (task, model, statuses).
3. Camino actual de extracción de `event_type` (intent_v5 → `normalize_event_type`): dónde exactamente insertar la normalización intra-cliente y emitir `NORMALIZED`/`DISCARDED`.
4. Punto único de composición de `requested_services_summary` y confirmación de que converge en `render_response` (si hay más de un ensamblador, repórtalo — convergencia sobre routing).
5. Códigos de servicio en código hoy: ¿existe ya un enum/dict de `entities.md` §13.2? ¿Dónde?
6. `data/knowledge_seed.py`: confirmar que `RESP-SERVICES-RETRY-001` no quedará atrapado en DRAFT.

**GATE G1: DETENTE y reporta.** No escribas código ni tests hasta aprobación.

## Fase G2 — Suite roja TC-SVC

`tests/test_pr_b_services_classification_adversarial.py` (+ archivo separado para extracción si el corte natural lo pide). Casos mínimos, derivados del catálogo:

- **TC-SVC-001**: "solo espacio" con pregunta de servicios pendiente → `[VENUE]` determinista, **cero llamadas al LLM** (asertar sobre el fake/spy del cliente).
- **TC-SVC-002**: "Espacio y gastronomía" (literal fila 532) → códigos resueltos, nunca verbatim en `requested_services`.
- **TC-SVC-003**: "espacio y decoracion" → multi-servicio `[VENUE, DECORATION]`.
- **TC-SVC-004**: longest-match-first — "mobiliario adicional" no resuelve como "mobiliario"; "musica en vivo" no resuelve como "musica" (usa los pares reales del catálogo).
- **TC-SVC-005**: tildes y mayúsculas — "DECORACIÓN" ≡ "decoracion".
- **TC-SVC-006**: negación — "sin licor, lo demás sí" → NO determinista, se despacha a `SERVICES_CLASSIFICATION`.
- **TC-SVC-007**: texto sin match → llamada LLM; respuesta JSON con códigos válidos → aceptada y persistida como códigos.
- **TC-SVC-008**: LLM devuelve código fuera del conjunto cerrado → descartado, fila `ai_execution` con status correspondiente, dominio intacto.
- **TC-SVC-009**: LLM vacío/`INVALID_SCHEMA` → `RESP-SERVICES-RETRY-001` (texto exacto del template aprobado); segunda falla → `OTHER`/escalamiento según flujo vigente, **nunca bucle** (tercer intento no re-pregunta).
- **TC-SVC-010**: paridad catálogo↔módulo.
- **TC-SVC-011**: composición de `requested_services_summary` — formas de Presentación, "X, Y y Z" sin coma de Oxford; casos de 1, 2 y 3+ servicios.
- **TC-SVC-012**: guard de alcance — "espacio" en un estado SIN pregunta de servicios pendiente NO dispara el match determinista.
- **TC-EXT-001**: "la boda de siglo que quiero realizar" → `WEDDING` vía `EVENT_TYPE_EXTRACTION`, normalización intra-cliente, fila `ai_execution` con status `NORMALIZED` cuando aplique.
- **TC-EXT-002**: extracción devuelve valor no normalizable → `DISCARDED` registrado, campo de dominio no contaminado (ninguna repetición del patrón `raw_value` del P0 previo).
- **TC-EXT-003**: "boda civil" en extracción → `CIVIL_WEDDING`, no colapsa a `WEDDING` (regresión de tarea 1 cubierta también por el camino nuevo).
- Instrumentación: al menos un e2e verifica que el turno completo escribió las filas esperadas en `ai_execution` (task, éxito/estado).

Commit: `test: add red adversarial suite TC-SVC for services classification and event type extraction`.

**GATE G2: la suite debe estar EN ROJO por aserciones** (no por imports). Reporta el conteo exacto y DETENTE. Verde prematuro = el caso no prueba lo que dice. Verificación en CI vía PR draft (patrón red-check si hace falta).

## Fase G3 — Implementación

Hasta suite completa del repo en verde en CI, cero regresiones. Corte propuesto (ajústalo en el reporte G1 si el corte natural difiere):

1. `docs: add RESP-SERVICES-RETRY-001 to approved responses` (+ seed)
2. `feat: add deterministic services alias matcher with catalog parity test`
3. `feat: add SERVICES_CLASSIFICATION task with closed-set JSON contract`
4. `feat: add EVENT_TYPE_EXTRACTION task with in-client normalization`
5. `feat: compose requested_services_summary deterministically at presentation boundary`

## Reporte final

Tabla censo G1 (con lo que cambió si algo cambió), conteos exactos rojo G2 → verde G3, estado del CI en el PR, y desviaciones — que deben ser ninguna o declaradas con justificación. Cualquier necesidad de plantilla nueva adicional, migración, o gap del catálogo = DETENTE y reporta.

---

# Enmienda 1 al prompt PR-B — Aprobación G1 y autorización G2

El Gate G1 queda **APROBADO**. El censo se adopta como anexo normativo con las resoluciones de abajo. Autorizado pasar a G2 con las adiciones de esta enmienda.

## Correcciones rectoras aceptadas (las tres solicitadas)

1. **Ruta de plantillas:** `docs/conversation/approved-responses.md` (la ruta `docs/review/` del prompt original era errónea). `RESP-SERVICES-RETRY-001` se agrega allí con el texto exacto del catálogo §5.
2. **37 códigos, incluido `OTHER`.** La discrepancia es interna del catálogo: su encabezado dice 36, su tabla tiene 37. Fix: commit `docs:` que corrige el encabezado de `services-catalog.md` a 37 (versión v1.0.1) y declara explícitamente que `OTHER` NO participa del match determinista (sin aliases). El test de paridad compara contra la **tabla** del catálogo.
3. **`intent_v4` se mantiene intacto.** Las tareas nuevas no alteran la versión del clasificador general. Versiones de prompt propias: `services_v1` y `event_type_extraction_v1`, registradas en `ai_execution.prompt_version`.

## Resoluciones de diseño (nuevas, normativas para G2/G3)

**R1 — Persistencia por códigos.** `EventServiceRequest.service_name` almacena códigos del catálogo (`VENUE`, `DECORATION`, …) para toda escritura nueva. Sin migración de datos: las filas legacy con texto libre permanecen. El presentador resuelve en dos niveles: código conocido → forma de Presentación del catálogo; valor desconocido (legacy) → degradación con la transformación vigente (minúsculas, quita "solo") + warning structlog con el valor. Prohibido que un valor legacy rompa el render o llegue crudo sin la degradación actual.

**R2 — Disparador de `EVENT_TYPE_EXTRACTION`.** El orquestador invoca la tarea cuando se cumplen AMBAS: (a) `event_type` es campo pendiente del lead/evento activo, y (b) la clasificación general del turno no produjo entidad `event_type` válida tras la normalización existente. Es fallback dirigido; el camino actual del clasificador general no se modifica. La doble invocación de `normalize_classification_event_type_entities()` detectada en el censo NO se toca (backlog).

**R3 — Refactor mínimo del cliente, sin framework.** Extraer helper privado que parametrice tarea, prompt, versión y schema hacia `_record_execution`; el string hardcodeado `INTENT_CLASSIFICATION` pasa a parámetro. Métodos públicos por tarea (`classify_intent` existente sin cambio de firma, `classify_services`, `extract_event_type`). Ningún registro genérico de tareas. El patrón HTTP-fuera-de-transacción verificado en el censo se preserva idéntico: las tareas nuevas jamás se llaman con transacción de DB abierta.

**R4 — Composición del summary en el presentador.** `requested_services_summary` se compone íntegramente en la capa de presentación consumiendo códigos y formas del catálogo (serialización coma + "y", sin coma de Oxford). El ensamblador actual del orquestador (`service.py:3016`) deja de componer texto: entrega los valores crudos (códigos o legacy) al presentador. La transformación parcial de `presentation.py:167` se absorbe en la nueva composición (queda solo como rama de degradación legacy de R1). Resultado: UNA sola composición, del lado determinista de la frontera.

**R5 — Eliminación del fallback verbatim.** `contextual_requested_service_entities()` deja de fabricar entidades con el mensaje completo. El camino nuevo con pregunta de servicios pendiente es: matcher determinista → (sin match o negación) → `SERVICES_CLASSIFICATION` → (vacío/inválido) → `RESP-SERVICES-RETRY-001` → (segunda falla) → `OTHER` + flujo de escalamiento vigente. En ningún punto se persiste texto libre del cliente en `service_name`.

## Casos adicionales para la suite G2 (además de los TC-SVC/TC-EXT del prompt)

- **TC-SVC-013 — Degradación legacy:** evento con `EventServiceRequest.service_name` de texto libre preexistente → el summary renderiza con la degradación de R1, warning emitido (asertar vía `capture_logs`, pipeline structlog), sin excepción, sin texto crudo sin transformar.
- **TC-SVC-014 — Persistencia por códigos:** tras resolución determinista de "espacio y decoracion", las filas de `EventServiceRequest` contienen exactamente `VENUE` y `DECORATION`, no labels ni texto original.
- **TC-SVC-015 — `OTHER` fuera del match determinista:** ningún alias resuelve a `OTHER`; el código solo aparece por salida LLM o por el fallback de segunda repregunta.
- **TC-EXT-004 — Disparador R2 positivo:** `event_type` pendiente + clasificación general sin entidad válida → se invoca `EVENT_TYPE_EXTRACTION` (asertar sobre el fake/spy).
- **TC-EXT-005 — Disparador R2 negativo:** clasificación general SÍ produjo `event_type` válido → la tarea NO se invoca (cero llamadas extra al LLM).
- **TC-EXT-006 — `prompt_version` por tarea:** filas de `ai_execution` de las tareas nuevas registran `services_v1` / `event_type_extraction_v1`; las de clasificación general siguen con la versión de `intent_v4`.

## Precondiciones operativas (Emerson, antes de que Codex ejecute G2)

1. Crear branch `services-classification-and-event-type-extraction` desde `main` (`30ab668`).
2. Commit 0 en el branch: `docs: add codex prompt and amendment for PR-B` (este archivo + el prompt original en `docs/prompts/`).
3. Confirmado que `3fe5df1` y `30ab668` son los commits docs de la enmienda v1.1.1 y el handoff; si no lo son, detener y reportar.

## Recordatorios vigentes

GATE G2 sin cambios: suite en rojo por aserciones, conteo exacto, DETENTE. Los commits de G3 del prompt original se re-cortan si hace falta conforme a R1–R5; propuesta de corte ajustado en el reporte G2. Toda desviación se declara.

---

# Enmienda 2 al prompt PR-B — Proceso en máquina sin PostgreSQL local

Desbloquea el falso bloqueo reportado tras G1.

## Regla de proceso (vigente desde slice 2B-3, re-enunciada como rectora)

En esta máquina NO existe PostgreSQL local ni Docker, y no es precondición de nada:

1. Commits `docs:` requieren únicamente `ruff check .` verde. **El Commit 0 procede YA** — pytest no aplica.
2. Commits de código (tests incluidos) se permiten con ruff verde local. El gate de pytest se verifica **exclusivamente en el CI de GitHub Actions**, que corre la suite completa contra PostgreSQL real en Python 3.12 en cada push del branch con PR abierto.
3. El pytest local queda restringido al focal sin DB (si el repo define marcadores para ello); un `ConnectionRefusedError` contra `localhost:5432` NO es un fallo tuyo ni un bloqueo — es la condición normal de esta máquina.
4. Prohibido instalar Docker, Postgres o modificar la URL de pruebas para esquivar esto. Prohibido push a `main`; el branch se pushea libremente.

## Verificación del GATE G2 vía CI

Secuencia obligatoria:

1. Commit 0: `docs: add codex prompt and amendments for PR-B` (prompt + enmiendas 1 y 2).
2. Commits de G2: suite TC-SVC/TC-EXT completa según prompt + Enmienda 1.
3. Push del branch → PR **draft** contra `main`, título: `PR-B: services classification + event_type extraction — NO MERGEAR (G2 rojo esperado)`.
4. El resultado esperado del CI es: **todos los TC-SVC/TC-EXT en rojo por aserciones o NotImplementedError, todo lo preexistente en verde**. Ese check rojo ES la evidencia del GATE G2 — repórtala con el conteo exacto leído del log del CI y DETENTE.
5. Un TC nuevo en verde en ese run = el caso no prueba lo que dice: DETENTE y repórtalo antes de tocar nada.

El historial de checks del PR documenta rojo (G2) → verde (G3) sin refs temporales; no crees branch de red-check separado.

## Autorización de esqueletos en G2 (excepción acotada)

Para que la suite coleccione sin errores de import, el commit de G2 puede incluir **esqueletos mínimos** de los artefactos que G3 implementará:

- El módulo de catálogo de servicios (códigos/aliases/matcher): firmas exactas con `raise NotImplementedError`, cero lógica, cero datos salvo lo estrictamente necesario para importar.
- Los métodos nuevos del cliente (`classify_services`, `extract_event_type`): firma + `raise NotImplementedError`.

Prohibido en los esqueletos: cualquier lógica, cualquier dato del catálogo (la tabla de códigos/aliases se puebla en G3 — si el esqueleto la incluyera, el test de paridad daría verde prematuro), cualquier modificación a código existente. El rojo de estos tests debe provenir de `NotImplementedError` o de aserciones, jamás de errores de colección.

Commit separado: `test: add skeletons for services catalog module and AI client tasks (G2 scaffolding)`.

## Sin cambios en lo demás

Alcance, resoluciones R1–R5, casos TC y gates de la Enmienda 1 permanecen intactos. Tras el reporte G2 con el conteo del CI, esperar autorización para G3.
