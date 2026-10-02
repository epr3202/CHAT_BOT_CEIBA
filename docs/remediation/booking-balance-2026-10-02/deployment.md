# Despliegue posterior a revisión y merge autorizado

Este PR no aplica cambios en producción ni autoriza merge. La autorización de
merge debe venir literalmente de Emerson en un prompt posterior. Base verificada:
`c5812f5267e9c99208282e2a3baed66f9fb02cb7`.

## Settings nuevos

| Variable | Default | Valor previsto tras comprobar las plantillas Meta |
| --- | --- | --- |
| BALANCE_REMINDERS_ENABLED | false | true solo después de verificar configuración y destinatarios |
| BOOKING_REMINDER_DAYS_BEFORE | 3 | 3 |
| BOOKING_REMINDER_TIME | 10:00 | 10:00 America/Bogota |
| CUSTOMER_TEMPLATE_BALANCE_REMINDER_NAME | vacío | recordatorio_saldo_reserva |
| STAFF_TEMPLATE_OVERDUE_NAME | vacío | aviso_saldo_vencido |

La pre-revisión conserva PAYMENT_REVIEW_AI_ENABLED y usa el lease timeout existente
OUTBOX_SENDING_TIMEOUT_SECONDS. Los demás flags y las plantillas B3 mantienen su
configuración actual; no se requiere cambiar BOOKING_LATEST_START=21:00 ni
BOOKING_HOURS_END=24:00.

## Secuencia para el operador autorizado

1. Respaldar la base y coordinar el cambio de aplicación y worker. Aplicar
   `alembic upgrade head` hasta `20261002_0035`; no hay backfill ni edición de
   historiales append-only. Reiniciar todos los workers y la aplicación con el
   mismo código para que ninguna instancia siga ejecutando la pre-revisión antigua.
2. Ejecutar el seed idempotente `python scripts/load_knowledge.py` para incorporar
   los dos códigos BALANCE nuevos. El seed conserva las filas existentes por
   code/version; no sincroniza ni reemplaza las versiones aprobadas en producción.
   Las versiones productivas v2/v3 documentadas no son una orden de sobrescritura.
3. Verificar en Meta los nombres, idioma `es`, cuerpos literales y cinco parámetros
   de recordatorio_saldo_reserva, así como cuatro de aviso_saldo_vencido. La
   aprobación comercial de Leandro está documentada; los nombres vacíos impiden
   enviar una plantilla que no esté configurada. Si cambian los datos bancarios,
   obtener la nueva aprobación de recordatorio_saldo_reserva antes de usarla.
4. Revisar los destinatarios activos con notify_on_evidence y sus teléfonos
   normalizados. Un número que también es cliente recibe la advertencia del panel;
   mientras sea asesor activo sus entradas se interceptan y el bot no le responde.
5. Configurar los nombres y habilitar BALANCE_REMINDERS_ENABLED. Observar el primer
   ciclo de cinco minutos: recordatorios idempotentes, omisiones tardías auditadas,
   y marcado/aviso de saldo vencido sin cancelación automática. Comprobar en el
   panel pagado, saldo, vencimiento, recordatorios e insignias.
6. Para detener recordatorios, desactivar el flag y reiniciar el worker. La
   cancelación de una reserva sigue siendo una acción humana del panel.

## Límite de rollback

La verificación local hace `head → -1 → head` en una base exclusiva de pruebas.
El downgrade restaura el CHECK anterior de staff_outbox y falla si existen avisos
BALANCE_OVERDUE, preservándolos. No borra historia para forzar un rollback. La cola
customer_notification sí es mutable y se elimina al bajar esta revisión; cualquier
rollback real requiere respaldo y decisión operativa humana. No se ha ejecutado
ningún downgrade contra producción.

Los tipos de recordatorio tienen UNIQUE(reservation_id, kind). Una reprogramación
no repite un tipo ya registrado; sí limpia una marca vencida si el nuevo plazo es
futuro y conserva sus valores anterior/nuevo en la auditoría.
