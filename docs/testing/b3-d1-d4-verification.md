# B3 + D1–D4 — censo y evidencia local

Base verificada mediante fetch de main y `git rev-parse origin/main`:
`9bf2d09e267b1ec24470c76879c28579ca21e58b`. Rama
`feat/b3-staff-notifications`. No se accedió a producción ni se hizo merge.
Los números de línea del censo corresponden a esa base; el commit posterior de
formato cambia posiciones sin cambiar el AST de esos archivos.

## G1 — mini-censo, anterior a las modificaciones

| Caso | Punto observado en 9bf2d09 | Conclusión |
| --- | --- | --- |
| C1 | app/channel/inbound.py:484; app/payment/service.py:75–89; app/reservation/booking.py:92–115; app/channel/inbox.py:248 | El comprobante se inserta, vincula y pasa la reserva a PAYMENT_REVIEW en la transacción del inbox. attach_payment_evidence no abre otro commit. El aviso comparte esa transacción. |
| C2 | app/orchestrator/booking_flow.py:489; app/reservation/booking.py:28–80 | CONFIRM_BOOKING afirmativo llama create_pending_reservation; flush sin commit propio. La solicitud PAYMENT_PENDING y el aviso comparten la transacción. |
| C3 | app/channel/inbound.py:759 y :1065; app/channel/models.py:36 | get_or_create_customer usa upsert/lock de teléfono. Se puede interceptar al entrar a persist_inbound_message_in_session antes de crear Customer. El cliente normal conserva consulta y UNIQUE de Message.external_message_id; asesores activos usan timestamp monotónico/último ID bajo lock. |
| C4 | app/channel/inbound.py:1120; app/channel/models.py:114 | Antes se ignoraban IDs sin Message. MessageProviderStatus.message_id admite NULL y dedupe uq_provider_status. El payload es statuses con status="failed" y errors[0].code entero. |
| C5 | app/channel/outbound.py:42 y :63; app/channel/worker.py:61, :97, :157, :421, :481 y :601 | POST text con httpx y timeout; HTTPStatusError se convertía en WhatsAppSendError(str(error)) sin código. Claim/stale/backoff/settlement separados del HTTP; se reutiliza ese patrón. |
| C6 | app/orchestrator/booking_flow.py:166, :288 y :337 | consume_date_time exigía hora explícita; SELECT_BOOKING_TIME y DATETIME compartían parser. OUTSIDE_HOURS limpiaba fecha/hora y enviaba UNAVAILABLE. D1 separa aceptación de número suelto, infiere tarde y vuelve a TIME para horario inválido. |
| C7 | app/reservation/availability.py:82 y :113–130; app/config/settings.py:93; app/reservation/models.py:29; alembic/versions/20260930_0028_plan_reservation.py:75 | La regla pura prohibía cruzar fecha; BD solo exige ends_at > starts_at, sin prohibición de medianoche. Las consultas list_events usan ambos timestamps completos. |
| C7, superficies restantes | app/admin/routes.py:674, :740 y :806; app/reservation/settlement.py:244–260 y :365; frontend/app.js:1359, :1587–1588 y :1814 | Panel manual y reprogramación usan el mismo validador. Calendar recibe inicio/fin completos; su título ya usa nombre o teléfono. Expiración compara starts_at, sin truncar fin a fecha. Panel presenta ambos timestamps y reprograma por inicio. No se encontró otro recorte al mismo día. |
| C8 | app/admin/routes.py:1222–1250; frontend/app.js:1654 | Rechazo sin reserva interpolaba review_note en RESP-PAYMENT-005. El panel tenía una sola nota. D3 añade customer_reason separado y lo persiste con migración 0034. |
| C9 | app/orchestrator/service.py:3027 y :3058; app/conversation/entity_validation.py:89; data/knowledge_seed.py | COLLECT_CUSTOMER_NAME/apply_full_name/maybe_apply_name_confirmation existen. Su validador acepta más que la regla pedida; se añade extractor puro de reserva. RESP-CUSTOMER-001 y 003 están APPROVED, versión 1 en seed. Calendar ya consume Customer.full_name. |
| C10 | frontend/app.js:156; frontend/labels.mjs; app/admin/routes.py authenticated_admin; app/models_registry.py; tests/unit/test_models_registry.py; tests/payment_prereview/test_contracts.py:355 | UI usa data-admin-only y backend authenticated_admin. Registro de tablas exacto y head previo 20260930_0033 comprobados; se amplían contratos en commits test propios. |

No se activó ninguna condición DETENTE: C1/C2 son transaccionales, C3 permite
interceptar conservando dedupe, BD permite 00:00 del día siguiente y las dos
respuestas de nombre están aprobadas.

## G2 — roja en local

Backend definitivo: **78 fallos por AssertionError, 3 casos verdes**, 178,38 s.
Frontend definitivo: **3 fallos de aserción** por ausencia de la nueva vista y
del campo Nota interna. Se excluyeron intentos de preparación que fallaron por
sandbox/puertos/readiness: no se cuentan como evidencia roja.

Suite congelada en `c048251`. Contratos iniciales ampliados en `d3106ea`.
Los hashes SHA-256 de siete de los ocho archivos G2 permanecen idénticos. El
único archivo modificado es test_d2_window.py, con dos excepciones expresamente
autorizadas y commits propios:

- `881c5ad`: título «Evento existente» → «Evento existente — exclusividad» para
  respetar la regla vigente de bloqueadores externos. Se descartó bloquear todos
  los eventos de Calendar, lo que cambiaría la regla de negocio.
- `02f22c4`: expectativa HTTP 201 → 200 en creación manual, preservando sus
  comprobaciones de fin a medianoche y reprogramación. Incluye el ajuste de líneas
  del título para Ruff. Se descartó cambiar el contrato HTTP de la API.

No se modificaron los tests G2 para ocultar fallos de implementación.

## G3 — verificación

Se ejecutan únicamente los subsets afectados, contratos y regresiones del outbox
de clientes. La suite completa se reserva para CI; el segundo run se autoriza
expresamente tras el fallo de contrato descrito más adelante.

- PostgreSQL 16 local desechable, bases ceiba_b3_test, ceiba_b3_regression_test,
  ceiba_b3_frontend_test y ceiba_b3_migration_test. Meta/OpenRouter con dobles.
- Ruff check y format --check sobre copia del contenido del PR: pasan; se excluyen
  archivos previos no versionados del usuario, sin editarlos ni agregarlos.
- `make migrate-cycle` con TEST_ENV apuntando explícitamente a la base desechable:
  upgrade head → downgrade base → upgrade head, verde. Además, head → downgrade
  -1 → upgrade head, verde; 0034 vuelve correctamente a 0033 y se reaplica.
- Playwright: **49 verdes**, incluidos nuevos avisos/D3, B2, G3 pagos,
  pre-revisión, descargas fallidas y etiquetas en español.
- Contratos/unitarios seleccionados finales: **201 verdes**, incluidas
  validaciones de settings, códigos permanentes, prefijos de nombre, red y
  truncado de motivos. Sin modificación de los tests previos del outbox.
- Primera corrida amplia: 399 verdes y 5 fallos; cuatro usaban expectativas
  anteriores recogidas antes de corregirlas. Un guard de transacciones de Calendar
  falló y pasó en la comprobación aislada. Los cinco casos afectados sumaron
  15 verdes al repetir sus parametrizaciones. La corrida final pasó completa.

| Subset requerido | Verdes |
| --- | ---: |
| tests/staff_notifications | 36 |
| tests/booking_conversation | 143 |
| tests/payment_settlement | 83 |
| tests/payment_prereview | 53 |
| tests/booking_backend | 90 |
| Total | 405 |

Corrida final: **405 passed in 1022.10s**. Regresiones adicionales afectadas:
tests/integration/test_outbox_worker.py,
tests/integration/test_b1a_plan_reservation_admin.py y
tests/test_w2b_payment_evidence_adversarial.py: **63 passed in 371.31s**.
Verificación posterior de los últimos cambios de frontera de canal, motivo y
fecha: staff_notifications + test_d3_customer_reason + test_g3_clock_contracts,
**43 passed in 147.57s**. Contratos finales: **201 passed in 3.14s**.

Comando principal reproducible (TEST_DATABASE_URL debe apuntar a una base de
pruebas PostgreSQL desechable):

```bash
QUALITY_STAGE=suite pytest tests/staff_notifications tests/booking_conversation \
  tests/payment_settlement tests/payment_prereview tests/booking_backend -q
```

## Desviaciones y decisiones declaradas

- app/config/settings.py y .env.example: default HOURS_END pasa de 21:00 a 24:00,
  autorizado. Se descartó dejar defaults incompatibles con LATEST_START < END.
- Commit de formato general: autorizado por 136 archivos detectados inicialmente;
  se limita a los 127 archivos versionados que siguen pendientes tras ajustar
  el fixture G2. Se verifica equivalencia de AST, incluidas dos divisiones de
  literales necesarias para E501. Los artefactos ajenos no entran al PR.
- `dbb8522` contiene exclusivamente formato general; `d3106ea` y `8f611cc`
  contienen los contratos propios. D1/D2/D4 comparten booking_flow y se agrupan
  por área en `4ce289b`, con catálogo y states.md en el mismo commit. Se descartó
  repartir artificialmente los mismos bloques de ese archivo entre commits.
- Ruff sobre `.` se ejecutó en /tmp/ceiba-b3-quality-stage, copia completa del
  contenido del PR: **369 archivos formateados**, lint verde. En la carpeta de
  trabajo hay scripts no versionados previos bajo docs/remediation y docs/reports
  que producen errores ajenos al PR; se descarta agregarlos o editarlos. No se
  alteró la configuración de Ruff para esconderlos en CI.
- frontend/server.mjs: nuevas rutas administrativas requieren proxy; se extiende
  conservando autenticación, queries y cuerpos. Se descartó acceso directo desde
  el navegador a la API, que rompería el patrón del panel.
- app/payment/customer_reason.py y app/conversation/presentation.py: valor humano
  saneado con tipo explícito para RESP-PAYMENT-005; strings arbitrarios del cliente
  no son renderizables. Se descartó seguir reutilizando review_note interna.
- Tests históricos afectados de pagos/horario se amplían en commit test propio:
  motivo visible separado, TIME en horario inválido y cierre por defecto 24:00.
  Se conservan pruebas de auditoría, idempotencia, permisos y agenda.
- Se prepara el PR draft contra main después del primer push. La excepción
  posterior para un segundo push y CI se declara a continuación. Sus resultados
  se informan en el PR y en el cierre, sin afirmar resultados aún no observados.

## CI inicial y excepción posterior autorizada

PR draft: https://github.com/epr3202/CHAT_BOT_CEIBA/pull/39.
Primer run: https://github.com/epr3202/CHAT_BOT_CEIBA/actions/runs/37027602074,
SHA 4a82ca9e8b9c8c6f2d237b95ca4c6aa0e0f3ffff. Ruff y migrate-cycle remotos verdes;
la suite completa de backend sigue en curso al publicar la corrección.
Frontend: 69 verdes y 1 fallo en test_b2_payment_amount.spec.mjs:37:
`locator('textarea') resolved to 2 elements`. Es un contrato histórico omitido
de la selección local, no un fallo de infraestructura.

Corrección preparada: seleccionar Nota interna por etiqueta, comprobar que la
nota sola no permite rechazar sin motivo visible, completar ese motivo y verificar
el JSON con ambos campos. Diff del test: 7 líneas añadidas, 3 retiradas. Mantiene
la comprobación del monto y añade la exigencia de D3. Verificación local con el
spec corregido y los tres casos B3/D3: **4 verdes**, Ruff verde. No cambia G2.

Emerson autorizó expresamente «Autorizar un push adicional y un segundo CI»
después de revisar esta corrección y su evidencia. Posteriormente indicó
«mandalo antes que termine el otro»: el segundo push se publica con el primer
run todavía en curso. Se descarta relanzarlo como infraestructura, cambiar D3
para conservar un único campo o publicar sin esa excepción a §9.
El resultado del segundo run se informa en el PR y el cierre.

## Primeras líneas de cada fallo G2

Las entradas siguientes provienen del log definitivo anterior a implementar.

- `test_tc_b3_001_002_003_evidence_atomic_deduplicated[True]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_001_002_003_evidence_atomic_deduplicated[False]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_004_pending_atomic`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_005_sanitize[a\n b\t c\r d-a b c d]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_005_sanitize[  a    b  -a b]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_005_sanitize[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_005_sanitize[\n\t  --]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_005_params[Laura G\xf3mez-Laura G\xf3mez (+57 300 000 0123)]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_005_params[None-+57 300 000 0123]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.staff_texts`

- `test_tc_b3_006_007_channel_and_no_http_in_transaction[1--TEXT]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_006_007_channel_and_no_http_in_transaction[23.5-aviso_comprobante_reserva-TEMPLATE]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_006_007_channel_and_no_http_in_transaction[24-aviso_comprobante_reserva-TEMPLATE]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_006_007_channel_and_no_http_in_transaction[24--DEFERRED]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_008_error_codes[500-131000-True]`: `E   assert None == 131000`

- `test_tc_b3_008_error_codes[429-130429-True]`: `E   assert None == 130429`

- `test_tc_b3_008_error_codes[400-130429-True]`: `E   assert None == 130429`

- `test_tc_b3_008_error_codes[400-132001-False]`: `E   assert None == 132001`

- `test_tc_b3_008_error_codes[400-131047-False]`: `E   assert None == 131047`

- `test_tc_b3_008_error_codes[400-999999-False]`: `E   assert None == 999999`

- `test_tc_b3_008_error_codes[401-190-False]`: `E   assert None == 190`

- `test_tc_b3_008_backoff_and_exhaustion[False-0-PENDING]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_008_backoff_and_exhaustion[True-0-FAILED]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_008_backoff_and_exhaustion[False-4-FAILED]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_009_status_monotonic_and_dedupe`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_009_131047_recovery[aviso_comprobante_reserva-PENDING]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_009_131047_recovery[-DEFERRED]`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_010_staff_inbound_reopens_and_is_silent`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_010_inactive_is_customer`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_011_expiration_and_disabled_flag`: `E   AssertionError: B1a: falta implementar el módulo app.notifications.models`

- `test_tc_b3_012_admin_crud_audit_and_masking`: `E   AssertionError: {"detail":"Not Found"}`

- `test_tc_b3_012_agent_forbidden[GET-/admin/notification-recipients-None]`: `E   AssertionError: {"detail":"Not Found"}`

- `test_tc_b3_012_agent_forbidden[POST-/admin/notification-recipients-body1]`: `E   AssertionError: {"detail":"Not Found"}`

- `test_tc_b3_012_agent_forbidden[PATCH-/admin/notification-recipients/1-body2]`: `E   AssertionError: {"detail":"Not Found"}`

- `test_tc_b3_012_agent_forbidden[POST-/admin/notification-recipients/1/test-None]`: `E   AssertionError: {"detail":"Not Found"}`

- `test_tc_b3_012_agent_forbidden[GET-/admin/staff-notifications-None]`: `E   AssertionError: {"detail":"Not Found"}`

- `test_d1_clock_resolution[7-expected0]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[7 pm-expected1]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[a las 7-expected2]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[las 8-expected3]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[7:30-expected4]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[12-expected5]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[1-expected6]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[9-expected7]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[10-expected8]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[7 am-expected9]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[11 am-expected10]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[7 de la tarde-expected11]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_clock_resolution[7 de la ma\xf1ana-expected12]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_datetime_never_takes_the_day_as_time`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.resolve_booking_clock`

- `test_d1_conversation_with_meta_double[7-CONFIRM_BOOKING]`: `E   AssertionError: assert 'SELECT_BOOKING_TIME' == 'CONFIRM_BOOKING'`

- `test_d1_conversation_with_meta_double[7 am-SELECT_BOOKING_TIME]`: `E   AssertionError: assert 'SELECT_BOOKING_DATETIME' == 'SELECT_BOOKING_TIME'`

- `test_d2_midnight_window[21-0-24:00-True-None]`: `E   AssertionError: Falta BOOKING_LATEST_START`

- `test_d2_midnight_window[21-30-24:00-False-OUTSIDE_HOURS]`: `E   AssertionError: Falta BOOKING_LATEST_START`

- `test_d2_midnight_window[11-30-24:00-False-OUTSIDE_HOURS]`: `E   AssertionError: Falta BOOKING_LATEST_START`

- `test_d2_midnight_window[12-0-24:00-True-None]`: `E   AssertionError: Falta BOOKING_LATEST_START`

- `test_d2_midnight_window[21-0-23:59-False-OUTSIDE_HOURS]`: `E   AssertionError: Falta BOOKING_LATEST_START`

- `test_d2_calendar_conflict_after_23`: `E   AssertionError: assert 'booking_latest_start' in {'database_url': FieldInfo(annotation=str, required=True, alias='DATABASE_URL', alias_priority=2), 'db_pool_size': Fie...lopment', 'testing', 'production'], required=False, default='development', alias='ENVIRONMENT', alias_priority=2), ...}`

- `test_d2_panel_manual_and_reschedule`: `E   AssertionError: assert 'booking_latest_start' in {'database_url': FieldInfo(annotation=str, required=True, alias='DATABASE_URL', alias_priority=2), 'db_pool_size': Fie...lopment', 'testing', 'production'], required=False, default='development', alias='ENVIRONMENT', alias_priority=2), ...}`

- `test_d4_pure_name[Emerson Pulgar\xedn-Emerson Pulgar\xedn]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[me llamo laura g\xf3mez-Laura G\xf3mez]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[Soy Ana-Ana]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[\xa1Hola! mi nombre es mar\xeda jos\xe9-Mar\xeda Jos\xe9]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[habla Ana-Ana]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[con Jos\xe9-Jos\xe9]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[Ana-Mar\xeda O'Neill-Ana-Mar\xeda O'Neill]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[7 pm-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[https://x.co-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[a-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[@ana-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[a b c d e f-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_pure_name[XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX-None]`: `E   AssertionError: B1a: falta el contrato app.orchestrator.booking_flow.extract_booking_name`

- `test_d4_collects_name_then_confirms_without_echo`: `E   AssertionError: assert 'CONFIRM_BOOKING' == 'COLLECT_BOOKING_NAME'`

- `test_d4_two_invalid_names_handoff`: `E   AssertionError: assert 'CONFIRM_BOOKING' == 'COLLECT_BOOKING_NAME'`

- `test_d3_requires_customer_reason_without_urls[None-Escribe el motivo que ver\xe1 el cliente]`: `E   AssertionError: {"id":1,"amount_cop":null,"review_status":"REJECTED","reviewed_by_agent_id":1,"reviewed_at":"2026-10-02T13:47:25.804106Z","evidence":{"id":1,"amount_cop":null,"review_status":"REJECTED","reviewed_by_agent_id":1,"reviewed_at":"2026-10-02T13:47:25.804106Z"},"reservation":null,"result":"REJECTED","missing_cop":null,"blockers":[],"calendar_synced":null,"detail":null,"customer_notification":"DEFERRED"}`

- `test_d3_requires_customer_reason_without_urls[  -Escribe el motivo que ver\xe1 el cliente]`: `E   assert 'Escribe el motivo que verá el cliente' in '{"detail":[{"type":"extra_forbidden","loc":["body","customer_reason"],"msg":"Extra inputs are not permitted","input":"  "}]}'`

- `test_d3_requires_customer_reason_without_urls[Mira https://x.co-No incluyas enlaces en el motivo]`: `E   assert 'No incluyas enlaces en el motivo' in '{"detail":[{"type":"extra_forbidden","loc":["body","customer_reason"],"msg":"Extra inputs are not permitted","input":"Mira https://x.co"}]}'`

- `test_d3_requires_customer_reason_without_urls[www.ejemplo.co-No incluyas enlaces en el motivo]`: `E   assert 'No incluyas enlaces en el motivo' in '{"detail":[{"type":"extra_forbidden","loc":["body","customer_reason"],"msg":"Extra inputs are not permitted","input":"www.ejemplo.co"}]}'`

- `test_d3_internal_note_separate_and_visible_reason_sanitized`: `E   AssertionError: assert 'customer_reason' in <sqlalchemy.sql.base.ReadOnlyColumnCollection object at 0x71e979f31ad0>`

Frontend G2: test_b3_staff_notifications.spec.mjs, casos «solo ADMIN», «crear/editar/prueba» y «D3 rechazo»: Expected visible; locator de Avisos a asesores o Nota interna no existe.
