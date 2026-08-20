# Prompt Codex — Fix: fallback a labels canónicos en `normalize_event_type`

## Contexto y motivación

El fix del incidente "GENDER REVEAL" estableció el invariante correcto: valores
de `event_type` que no matchean el enum degradan a `None` con audit
`EVENT_TYPE_ENTITY_DISCARDED`, nunca excepción. Pero en ese cambio se eliminó el
mapeo legacy `BODA→WEDDING` de `normalize_event_type`
(`app/event/event_type.py`). Consecuencia: si el clasificador devuelve el label
en español (`"BODA"`, `"boda civil"`) en vez del valor enum, la entidad se
descarta silenciosamente — el sistema no se cae, pero pierde información que el
cliente ya dio y vuelve a preguntarla.

El fix NO es restaurar mapeos hardcodeados caso por caso. Es agregar un fallback
en cascada: si la normalización mecánica no matchea el enum, intentar resolver
contra los labels canónicos de `docs/conversation/entities.md` §7.1, reutilizando
el resolver que ya existe para el flujo de catálogos:
`resolve_catalog_event_type_label` en `app/conversation/catalog_event_type.py`.

Trabaja en un branch nuevo `fix-event-type-label-fallback` creado desde
`origin/main`. Lee `AGENTS.md` completo. Fuentes de verdad, en orden: este
documento, `docs/conversation/entities.md` §7.1, el código actual en
`origin/main` (las rutas de archivo citadas aquí se verifican en G1; el estado
real del repo manda sobre este documento si hay discrepancia de detalle).

## Restricciones globales (innegociables)

- PROHIBIDO agregar, quitar o renombrar valores del enum de tipos de evento.
- PROHIBIDO tocar migraciones, CHECK constraints, plantillas RESP-*,
  `app/conversation/presentation.py`, docker-compose, CI.
- PROHIBIDO duplicar la tabla de labels canónicos. Existe una sola fuente
  (§7.1) y un solo resolver en código; se reutiliza, no se copia.
- El invariante del incidente GENDER REVEAL se preserva intacto: valor no
  resoluble → `None` + audit `EVENT_TYPE_ENTITY_DISCARDED`. Jamás excepción,
  jamás adivinar por aproximación (sin fuzzy matching, sin startswith).
- Si el fallback requiere importar `app.conversation.*` desde
  `app.event.event_type` y eso cierra un ciclo de imports, la resolución
  preferida es mover la tabla de labels (y su función de resolución pura) a un
  módulo neutral de bajo nivel del que ambos dependan (p. ej.
  `app/event/event_type_labels.py`), dejando en
  `app/conversation/catalog_event_type.py` un re-export o wrapper para no
  romper sus consumidores. Un import diferido dentro de la función es aceptable
  solo si el movimiento de módulo resulta desproporcionado; repórtalo en G1
  antes de decidir.
- Un commit por tarea, prefijos convencionales (`test:`, `fix:`, `refactor:`),
  sin amend/rebase de lo pusheado. Codex nunca pushea `main`; el branch sí.
- `pytest` siempre vía `.venv/bin/python -m pytest`.

## Tarea 0 — Setup

`git switch -c fix-event-type-label-fallback origin/main`. Copia este documento
a `docs/prompts/fix-event-type-label-fallback-prompt.md`.
Commit: `docs: add event_type label fallback specification`.

## GATE G1 — Descubrimiento (bloqueante: reporta y DETENTE)

Antes de escribir cualquier test o código, reporta:

1. **Estado actual de `normalize_event_type`**: firma, cuerpo completo, y dónde
   se emite el audit `EVENT_TYPE_ENTITY_DISCARDED` (¿dentro de la función o en
   el caller?).
2. **Firma y semántica de `resolve_catalog_event_type_label`**: cómo normaliza
   (casefold, acentos, espacios), qué devuelve ante no-match, y si su tabla
   cubre los 17 tipos actuales (incluido `GENDER_REVEAL`) con los labels de
   §7.1.
3. **Censo de puntos de normalización**: `git grep -n "BODA"` y
   `git grep -n "\.strip()\.upper()"` sobre `app/`. En particular: ¿sobrevive
   en `apply_event_type` (`app/orchestrator/service.py`) el hack inline
   `if event_type == "BODA": event_type = "WEDDING"` con su propio
   `.strip().upper()`? ¿Qué otros callers normalizan event_type por su cuenta
   en vez de llamar a `normalize_event_type`?
4. **Grafo de imports**: ¿importar el resolver desde `app/event/event_type.py`
   cierra un ciclo? Si sí, propuesta concreta de módulo neutral (nombre, qué se
   mueve, qué queda como re-export).
5. **Alcance propuesto**: si el censo del punto 3 revela normalizadores
   paralelos, propone unificarlos (todos los caminos pasan por
   `normalize_event_type`; el hack inline se elimina). Si la unificación toca
   más de ~3 call sites o cambia comportamiento observable más allá de los
   casos especificados aquí, DETENTE y repórtalo como scope excedido en vez de
   proceder.

Espera aprobación antes de continuar.

## Tarea 1 — Suite adversarial (rojo) — GATE G2

Deriva los tests SOLO de `entities.md` §7.1 y de este documento, no de la
implementación. Archivo: `tests/unit/test_event_type_label_fallback.py` (o
extender el archivo de tests existente de normalización si G1 lo identifica).

Contrato mínimo:

| Entrada | Salida esperada | Qué prueba |
| --- | --- | --- |
| `"WEDDING"` | `WEDDING` | Camino mecánico intacto (regresión) |
| `"GENDER REVEAL"` (con espacio) | valor enum correcto vía normalización mecánica o fallback, según defina §7.1 | El fix del incidente previo no se degrada |
| `"BODA"` | `WEDDING` | Label canónico, mayúsculas |
| `"boda"` | `WEDDING` | Label canónico, minúsculas |
| `"boda civil"` | `CIVIL_WEDDING` | Label compuesto — prueba que la cascada usa la tabla completa, no uppercase-match |
| `"Boda Civil"` | `CIVIL_WEDDING` | Insensibilidad a caso en compuestos |
| `"FIESTA"` | `None` | Negativo: término no canónico degrada limpio, no se adivina |
| `""` / `"   "` | `None` | Entrada vacía |
| `None` | `None` | Entrada nula (si la firma lo admite; si no, documentar) |

Además, un test que verifique que el camino `None` sigue emitiendo (o
permitiendo que el caller emita) `EVENT_TYPE_ENTITY_DISCARDED` — según lo que
G1 haya establecido sobre dónde vive ese audit.

Si G1 aprobó unificación del hack inline: agregar un test de integración a
nivel `apply_event_type` (o el caller equivalente) que verifique que una
entidad con `normalized_value="BODA"` captura `WEDDING` en el evento, y que
`"FIESTA"` no captura nada y audita el descarte.

Corre la suite: los tests nuevos deben estar en ROJO (salvo los de regresión).
Commit: `test: adversarial suite for event_type canonical label fallback`.
Reporta el output de pytest y DETENTE.

## Tarea 2 — Implementación (verde) — GATE G3

Implementa el fallback en cascada en `normalize_event_type`:

1. Normalización mecánica actual (sin cambios de comportamiento).
2. Si no matchea: resolver contra labels canónicos vía el resolver reutilizado
   (o movido a módulo neutral según lo aprobado en G1).
3. Si tampoco: `None`, preservando el audit de descarte exactamente como está.

Si G1 aprobó la unificación: eliminar el hack inline de `apply_event_type` y
rutear por `normalize_event_type`. Commit separado con prefijo `refactor:`.

Corre la suite completa. Todo verde. Commits:
- `fix: fall back to canonical Spanish labels in normalize_event_type`
- (opcional, aprobado en G1) `refactor: route apply_event_type through normalize_event_type`

Reporta: output completo de pytest, `git log --oneline origin/main..HEAD`, y
diff resumido por archivo. DETENTE — la revisión de diffs en archivos frontera
y el push los hace Emerson.

## Fuera de alcance explícito

- El bug de confirmación verbatim y el bug de composición de slots
  (presentación enum→label hacia el cliente): son otro prompt. Este fix es
  entrada (texto→enum), no salida (enum→texto).
- Cualquier cambio a `format_event_type` / `EVENT_TYPE_LABELS` en
  `presentation.py`.
- El prompt del clasificador en OpenRouter.
