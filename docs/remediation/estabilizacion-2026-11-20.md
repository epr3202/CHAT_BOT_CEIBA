# Evidencia de estabilización · 20 de noviembre de 2026

## Procedencia

La base fue main en `d0b8736d368087f90cf65229b8feffac0e419bfc`. El PR #48 había incorporado la consulta informativa de disponibilidad y los intervalos de hospedaje. El candidato recoge el guard de reservas y avisos del PR #49 (`1f897f14be1b330b1837cef92aa740eaa5a9ef41`) y la captura de formularios del PR #52 (`5a9d14c6a004780cd1352a8929e72bf6b7bd89c2`). La revisión seleccionó los cambios sobre la base de main. El PR #50 trata el selector de indicativo telefónico y el modal de confirmación. El PR #51 trata la presentación del panel y el modo oscuro. Ambos siguen su propio curso.

## Lecturas de producción

| Comprobación | Fuente del 20 de noviembre, UTC | Resultado |
|---|---|---|
| Checkout e imágenes activas | 21:59, `git rev-parse HEAD`, Docker Compose y cotejo de SHA-256 contra Git | SHA de la base. Los 179 archivos de Python y documentación conversacional comprobados concuerdan tanto en app como en worker. |
| Esquema | 21:40, `SELECT version_num FROM alembic_version` | `20261028_0037` |
| Configuración efectiva | 21:59, `get_settings()` dentro de app y worker, lectura de cuatro campos | Meta v26.0, Calendar google, anticipación global 1, autoservicio habilitado en ambos. |
| Salud | 21:59, `GET /ready`, `GET /` del panel, `docker compose ps` | HTTP 200 en ambas consultas. App, worker y admin en ejecución. PostgreSQL healthy. |
| Actividad y entrega | 21:40, PostgreSQL en transacción de solo lectura, últimos siete días | 38 mensajes entrantes. Outbox con 33 SENT y 2 SUPPRESSED. Último envío 19:56:25 UTC. Estados de proveedor con 33 sent, 29 delivered y 20 read. Cero errores de proveedor registrados en esa ventana. Los estados pueden corresponder a los mismos mensajes. |
| Google Calendar | Comprobación previa del worker a las 21:26 UTC | Los dos calendarios configurados respondieron. Visitas La Ceiba informó permiso writer. Se reutilizó esa lectura. |
| Respuestas aprobadas | 21:40, versiones aprobadas en PostgreSQL | Propuestas v2, cenas románticas v3, confirmación previa v2 y datos de pago v3. |
| Planes y PDF | 21:40, ocho planes activos. PDF de propuestas obtenido de su almacenamiento y contrastado con PostgreSQL | Huella SHA-256 `2827c1d2d4d1bd9c7c549b671086ccbddc522782e6c6d858c14fe2bbae10f658`. Ocho registros de envío del activo. |

Las plantillas efectivas de confirmación previa v2, datos de pago v3, error de agenda v2 y respuesta de servicios v2 coinciden con el texto versionado. Las de propuestas v2 y cenas románticas v3 difieren del seed y no contienen importes literales precedidos por el signo de pesos. Hospedaje mantiene en producción la versión 1. La retirada de la frase de un día tiene aprobación expresa para la versión 2 del candidato.

### Conciliación pendiente de autorización comercial

| Experiencia | PostgreSQL y seed | PDF activo | Propuesta comercial aportada |
|---|---|---|---|
| Entre Pétalos y Estrellas | $450.000, 180 min, sin exclusividad | $450.000, cena para dos | $450.000, 150 min |
| Confesión bajo la Luna | $900.000, 180 min, sin exclusividad | $900.000, cena para dos | $800.000, 150 min |
| Noche Inolvidable | $2.500.000, 180 min, exclusiva | $2.500.000, cena para dos y terraza exclusiva | Una Noche Inolvidable, $1.700.000, 210 min |
| Amor puro y natural | Ausente | Ausente en este PDF | $2.000.000, 210 min |

A las 22:20 UTC se contrastó también el PDF activo de planes románticos de 12 páginas, huella SHA-256 `0a5ba23944985606da39d8f0402d985dc1620b1f1a417bf66ae35bc262f57d39`, con 16 envíos registrados. Presenta Romance entre Copas para dos por $400.000. Los otros planes activos de este PDF y sus precios de PostgreSQL son Ritual del Corazón $250.000, Mañanas de Encanto $450.000, Cinema y Amor $700.000 y Refugio para Dos $1.000.000. En PostgreSQL los cinco tienen duración de 180 minutos y el indicador de exclusividad desactivado. Los dos PDF contienen importes que los clientes pueden recibir aunque una plantilla de chat omita los precios.

El seed conserva los códigos ya existentes. La tabla de planes carece de un campo de personas. La comparación de personas y exclusividad de la oferta propuesta requiere ratificación comercial. El candidato conserva los valores de producción.

## Controles con datos sintéticos

| Criterio | Fallo reproducido o control independiente | Verificación del candidato |
|---|---|---|
| Preparación de pruebas | El destino `contest` superaba el guard anterior. El esquema de la fixture carecía del trigger de revisiones. | `tests/unit/test_test_database_target.py`, `tests/integration/test_stabilization_schema.py` y `tests/payment_prereview/test_contracts.py::test_r8_migration_round_trip`. El último intenta UPDATE y DELETE sobre una revisión insertada. |
| Confirmadas y reentregas | Una solicitud repetida después del reset llegaba a crear otro pendiente. El panel también admitía una solicitud manual del mismo cliente, plan y franja. | `tests/booking_conversation/test_duplicate_reserved_guard_g2.py`, `test_duplicate_reserved_guard_edges.py` y `test_adjacent_booking.py`. El control manual pasó de HTTP 200 a 409. |
| Avisos del asesor | La fuente podía salir de estado tras el claim. | `tests/staff_notifications/test_superseded_edges.py` y `test_superseded_g2.py` comprueban entrega, auditoría y callbacks tardíos. |
| FreeBusy | Un intervalo sin end llegó a producir horas disponibles. | `tests/integration/test_incomplete_calendar.py` exige cero slots, respuesta aprobada de error y revisión. Los controles de respuesta completa consultan el adaptador con HTTP simulado. |
| Formularios y privacidad | $15.000 se interpretaba como millones, $15.000.000 detenía el turno y una negativa de correo permitía guardarlo. | `tests/visit_booking_guard/test_prefilled_independent.py` y `test_prefilled_visit.py`. Se comprueba la corrección de nombre y presupuesto, retirada del correo, motivo de boda, dos asistentes a la visita y menos de 50 invitados al evento. |
| Caso romántico y anticipación | Ambos mensajes históricos recibían una petición genérica de fecha. | `tests/booking_conversation/test_stabilization_flows.py` usa los relojes de Bogotá, un PATCH autenticado, una franja ocupada, reentrega idéntica, cambio de fecha y una aceptación humana sintética. Comprueba contenido de panel, handoff y evento del adaptador. |
| Valor comercial | Un texto recibido puede incluir precio base, subtotal y extras distintos al catálogo. | El precio histórico procede del plan. El control independiente declaró $12.345 de base y $999.999 de subtotal. La solicitud quedó en $400.000, con pago cero y ambos importes declarados diferenciados. |
| Visibilidad | Las notas libres podían quedar fuera de la solicitud una vez cerrada la conversación. | También se abrió la reserva del recorrido anterior en Chromium, con FastAPI y PostgreSQL reales. Admin y asesor vieron personas, ocasión, noche, violín, fotografía y ambos importes informados. |
| Recuperación | El script anterior terminaba después del fallo del seed con los servicios detenidos. | `bash tests/smoke_deploy_reexec.sh` inserta una tabla y altera precios antes de fallar. Exige restauración real del dump, mismo precio y revisión, tres servicios activos, HTTP 200, archivo 0600 y selección de un SHA distinto de la punta de main. |

La anticipación por plan hereda el valor global mediante una columna nullable. Los textos aprobados para fecha pasada y plazo mínimo están en el registro conversacional. Hospedaje adopta la versión 2 sin el plazo fijo. El aviso de respaldo de una reserva ya confirmada usa la transferencia genérica aprobada. Los mensajes originales permanecen en el historial append-only incluso al retirar un correo de contacto.

La actualización de pruebas históricas afecta revisiones concretas de Alembic, el texto aprobado de hospedaje y la expectativa de pedir una hora para un día que ya incumple el plazo. La expectativa nueva exige la fecha más próxima admitida. La prueba que renderiza todas las plantillas aprobadas señaló que faltaban ejemplos para dos variables nuevas. Se añadieron una fecha y un número de días al conjunto de entradas. Se conservaron sus comprobaciones de cobertura, valores internos y fechas ISO. Dos pruebas históricas señalan que el analizador compartido debe excluir fechas vencidas de su salida ordinaria. Se conservó esa expectativa. El flujo que explica una fecha rechazada pide explícitamente recuperar la fecha histórica. El 20 de noviembre a las 22:29 UTC se reinició Docker local y la primera ejecución general perdió el servidor de pruebas. Se conservó la salida de ese intento y se repitió el ciclo sobre un volumen dedicado. Al ejecutar cuatro procesos pytest sobre el mismo servidor, tres pruebas alcanzaron el máximo de 100 conexiones. Sus trazas registraron `TooManyConnectionsError`. Se destinó capacidad para 350 conexiones al servidor desechable y se volvieron a ejecutar los tres grupos afectados. Para evaluar sobreajuste se reintrodujeron fallos en copias desechables y se exigió que fallara la aserción correspondiente.

### Resultados independientes de la suite general

- En dos sesiones de Chromium con roles ADMIN y AGENT se abrió la misma reserva sintética persistida por el recorrido de WhatsApp. Ambas mostraron Romance entre Copas, precio base histórico de $400.000, dos personas, Aniversario, Noche, violín, fotografía y los importes declarados.
- Una ejecución adicional con el seed versionado completó la visita a partir del formulario. En el primer turno devolvió las reglas de visita y «La fecha que indicaste, 29 de octubre de 2026, ya pasó. ¿Qué nueva fecha te gustaría revisar?». En una conversación transferida al asesor se retiró el correo ante una negativa expresa, se registró la auditoría y no se añadió ninguna respuesta del bot.
- En la vista Planes de Chromium se cambió la anticipación de Romance entre Copas de 20 a 7 en una base desechable. El PATCH devolvió HTTP 200. Al recargar, el campo seguía en 7 y una conexión independiente devolvió `ROMANCE_COPAS|7` al consultar PostgreSQL.
- Diez cambios deliberados en copias aisladas produjeron fallos de aserción. Afectaron el año de la fecha pasada, el límite de franja contigua, la agenda incompleta, el presupuesto, el correo rechazado, los adicionales extensos, la persistencia del resumen comercial de la reserva, la revalidación final, el aviso obsoleto y el callback tardío. El primer intento de ejecutar la prueba de aviso usó un identificador de prueba incorrecto. Con la ruta corregida, pytest ejecutó el caso y falló por el estado observado.
- Un segundo ensayo introdujo una migración sintética posterior a 0039 antes del fallo de carga. El proceso alcanzó `rehearsal_0040` y recuperó `20261120_0039`, $400.000, tres servicios en ejecución, HTTP 200 en ambos servicios HTTP y respaldo 0600. SHA de ensayo recuperado `d02e736ab6576edbf34b7f383a061b5ed3322b5f`. SHA de ensayo fallido `a3ed429afef196e8d737a03ea7e6d0c037803c18`. Destino explícito probado `39f9cc645df066f2ea6341ba2cd0c87810231c24`.

- En el ensayo con los archivos de la versión desplegada se arrancó el script antiguo sobre 0037. El nuevo script recibió el control, migró hasta 0039 y se forzó el fallo del seed. Se verificaron la vuelta a 0037, la ausencia de la tabla del intento fallido, el precio original, /ready y panel HTTP 200 y el worker en ejecución. El siguiente despliegue al SHA explícito alcanzó 0039. El resultado del repositorio sintético fue `PASS final_schema=20261120_0039 recovered_schema=20261028_0037 previous=7ca061136cdc72394fccda3878012407de3c7f4c failed=809e80c4af74f1c2ac8cf3ae3ed12fc5e73c4631 explicit_target=064be3fc3f556df2b71f8f6578b2db78840ad14a schema=20261028_0037 price=400000 backup_mode=600`.

## Reproducción

Usar PostgreSQL 16 desechable y exportar TEST_DATABASE_URL antes de los comandos. Las pruebas de Meta, Google y OpenRouter usan dobles locales. Los envíos observados en producción corresponden al tráfico que ya había registrado el servicio.

```bash
ruff check .
make migrate-cycle PYTHON=python
alembic current
pytest -q
npm ci --prefix tests/frontend
# En una base diferente, desechable y migrada, con DATABASE_URL = TEST_DATABASE_URL:
python -m tests.frontend.seed_admin
ENVIRONMENT=production npm --prefix tests/frontend test
bash tests/smoke_deploy_reexec.sh
```

La ruta de rollback exige el SHA completo. Si la revisión del destino es incompatible, hay que ensayar una restauración y revisar las escrituras que podrían perderse antes de autorizar el cruce de esquema. El cifrado de los respaldos queda pendiente de un procedimiento de custodia y recuperación de claves.

## Cierre para revisión

| Estado | Criterio | Evidencia observable |
|---|---|---|
| ✅ | Base de trabajo y alcance | `git ls-remote --heads origin main` devolvió `d0b8736d368087f90cf65229b8feffac0e419bfc`. El árbol de trabajo es propio de la rama de estabilización. |
| ✅ | Base desechable y migraciones | `make migrate-cycle PYTHON=python` seguido de `alembic current` devolvió `20261120_0039 (head)`. El mismo comando contra el nombre de base `ceiba` terminó con código 2 antes de conectarse. |
| ✅ | Reservas duplicadas y avisos vigentes | Los casos de reset, reentrega, confirmación intermedia, solapamiento parcial y ambas franjas contiguas pasaron. El endpoint manual rechazó el conflicto con HTTP 409. La inversión del criterio de vigencia volvió a fallar en `test_literal_staff10_cancelled_d79893e0_never_sends`. |
| ✅ | Agenda y formularios | El caso de FreeBusy parcial dio cero opciones. Con reloj de Bogotá del 3 de noviembre los dos formularios capturaron sus datos iniciales y solicitaron una nueva fecha. Las pruebas con el seed versionado y el retiro del correo durante atención humana también pasaron. |
| ✅ | Anticipación, persistencia y asesor | Edición en Planes con HTTP 200 y confirmación por SQL. Los recorridos comprobaron medianoche, revalidación, reentrega, dos adicionales, histórico tras reset y coincidencia del contenido en panel, transferencia y adaptador de Calendar. |
| ✅ | Restauración y rollback | El ensayo local con los archivos de main recuperó 0037 tras aplicar 0039, restauró el precio y levantó tres servicios. La petición a /ready y la petición al panel devolvieron HTTP 200. |
| ✅ | Ruff y Playwright | `ruff check .` devolvió `All checks passed!`. `ENVIRONMENT=production npm --prefix tests/frontend test` terminó con `77 passed (1.9m)`. |
| ❌ | Conciliación comercial publicada | Quedan cuatro diferencias con el portafolio propuesto. Hace falta autorización por código y versión de catálogo antes de publicar. |
| ✅ | Suite Python congelada y revisión del cambio | `pytest -q --tb=short` en cuatro grupos disjuntos de archivos sobre PostgreSQL 16.14. Resultados 767, 664, 840 y 649 aprobados. Total **2.920 de 2.920** en 184 archivos, con 20 advertencias. La recopilación independiente verificó que cada caso perteneciera a un solo grupo. La revisión de 76 rutas y `git diff --check` terminaron sin hallazgos de las credenciales o identidades buscadas. |
| ❌ | Protección de main al cierre local | La consulta del 20 de noviembre a las 23:11 UTC devolvió `protected: false`. El conector no expone la escritura de protección y el cliente local de GitHub no tenía sesión autenticada. |

La huella SHA-256 del manifiesto local de archivos de ejecución, pruebas y documentación funcional fue `f5c4754f7111cb4e466850c5b7a4a33e702ac0459cc3c5c38e067ee7baf4c4e5`. El SHA definitivo del candidato y el resultado del workflow quedan asociados al PR.
