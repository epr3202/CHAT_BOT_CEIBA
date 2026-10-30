# A — Auditoría de …8945 sin respuesta

2026-10-30, base `origin/main d0b8736d368087f90cf65229b8feffac0e419bfc`. Auditoría terminada antes de modificar código para B. No se extrajeron cuerpos, nombres, teléfonos completos ni secretos. Producción se mantuvo sin escrituras.

## A1. Histórico completo de entrada

PostgreSQL se consultó sin límite temporal mediante el wrapper habitual: `PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000"`, `psql -X -v ON_ERROR_STOP=1 -P pager=off`, bloques `BEGIN READ ONLY … ROLLBACK`. Ambos ajustes read-only devolvieron `on`. Snapshot: **2026-10-30 16:24:41.275655 UTC**.

Se buscó el sufijo en el teléfono normalizado de customer/recipient, contenido JSON de mensajes y payload crudo de webhook, recipient_id/payload de estados del proveedor, resultados de inbox y transcripciones. Las relaciones de inbox/transcripción se comprobaron además por cliente → mensaje. La búsqueda de payload identifica números de al menos siete dígitos terminados en 8945 sin devolver su valor.

| Tabla / ámbito | Coincidencias | Primer registro | Último registro |
|---|---:|---|---|
| customer | 0 | No existe | No existe |
| message, cualquier dirección/tipo | 0 | No existe | No existe |
| webhook_event.payload, histórico completo | 0 | No existe | No existe |
| inbox_job | 0 | No existe | No existe |
| message_provider_status | 0 | No existe | No existe |
| message_transcription | 0 | No existe | No existe |
| audit_event, referencias de teléfono en antes/después | 0 | No existe | No existe |
| notification_recipient | 0 | No existe | No existe |

No hay primer/último registro atribuible a …8945. Una consulta exploratoria abortó por referir `customer.updated_at`, columna inexistente; se corrigió a `created_at` y se repitió dentro de otra transacción read-only. No hubo escritura.

## A2. Logs de app y worker, solicitud de 72 horas

Se ejecutó `docker compose logs --since 72h --timestamps --no-color app worker`, con filtrado/agregación en la VPS antes de imprimir. No se descargaron líneas crudas.

**Límite de retención:** ambos contenedores fueron creados el **30-oct 15:44:50 UTC**. Sus logs conservados empiezan el **30-oct 15:44:54 UTC** y llegan al momento de consulta, aproximadamente **16:26 UTC**. `--since 72h` no recupera los logs de contenedores anteriores. Primer barrido: 23.714 líneas; segundo barrido posterior: 24.689, por actividad concurrente de los pollers.

| Evento solicitado | Conteo | Horas |
|---|---:|---|
| whatsapp_webhook_ignored | 0 | Ninguna |
| whatsapp_message_ignored | 0 | Ninguna |
| Firma inválida en logs | 0 | Ninguna |
| HTTP 401/403 en /webhook | 0 | Ninguna |
| Peticiones registradas a /webhook, cualquier código | 0 | Ninguna |
| phone_number_id observado en logs distinto del configurado | 0 observaciones de ese campo | Sin comparación posible solo con logs |
| Número …8945 identificable en campos de logs | 0 | Ninguna |

Dos búsquedas numéricas amplias coincidieron con nanosegundos de timestamps, **no con teléfonos**: 16:03:11.461778945Z y 16:23:00.884468945Z. Se validó que no estaban en ningún campo JSON del evento; no se atribuyeron al remitente.

Para cubrir las 72 h aun con rotación, se consultó también la auditoría persistida: **0 `WHATSAPP_WEBHOOK_INVALID_SIGNATURE`**. Esa acción se guarda antes del 403, `app/channel/webhook.py:67`, `app/channel/inbound.py:1306`.

**Destino configurado:** phone_number_id **…9027**, leído sin imprimir el valor completo. Los metadatos de webhook persistidos de las últimas 72 h contienen **456 valores**, todos para **…9027**, **0 discrepancias**; primero **27-oct 18:24:50.028611 UTC**, último **30-oct 03:53:45.413771 UTC**. Se comparó el ID completo en memoria y solo se emitieron igualdad y sufijo enmascarado. Esta consulta también usó PGOPTIONS/BEGIN READ ONLY/ROLLBACK.

## A3. ¿Es asesor activo?

**No:** no existe fila en notification_recipient cuyo teléfono termine en …8945, activa ni inactiva. Por tanto, no hay evidencia de interceptación por asesor para ese número.

La excepción sí existe para asesores activos: `app/notifications/service.py:156` busca el teléfono exacto con `active=true`; una coincidencia retorna `True` incluso ante reentrega (`:166`) y al finalizar (`:214`). `app/channel/inbound.py:887` llama ese interceptor **antes** de crear Customer/Message/Inbox; cuando devuelve True, retorna None en `:895`, sin respuesta del bot. El payload crudo del webhook se habría conservado antes, `app/channel/webhook.py:75`. Aquí tampoco hay rastro en ese payload.

## A4. cloudflared en la VPS

No hay contenedor cloudflared. Sí existen `cloudflared.service` y `cloudflared-update.service`. La lectura inicial como deploy no daba cobertura del journal del sistema; se repitió como root por SSH, solo lectura.

| Unidad | Registros en 72 h | Primero UTC | Último UTC | POST /webhook y código |
|---|---:|---|---|---|
| cloudflared.service | 124 | 27-oct 21:34:27.024461 | 30-oct 16:14:11.121426 | No registrados |
| cloudflared-update.service | Sin entradas | — | — | No registrados |

El servicio estaba **active**. El journal contiene 9 coincidencias de timeout QUIC por inactividad, 7 de fallo de datagram handler, 7 de fallo al servir conexión, 7 reintentos y 7 registros exitosos de conexión al túnel. Los últimos timeout/reintento fueron el **30-oct 07:53:23**, seguidos de conexión registrada a las **07:53:40**. Hay 73 coincidencias de `context canceled` hasta las 16:14:11. Estas categorías se solapan por línea y no son conteos de solicitudes fallidas. No aparecen `origin unreachable` ni `connection refused` en las categorías revisadas.

cloudflared no ofrece aquí un access log de cada POST: **no hay código HTTP atribuible a …8945 ni a unas horas de envío conocidas**. Sus eventos de transporte no permiten atribuir una petición a ese teléfono.

## A5. Conclusión

**No llegó ningún mensaje/webhook identificable de …8945 a la aplicación del bot en la VPS.** No existe rastro histórico en entrada persistida, cliente, inbox ni destinatarios staff. No hay un fallo del pipeline del bot que explique una entrada guardada sin respuesta.

El siguiente frente de diagnóstico es **Meta y el número de destino del envío**: contrastar el destinatario utilizado con el número conectado al phone_number_id …9027 y revisar entrega/suscripción del webhook. No corresponde modificar el bot para responder a una entrada que no tiene registrada.

Límite de la conclusión: los logs de app/worker anteriores al despliegue ya no están conservados y el túnel no registra cada request. Por eso no se puede demostrar, solo con estas fuentes, que jamás alcanzó ningún componente de red de la VPS ni asignar una causa externa exacta. Sí se puede afirmar claramente que **no hay entrada atribuible a …8945 en el bot**, y que no fue silenciada por un asesor activo. Los errores transitorios del túnel se reportan sin atribuirlos a este número.

Consultas y agregadores temporales: `/tmp/ceiba-pr49-a-logs.py`, `/tmp/ceiba-pr49-a-log-details.py`, `/tmp/ceiba-pr49-a-cloud-logs.py`; salidas solo de metadatos en `/tmp`. Sin resets, llamadas a Meta, cambios de configuración ni escrituras productivas.
