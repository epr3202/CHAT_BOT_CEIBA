Reparación de CI sobre `f7a8d4c`, autorizada directamente por Emerson para continuar hasta integrar el PR #41 en main. Los runs anteriores verifican SHAs históricos; el nuevo run verificará conjuntamente las correcciones del HEAD.

[CI #161](https://github.com/epr3202/CHAT_BOT_CEIBA/actions/runs/37392766376) terminó con `4 failed, 2447 passed, 24 warnings in 1916.85s (0:31:56)`. Frontend, lint y migraciones pasaron. [Extracto de fallos](CI-161-red.out), sin el prefijo de timestamp de Actions; log original completo conservado en el directorio local de trabajo.

Todas las correcciones están en tests. No cambian código de producción, reglas funcionales, esquema ni texto al cliente:

| Caso | Causa y corrección |
| --- | --- |
| R3, degradación durante captura | El test exigía el menú discovery pese a la nueva R5. Ahora exige preservar la pregunta aprobada sin variables, pending_action y contador; active mantiene discovery. `tests/remediation/r3/test_r3_flow.py:92`. |
| Catálogo 018c, cadena de plantillas no aprobadas | El input anterior ya contenía ROMANTIC_DINNER y R3 resolvía el tipo antes de preguntar. Se usa `envíame el catálogo`, sin tipo, para probar otra vez la cadena 002→003; todas las expectativas permanecen. `tests/test_slice2a_catalogs_adversarial.py:955`. |
| B3, reapertura de notificaciones internas | El test fijaba sus fechas al 2 de octubre, pero el handler calculaba antigüedad con el reloj real. Se fija únicamente el reloj de notificaciones a NOW durante los dos webhooks, conservando el límite de 48h, silencio e idempotencia. Preexistía idéntico en main. `tests/staff_notifications/test_b3.py:303`. |
| D2, guard de transacciones de Calendar | El guard consultaba todas las transacciones de PostgreSQL y el fallo no identificaba el backend. El caso aislado pasó y availability está idéntica a main. El fixture ahora comprueba el estado real de Connections SQLAlchemy de todos los engines de la misma BD de prueba, sin abrir otra transacción ni introducir esperas. Conserva la prohibición de Calendar con tx abierta y elimina el listener en finally. `tests/booking_conversation/conftest.py:78`. |
| Contrato adicional D2 | Un segundo engine con tx abierta debe producir AssertionError; después de commit debe permitir Calendar. `tests/booking_conversation/test_d2_window.py:58`. |

| Subset local | Resultado |
| --- | --- |
| Caso Calendar aislado, antes del ajuste del guard | [calendar-before.out](calendar-before.out): `1 passed in 4.48s` |
| D2 + contratos backend G3 | [calendar-guard-green.out](calendar-guard-green.out): `20 passed in 13.47s` |
| B3 + reapertura F2 | [staff-green.out](staff-green.out): `37 passed in 109.37s (0:01:49)` |
| Catálogos adversariales | [catalog-ci-green.out](catalog-ci-green.out): `33 passed, 7 warnings in 59.71s` |
| R3 + G2 captura + fronteras fallback | [fallback-ci-green.out](fallback-ci-green.out): `54 passed in 298.15s (0:04:58)` |
| Conversación de reservas completa (fixture afectado) | [booking-ci-green.out](booking-ci-green.out): `153 passed in 622.41s (0:10:22)` |
| Lint | `ruff check .`: `All checks passed!` |

[Comandos reproducibles](commands.txt). Los cuatro subsets finales suman 277 casos distintos en verde; D2/G3 aporta además la verificación de 20 contratos (parcialmente compartidos).

Los primeros comandos locales de R3 y G3 requerían variables sintéticas de CI que no estaban definidas. Se corrigió únicamente el entorno del comando (`DATABASE_URL`, `META_APP_SECRET`, `META_ACCESS_TOKEN`, `OPENROUTER_API_KEY`, `QUALITY_STAGE=suite`); las ejecuciones siguen siendo subsets, sin suite completa local. Las salidas iniciales se conservan en el directorio local de trabajo.

Desviaciones declaradas: se actualiza una expectativa anterior de R3 conforme a R5; se corrigen los mecanismos del input de catálogo, reloj de staff y guard de Calendar en commits test propios. Los archivos G2 no se modifican respecto a `f7a8d4c`. El test nuevo fortalece el contrato de transacciones con un engine independiente. No se añaden migraciones, plantillas, estados ni valores de pending_action; no hay consultas adicionales a producción.

Se realizará un único push de esta tanda y un nuevo run CI. La autorización de Emerson sustituye la instrucción anterior de detenerse antes del merge; la integración se hará por PR al superar CI, conservando los commits por área.

Commits por área antes de la evidencia:

```text
91d6d4b test: observe calendar transaction boundary across test engines
37a6dac test: align fallback and catalog chain regression contracts
ad1544b test: freeze staff notification reopening clock
```

Diff funcional incremental (la evidencia se añade aparte):

```text
 tests/booking_conversation/conftest.py       | 35 ++++++++++++++++++----------
 tests/booking_conversation/test_d2_window.py | 19 +++++++++++++++
 tests/remediation/r3/test_r3_flow.py         |  6 ++++-
 tests/staff_notifications/test_b3.py         |  8 ++++---
 tests/test_slice2a_catalogs_adversarial.py   |  2 +-
 5 files changed, 53 insertions(+), 17 deletions(-)
```
