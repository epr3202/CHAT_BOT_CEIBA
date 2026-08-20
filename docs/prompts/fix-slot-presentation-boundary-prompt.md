# Prompt Codex — Fix: frontera de presentación única para slots interpolados a cliente

## Contexto y motivación

Tres incidentes distintos materializan el mismo defecto estructural:

1. **Conversación 1**: un label interno de slot fue renderizado al cliente.
2. **Confirmación de visita (2026-08-19)**: el mensaje mostró "Una boda" —
   el texto del usuario verbatim — en vez del label canónico, produciendo
   "...para Una boda para..." gramaticalmente roto.
3. **Resumen de cotización (2026-08-20, verificado en vivo)**: RESP-QUOTE-002
   renderizó "con interés en Solo el espacio" — el texto del usuario tal cual,
   mayúscula intrusa incluida, interpolado en `requested_services`.

La regla de composición vigente ("los valores internos y el texto crudo del
usuario JAMÁS se renderizan al cliente") existe pero su cumplimiento es
opcional por call site: `app/conversation/presentation.py` ya tiene
`format_event_type`, `format_date_natural` y `format_month_natural`, pero nada
obliga a que toda variable interpolada pase por un presentador. Este fix
convierte la frontera en estructural: **registro de presentadores por
variable** + **test contractual** que falla ante cualquier variable de template
aprobado sin presentador registrado. El objetivo es que esta clase de bug sea
imposible de reintroducir, no solo arreglar los tres casos.

Trabaja en un branch nuevo `fix-slot-presentation-boundary` creado desde
`origin/main`. Lee `AGENTS.md`. Entorno Windows: `.venv/Scripts/python.exe -m`
para pytest y ruff. Fuentes de verdad, en orden: este documento, la regla de
composición en los docs de conversación, `approved-responses.md` (inventario de
variables), el código actual en `origin/main`.

## Material preexistente que DEBES reutilizar

La rama `origin/rescue-adversarial-suites` contiene
`tests/unit/test_event_type_contract_adversarial.py` con tests TC-DISPLAY-001
a TC-DISPLAY-004 que especifican parte de este contrato (labels naturales en
templates, ningún identificador enum en mensajes compuestos, texto verbatim
del usuario nunca reutilizado como valor de template). Extráelos con
provenance correcta:

```
git show origin/rescue-adversarial-suites:tests/unit/test_event_type_contract_adversarial.py
```

Integra los TC-DISPLAY a la suite de este fix (adaptados si hace falta). Los
TC-ETYPE de ese mismo archivo NO se migran aquí: verifica cuáles ya están
cubiertos por `tests/unit/test_event_type_normalization.py` (el fix
`a7e1107` cubrió varios) y repórtalo en G1 — la deduplicación se decide ahí.
No modifiques la rama `rescue-adversarial-suites`.

## Restricciones globales (innegociables)

- PROHIBIDO todo texto nuevo hacia el cliente: solo plantillas RESP-* ya
  aprobadas. Las transformaciones de presentación (labels, casing, uniones de
  lista) alteran cómo se rellena una variable, no el texto del template — pero
  como cambian lo que el cliente lee, la tabla de transformaciones propuestas
  requiere aprobación humana explícita en G1 antes de implementar nada.
- PROHIBIDO tocar: migraciones, plantillas en `approved-responses.md`,
  el prompt del clasificador, `VisitSchedulingService`, catálogos,
  docker-compose, CI.
- PROHIBIDO fuzzy matching o heurísticas de "arreglo" de texto del usuario.
  Si un valor no tiene presentación canónica definida, la pregunta escala a
  humano vía G1 — no se inventa.
- Los tests se derivan de los docs y de los transcripts citados arriba, no de
  la implementación.
- Un commit por tarea, prefijos convencionales, sin amend/rebase de lo
  pusheado. Codex nunca pushea `main`.

## Tarea 0 — Setup

`git switch -c fix-slot-presentation-boundary origin/main`. Copia este
documento a `docs/prompts/fix-slot-presentation-boundary-prompt.md`.
Commit: `docs: add slot presentation boundary specification`.

## GATE G1 — Censo y tabla de presentación (bloqueante: reporta y DETENTE)

1. **Inventario de variables**: extrae de `approved-responses.md` la lista
   completa de variables `{...}` usadas por todas las plantillas RESP-*.
   Repórtala como tabla: variable → plantillas que la usan.
2. **Censo de ensamblado**: localiza cada punto del código donde se construye
   el diccionario de variables para `render_response`/`enqueue_template`
   (cotización, visitas, catálogos, FAQ, saludo, etc.). Para cada punto,
   reporta qué variables rellena y si el valor pasa por un presentador o va
   crudo. Marca explícitamente los tres caminos de los incidentes: la
   confirmación de visita (RESP-VISIT-CONFIRM-*), el resumen de cotización
   (`quote_summary_variables`, RESP-QUOTE-00X) y el punto de conversación 1.
3. **Tabla de transformaciones propuesta**: para cada variable que hoy va
   cruda, propone su presentación canónica con ejemplos ANTES → DESPUÉS
   tomados de los transcripts (p. ej. `requested_services`:
   "Solo el espacio" → propuesta concreta). Donde la presentación canónica
   requiera una decisión de negocio, márcalo como PREGUNTA en vez de decidir.
4. **Diseño del registro**: propuesta concreta del mecanismo (p. ej. dict
   `VARIABLE_PRESENTERS` en `presentation.py` + función `present_variables`
   que aplica presentadores y FALLA — no silenciosamente — ante variable sin
   registro) y del test contractual que recorre las variables del inventario
   del punto 1 y exige presentador para cada una.
5. **Alcance**: si el censo revela más de ~6 call sites a modificar, propone
   partición en dos slices y DETENTE.

Espera aprobación de la tabla de transformaciones antes de continuar.

## Tarea 1 — Suite adversarial (rojo) — GATE G2

Con la tabla aprobada en G1: suite derivada de docs + transcripts. Debe
incluir como mínimo:

- Los TC-DISPLAY rescatados e integrados.
- El caso literal del incidente 3: variables de resumen de cotización con
  `requested_services` capturado como "Solo el espacio" → el texto compuesto
  contiene la forma aprobada en G1 y NO contiene "Solo el espacio" verbatim.
- El caso del incidente 2: variables de confirmación de visita con el tipo
  capturado → label canónico ("una boda"), nunca el texto crudo del usuario.
- Test contractual de cobertura: toda variable del inventario tiene
  presentador registrado; una variable inventada sin registro hace fallar
  `present_variables` de forma explícita.
- Regresión: `format_event_type`, `format_date_natural`, `format_month_natural`
  siguen intactos y ahora registrados.

Estructura de commits igual que el fix anterior: los tests se commitean en G3
junto a la implementación en commits separados (`test:` primero, luego
`fix:`), con la cabeza del branch verde. En G2 solo reporta el output rojo de
pytest y DETENTE.

## Tarea 2 — Implementación (verde) — GATE G3

Implementa el registro y rutea los call sites del censo por
`present_variables`. Verde focal (suite unit + ruff). Reporta: output de
pytest, ruff, `git log --oneline origin/main..HEAD`, diff completo de
`presentation.py` y diff resumido de cada call site tocado. DETENTE —
revisión de archivos frontera, PR para suite completa en CI, merge y push los
hace Emerson.

## Fuera de alcance explícito

- El colapso del clasificador "boda civil"→WEDDING observado el 2026-08-20
  (es upstream, del prompt de intents; solo déjalo anotado si lo ves influir).
- Fusión de categorías boda/boda civil y el CRUD de tipos de evento (slice
  futuro; este fix construye la frontera de presentación que ese CRUD
  necesitará, nada más).
- Recordatorios, interruption policy, y cualquier plantilla nueva.
