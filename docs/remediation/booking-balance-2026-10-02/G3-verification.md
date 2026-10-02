# G3 — verificación local del PR combinado

Base: c5812f5267e9c99208282e2a3baed66f9fb02cb7. Rama feat/booking-balance.
Producto final en 9976400; el commit posterior solo completa documentación.
No hay producción, merge, amend, rebase ni force. La suite completa queda para
el único run de CI del PR; no se ejecutó completa en local.

## G1 y G2

[G1.md](G1.md) conserva el censo histórico C1–C8 con rutas/líneas de la base.
Su detención R9(a) se levantó mediante la autorización explícita de la
continuación de Emerson. D2 permite asociar saldo sin transición; no se amplía
su catálogo. C7 identificó las dos rutas originales de HTTP en TX incluidas en D6.

[G2-red.md](G2-red.md) registra 73 casos Python distintos: 58 fallos de aserción
y 15 verdes, más dos fallos de aserción Playwright. Incluye la primera línea de
cada fallo y el commit rojo b01cf91. No hubo errores finales de colección,
fixture, ImportError ni AttributeError en G2.

El [manifiesto original](G2-sha256.json) tiene trece archivos: doce mantienen
exactamente sus bytes. La única excepción es F2, corregida en c1bdc30 y
explicada en [G2-mechanism-corrections.md](G2-mechanism-corrections.md).
Las aserciones de ese caso no cambiaron. Las extensiones de contrato posteriores
están en commits test: propios; no modifican los demás tests congelados.

## Subsets finales

| Selección | Casos verdes |
| --- | ---: |
| tests/payment_prereview | 64 |
| tests/booking_balance | 49 |
| tests/staff_notifications | 47 |
| tests/booking_conversation | 152 |
| tests/payment_settlement | 103 |
| tests/booking_backend | 90 |
| Total distinto de los seis subsets | **505** |

La ejecución conjunta recogió 498 casos y pasó en 1262.31 s. Después se añadieron
siete contratos de reprogramación, locks y ciclo de handoff entre conversaciones.
Tras las correcciones finales, se repitió íntegro booking_balance: **49 passed,
263.97 s**, incluyendo sus 42 anteriores y los siete nuevos. El total por subset
se comprobó con colección final: 505 casos. Las otras cinco áreas no cambiaron
después de su ejecución conjunta verde.

Además se verificaron 142 contratos afectados: romántico 53; R9 48; W2b 23;
registry 1; settings 2; knowledge 6; sync de knowledge 9. La primera ejecución
tuvo 137 verdes y cinco fallos de mecanismo/datos: mapa de variables obsoleto
y cuatro DOC por ruta /data heredada del entorno. Las correcciones declaradas
pasaron los cinco casos; rerun 6 passed (incluye registry repetido), 22.27 s.
Los contratos de frontend Python añaden **18 passed**, 0.38 s. Son **160 contratos
adicionales distintos**, sin ejecutar el resto de la suite local.

Las comprobaciones dirigidas durante implementación también pasaron: D6 64;
D5 G2/notificaciones/E2E 20; extensiones y manuales 13; vinculación 5; SQL 1;
B4/B3 46; lock/reschedule 12; callbacks/B4/staff 60; lifecycle/G2 D5 18.
Estos números se solapan con la tabla y no se suman como casos nuevos.

## Ruff, migraciones y Playwright

`ruff check .` y `ruff format --check .` pasan con **Ruff 0.16.9**, la versión
de requirements-dev.lock: **396 archivos ya formateados**. Se ejecutaron en
una copia limpia de HEAD para excluir los nueve scripts locales a13/a14
preexistentes y no seguidos por Git. No se editaron esos archivos ajenos.
`git diff --check` y los checks de sintaxis de app.js/labels.mjs también pasan.

`make migrate-cycle TEST_ENV= DOWNGRADE_REVISION=-1` pasa en PostgreSQL local
exclusivo: **0035 → 0034 → 0035**. El contrato del ciclo conserva audit_event y
ai_execution; 0035 no modifica los historiales de mensajes ni reviews. La única
migración nueva es 20261002_0035. Su límite de rollback está documentado en
[deployment.md](deployment.md).

Playwright: **42 passed, 46.7 s**, ejecutando estas specs con huso del navegador
Honolulu para comprobar la presentación Bogotá:

- test_booking_balance.spec.mjs
- test_b3_staff_notifications.spec.mjs
- test_b2_panel_contracts.spec.mjs
- test_g3_payment_panel.spec.mjs
- test_g3_reservations.spec.mjs
- test_spanish_labels.spec.mjs

Meta/OpenRouter estuvieron simulados y Calendar fue fake. Todos los runners
usaron DBs explícitas de pruebas en localhost:55433; ninguna conexión de
producción. La aplicación local Playwright usa ENVIRONMENT=production para
probar el panel público, con base y proveedores de pruebas.

## Reproducción y evidencia

Con DATABASE_URL/TEST_DATABASE_URL explícitos de pruebas, settings sintéticos,
Calendar fake y directorios de almacenamiento privados:

```sh
QUALITY_STAGE=suite pytest tests/payment_prereview tests/booking_balance \
  tests/staff_notifications tests/booking_conversation tests/payment_settlement \
  tests/booking_backend -q
QUALITY_STAGE=suite pytest tests/booking_balance -q
ruff check . && ruff format --check .
make migrate-cycle TEST_ENV= DOWNGRADE_REVISION=-1
npm --prefix tests/frontend test -- test_booking_balance.spec.mjs \
  test_b3_staff_notifications.spec.mjs test_b2_panel_contracts.spec.mjs \
  test_g3_payment_panel.spec.mjs test_g3_reservations.spec.mjs \
  test_spanish_labels.spec.mjs
```

Logs locales: /tmp/booking-balance-subsets-final.log,
/tmp/booking-balance-booking-final.log y booking-final.xml,
/tmp/booking-d6-contracts.xml y booking-d6-contracts-rerun.xml,
/tmp/booking-balance-playwright-green.log,
/tmp/booking-balance-migrate-cycle-clean.log. Las desviaciones, alternativas y
archivos están en [deviations.md](deviations.md); los settings y pasos posteriores
autorizables de despliegue, en [deployment.md](deployment.md).

La URL y resultado del único CI se publican en el cuerpo del PR y en el reporte
final, después del único push. No requieren otro commit ni otro push. El workflow
solo despliega en push a main; el evento pull_request no ejecuta producción.
El diff stat definitivo se incorpora al cuerpo del PR después de este commit
para incluir también los documentos de verificación sin autorreferencia.
