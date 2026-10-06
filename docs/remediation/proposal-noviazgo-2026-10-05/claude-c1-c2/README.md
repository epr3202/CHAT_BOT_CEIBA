Correcciones C1/C2 de Claude al PR #41, sobre `9dce534de0be00b1608cd7dfc04e979a16f968d0`, en la rama `fix/proposal-noviazgo-catalog-capture`. El PR permanece en borrador hacia main; no se hace merge.

C1 restringe `noviazgo`, `propuesta`, `otro`, `otro tipo de evento`, `grado` y `taller` a respuestas durante `COLLECT_CATALOG_EVENT_TYPE`. Fuera de esa captura se ignoran como menciones. C2 exige un tipo único junto a `catalogo/catalogos`, o una etiqueta PROPOSAL reconocida con al menos dos palabras, para evitar el clasificador sin captura. Las cuatro frases incidentales de la revisión crean una ejecución del clasificador y no generan catálogo PROPOSAL ni handoff determinista.

| Corrección | Referencias |
| --- | --- |
| C1: conjunto explícito y filtro | `app/conversation/catalog_event_type.py:56`, `:95` |
| C1: flag público, default False | `app/conversation/catalog_event_type.py:122`, `:133` |
| C1: precio fijo sin labels de respuesta; prioridad solo sobre ROMANTIC_DINNER | `app/conversation/catalog_event_type.py:142` |
| C1: guard usa True únicamente en captura; handler de captura usa True | `app/orchestrator/service.py:629`, `:849` |
| C2: catálogo normalizado o frase PROPOSAL de dos o más palabras | `app/orchestrator/service.py:646` |
| Reglas documentadas junto con código | `docs/conversation/entities.md:598`, `docs/decisions.md:230`, `docs/conversation/states.md:2992` |
| Nuevos contratos del resolvedor y guard | `tests/unit/test_noviazgo_catalog_resolver_g2.py:63` |
| Nuevos contratos por canal, clasificador y ai_execution | `tests/test_noviazgo_catalog_capture_g2.py:339` |

Resultados literales y comandos reproducibles se adjuntan en esta carpeta:

| Verificación | Salida |
| --- | --- |
| Tests nuevos rojos, antes de C1/C2 | [red.out](red.out): `27 failed, 5 passed, 79 deselected in 24.91s` |
| C1 y G2-7 con contexto de captura | [c1.out](c1.out): `92 passed, 19 deselected in 22.28s` |
| G2, captura nueva y fronteras del fallback | [green-g2.out](green-g2.out): `127 passed in 131.19s (0:02:11)` |
| Normalización, guard de precio fijo y orquestador | [green-unit.out](green-unit.out): `95 passed in 15.62s` |
| Captura previa, precio fijo e información general | [green-catalog.out](green-catalog.out): `72 passed in 409.90s (0:06:49)` |
| Lint | `ruff check .`: `All checks passed!` |

Los tres subsets finales suman 294 casos distintos en verde. Los 27 fallos del rojo son `AssertionError`; no hay `ImportError` ni `TypeError`. Se usa PostgreSQL local, con tres bases de test distintas para los subsets paralelos; las llamadas externas permanecen mockeadas. No se ejecuta la suite completa localmente: corresponde al único run CI iniciado por el único push de esta revisión. [Comandos](commands.txt), [contrato de bytes](byte-contract.out), [checks del PR](https://github.com/epr3202/CHAT_BOT_CEIBA/pull/41/checks).

Commits por área:

- `4842730 test: reproduce incidental proposal catalog routing`: suite nueva en rojo antes de implementar.
- `23cfa33 test: run G2-7 resolver contract as catalog answers`: excepción de mecanismo autorizada por Emerson.
- `0d07041 fix: scope catalog answer labels and fixed-price ambiguity`: C1 y sus docs.
- `31709cb fix: require explicit proposal phrases outside catalog capture`: C2 y sus docs, incluida la precedencia en states.md.
- Un commit de evidencia adjunta estas salidas y el reporte.

Diff funcional incremental frente a `9dce534` (la evidencia se añade aparte):

```text
 app/conversation/catalog_event_type.py          | 37 ++++++++----
 app/orchestrator/service.py                     | 18 ++++--
 docs/conversation/entities.md                   | 30 ++++++----
 docs/conversation/states.md                     | 13 +++--
 docs/decisions.md                               | 22 ++++++-
 tests/test_noviazgo_catalog_capture_g2.py       | 53 +++++++++++++++++
 tests/unit/test_noviazgo_catalog_resolver_g2.py | 78 ++++++++++++++++++++++++-
 7 files changed, 215 insertions(+), 36 deletions(-)
```

Desviación declarada: G2-7 conserva todas sus expectativas, tablas de parámetros y decoradores, pero añade `answering_event_type_question=True` en sus dos llamadas. Emerson autorizó ese ajuste de mecanismo en un commit `test:` propio. G2-1, ambos G2-6 y el resto de los tests existentes siguen byte-idénticos; también los payloads literales. Los archivos de G2 contienen ahora los nuevos casos C1/C2, por lo que su hash de archivo cambia respecto a la entrega original.

El caso de captura `otro` demuestra resolución OTHER y usa el handoff de catálogo no disponible ya existente, porque la fixture solo tiene assets PROPOSAL y ROMANTIC_DINNER. No crea una regla ni plantilla nueva.

Sin migraciones, valores de pending_action, estados, textos al cliente, cambios al cliente IA ni consultas adicionales a producción. Se conserva el resolvedor exacto usado para normalizar entidades estructuradas. Las reglas y la evidencia M1–M8 de la entrega original permanecen en [el reporte anterior](../README.md). Se detiene el trabajo para revisión de Claude después del push y del enlace al run CI.
