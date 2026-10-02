# G2 rojo — 2026-10-02

Producto base c5812f5267e9c99208282e2a3baed66f9fb02cb7 sin modificaciones.
La continuación transmitida por Emerson autoriza la excepción R9 y revoca la
detención histórica G1. Tests congelados en b01cf91.

73 casos Python distintos: **58 FAILED por AssertionError, 15 PASS**.
Playwright nuevo: **2 FAILED por aserción de interfaz**. Ningún error final de
colección, fixture, ImportError o AttributeError. Proveedores simulados y
PostgreSQL local exclusivo con bases test y almacenamiento temporal.

Selección inicial: 69 casos, 55 FAILED/14 PASS. D5 se amplió antes del commit
con cuatro contratos (parcial con otra evidencia pendiente y rechazo en tres
estados) y espías Calendar; ejecución final: 13 FAILED/2 PASS. Antes de congelar
se quitó de T9 una exigencia extra no pedida: cero llamadas al clasificador.
El contrato pide silencio al cliente, y el código clasifica en silencio.
T9 conserva outbox/evidencia vacíos y estado pausado; reejecución final: 1 PASS.
No se atribuye rojo nuevo a esa corrección de alcance previa al commit.

El commit rojo es la excepción explícita al gate general AGENTS. El staging
explícito conserva fuera del PR documentos locales ajenos. Ruff G2 pasa.
El check global de formato incluye nueve scripts a13/a14 locales no seguidos
previos a la tarea; la verificación global final usará copia limpia del commit.
El manifiesto registra los bytes del commit b01cf91. Los contratos históricos
se extienden por separado y no se atribuye G2 rojo retroactivo a esas extensiones.

## Primera línea de cada fallo Python

| Caso | Primera aserción |
| --- | --- |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p1_extraction_has_no_transaction_and_evidence_lock_is_free[worker]` | AssertionError: D6: extract_receipt fue llamado con una transacción abierta |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p1_extraction_has_no_transaction_and_evidence_lock_is_free[endpoint]` | AssertionError: D6: extract_receipt fue llamado con una transacción abierta |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p2_human_accepts_during_extraction_and_ai_result_is_discarded[worker]` | AssertionError: D6: la extracción bloqueó la aceptación humana |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p2_human_accepts_during_extraction_and_ai_result_is_discarded[endpoint]` | AssertionError: D6: la extracción bloqueó la aceptación humana |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p3_expired_prereview_lease_is_reclaimed` | AssertionError: D6: falta payment_evidence.prereview_claim_token |
| `tests/payment_prereview/test_d6_no_http_in_tx.py::test_p4_worker_live_lease_makes_admin_retry_conflict` | AssertionError: D6: falta payment_evidence.prereview_claim_token |
| `tests/booking_balance/test_b4.py::test_r1_two_reminders_exact_payload_bogota_and_flag_off` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r2_fully_paid_before_due_produces_nothing` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r2_queued_reminder_expires_without_http_after_full_payment` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r3_late_booking_skips_early_once_and_sends_due` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r4_overdue_marks_once_and_notifies_active_evidence_recipients` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r5_missing_customer_template_does_not_enqueue_and_audits` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r5_provider_permanent_and_retryable_errors[400-132001-FAILED]` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r5_provider_permanent_and_retryable_errors[503-131000-PENDING]` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r6_customer_statuses_use_null_message_and_are_deduplicated[False]` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/booking_balance/test_b4.py::test_r6_customer_statuses_use_null_message_and_are_deduplicated[True]` | AssertionError: B1a: falta implementar el módulo app.reservation.reminders |
| `tests/staff_notifications/test_f1_phone.py::test_f1_normalizes_colombian_phone[3001234567]` | AssertionError: assert '+3001234567' == '+573001234567' |
| `tests/staff_notifications/test_f1_phone.py::test_f1_normalizes_colombian_phone[300 123 4567]` | AssertionError: assert '+3001234567' == '+573001234567' |
| `tests/staff_notifications/test_f1_phone.py::test_f1_invalid_phones_have_spanish_error[+5730012345]` | AssertionError: {"id":1,"display_name":"Asesor","phone_number":"+5730012345","notify_on_evidence":true,"notify_on_payment_pending":false,"active":true,"last_inbound_at":null,"ventana_abierta_hasta":null} |
| `tests/staff_notifications/test_f1_phone.py::test_f1_duplicate_after_normalization_is_conflict` | AssertionError: {"id":2,"display_name":"Dos","phone_number":"+573001234567","notify_on_evidence":true,"notify_on_payment_pending":false,"active":true,"last_inbound_at":null,"ventana_abierta_hasta":null} |
| `tests/staff_notifications/test_f1_phone.py::test_f1_created_local_phone_intercepts_provider_sender` | AssertionError: El número normalizado debe interceptarse como asesor |
| `tests/staff_notifications/test_f1_phone.py::test_f5_post_patch_warn_if_customer_has_conversations` | AssertionError: assert None == 'Este número tiene conversaciones como cliente. Mientras esté activo como asesor, el bot no le responderá.' |
| `tests/staff_notifications/test_f2_reopen.py::test_f2_reopen_clears_window_error_and_uses_text` | assert (131047 is None) |
| `tests/booking_conversation/test_f3_clock.py::test_f3_tomorrow_is_date_not_am[ma\xf1ana a las 7-expected0]` | AssertionError: assert datetime.time(7, 0) == datetime.time(19, 0) |
| `tests/booking_conversation/test_f3_clock.py::test_f3_tomorrow_is_date_not_am[manana a las 7-expected1]` | AssertionError: assert datetime.time(7, 0) == datetime.time(19, 0) |
| `tests/booking_conversation/test_f3_clock.py::test_f3_tomorrow_consumes_next_day_and_evening` | AssertionError: assert '07:00' == '19:00' |
| `tests/booking_conversation/test_f3_clock.py::test_f3_morning_remains_outside_booking_hours[a las 7 de la ma\xf1ana]` | AssertionError: assert 'SELECT_BOOKING_DATETIME' == 'SELECT_BOOKING_TIME' |
| `tests/payment_settlement/test_f4_notification.py::test_f4_rejection_without_customer_reason_defers_and_audits` | AssertionError: El rechazo sin motivo visible debe diferirse sin excepción |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-PLAN-001]` | AssertionError: RESP-BOOKING-PLAN-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-DATETIME-001]` | AssertionError: RESP-BOOKING-DATETIME-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-TIME-001]` | AssertionError: RESP-BOOKING-TIME-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-UNAVAILABLE-001]` | AssertionError: RESP-BOOKING-UNAVAILABLE-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-CONFIRM-001]` | AssertionError: RESP-BOOKING-CONFIRM-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-PAYMENT-001]` | AssertionError: RESP-BOOKING-PAYMENT-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-EVIDENCE-001]` | AssertionError: RESP-BOOKING-EVIDENCE-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-CONFIRMED-001]` | AssertionError: RESP-BOOKING-CONFIRMED-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-PARTIAL-001]` | AssertionError: RESP-BOOKING-PARTIAL-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-REJECTED-001]` | AssertionError: RESP-BOOKING-REJECTED-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-PAYMENT-004]` | AssertionError: RESP-PAYMENT-004 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-PAYMENT-005]` | AssertionError: RESP-PAYMENT-005 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-FILE-002]` | AssertionError: RESP-FILE-002 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-EVENTS-ROMANTIC-001]` | AssertionError: RESP-EVENTS-ROMANTIC-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-EVENTS-PROPOSAL-001]` | AssertionError: RESP-EVENTS-PROPOSAL-001 debe sembrarse APPROVED |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-BALANCE-PAID-001]` | AssertionError: Falta plantilla aprobada RESP-BOOKING-BALANCE-PAID-001 |
| `tests/payment_settlement/test_booking_template_alignment.py::test_seed_matches_approved_production_codes[RESP-BOOKING-BALANCE-PARTIAL-001]` | AssertionError: Falta plantilla aprobada RESP-BOOKING-BALANCE-PARTIAL-001 |
| `tests/payment_settlement/test_booking_template_alignment.py::test_file_receipt_has_payment_receipt_literal` | AssertionError: assert '[REVISAR] En... Comprobante.' == 'Gracias, ya ...sea aprobada.' |
| `tests/booking_balance/test_d5.py::test_t1_incident_196_two_100000_deposits_resolve_handoff` | AssertionError: El segundo abono requiere acuse RESP-BOOKING-EVIDENCE-001 |
| `tests/booking_balance/test_d5.py::test_t2_two_images_during_review_both_link_and_ack_without_extra_transition` | AssertionError: Las dos imágenes deben vincularse mientras la reserva sigue en PAYMENT_REVIEW |
| `tests/booking_balance/test_d5.py::test_t3_balance_paid_in_new_conversation_without_calendar_mutation` | AssertionError: Imagen d5.t3.a no produjo evidencia |
| `tests/booking_balance/test_d5.py::test_t4_taken_handoff_captures_evidence_without_automatic_ack` | AssertionError: assert None == UUID('a4f6efec-ced4-4c4a-9437-53b4f743c982') |
| `tests/booking_balance/test_d5.py::test_t5_past_or_cancelled_booking_is_never_linked[PAYMENT_PENDING-True]` | AssertionError: Una reserva pasada o cancelada no recibe evidencias |
| `tests/booking_balance/test_d5.py::test_t7_second_evidence_ack_has_own_context_and_pending_handoff_proof` | AssertionError: La segunda evidencia vinculada requiere exactamente un acuse |
| `tests/booking_balance/test_d5.py::test_t8_taken_after_enqueue_suppresses_second_ack_before_meta` | AssertionError: Falta el acuse encolado que debe revocarse al tomar el caso |
| `tests/booking_balance/test_d5.py::test_t10_second_image_redelivery_has_single_authorized_ack` | AssertionError: El reenvío de la segunda imagen no omite ni duplica el acuse |
| `tests/booking_balance/test_d5.py::test_d5_partial_with_another_pending_evidence_preserves_review_and_open_handoff` | AssertionError: assert None == UUID('b94e87c9-f704-497b-9435-b9ba92c1fbed') |
| `tests/booking_balance/test_d5.py::test_d5_rejected_linked_evidence_notifies_and_resolves_last_payment_handoff[PAYMENT_PENDING]` | AssertionError: assert ('PENDING' == 'RESOLVED' |
| `tests/booking_balance/test_d5.py::test_d5_rejected_linked_evidence_notifies_and_resolves_last_payment_handoff[PAYMENT_REVIEW]` | AssertionError: assert None == UUID('afa642d3-db49-4a10-8489-52677bb51166') |
| `tests/booking_balance/test_d5.py::test_d5_rejected_linked_evidence_notifies_and_resolves_last_payment_handoff[RESERVED]` | AssertionError: assert None == UUID('1f96294c-c4d4-469b-8472-8c781ddf3d36') |

Playwright R7: esperaba «Saldo pendiente» en una fila RESERVED con saldo; falta
la insignia. F1/F5: placeholder esperado «+57 300 123 4567», actual «+573000000123».

## Reproducción

Con TEST_DATABASE_URL local explícito y QUALITY_STAGE=suite:

```sh
pytest tests/payment_prereview/test_d6_no_http_in_tx.py tests/booking_balance \
  tests/staff_notifications/test_f1_phone.py tests/staff_notifications/test_f2_reopen.py \
  tests/booking_conversation/test_f3_clock.py tests/payment_settlement/test_f4_notification.py \
  tests/payment_settlement/test_booking_template_alignment.py -q
npm --prefix tests/frontend test -- test_booking_balance.spec.mjs
```
