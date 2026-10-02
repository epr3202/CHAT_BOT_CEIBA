# Avisos a asesores por WhatsApp

## Modelo y permisos

Los avisos internos se guardan en `staff_outbox`, separados del outbox de clientes.
Se encolan en la misma transacción que vincula un comprobante a una reserva y la
pasa a PAYMENT_REVIEW, o crea una solicitud PAYMENT_PENDING. El envío ocurre
después del commit. Solo se avisa sobre comprobantes vinculados a reservas.

`notification_recipient` conserva nombre, teléfono E.164 único, preferencias de
comprobantes y solicitudes, estado activo y última entrada de WhatsApp. Solo ADMIN
puede administrar destinatarios, consultar avisos o encolar una prueba; AGENT
recibe 403. Se desactiva un destinatario mediante PATCH, sin DELETE. Las ediciones
sin cambios no generan auditoría; las demás auditan únicamente las diferencias.

Cada aviso tiene cuatro parámetros saneados y una identidad única por
destinatario, tipo de evento, entidad y fuente. Reentregas no duplican avisos ni
auditorías. `staff_outbox` es mutable; su historia se registra en `audit_event`.
Los estados son PENDING, SENDING, SENT, DELIVERED, READ, FAILED, DEFERRED y EXPIRED.
La lista del panel muestra el teléfono enmascarado y omite los parámetros.

## Textos y plantillas Meta

La fuente de verdad compartida por texto y plantilla es
`app/notifications/staff_texts.py`. Estos mensajes son internos, no respuestas
al cliente, por lo que no usan KnowledgeEntry.

EVIDENCE_RECEIVED y TEST:

> Nuevo comprobante de pago de {1} para {2} el {3}. Abono esperado: {4}. Revísalo en el panel para confirmarlo.

PAYMENT_PENDING_CREATED:

> Nueva solicitud de reserva de {1}: {2} el {3}. Queda pendiente del abono de {4}; te avisaremos cuando llegue el comprobante.

BALANCE_OVERDUE, aprobado por Leandro el 2026-10-02:

> Saldo vencido: {1} tiene {2} sin pagar de la reserva de {3} el {4}. Según la política, la reserva no se realiza sin el pago completo. Revísala en el panel.

Este aviso usa identidad, saldo total pendiente, plan e inicio presentado en Bogotá,
en ese orden. Se dirige a destinatarios activos con `notify_on_evidence`. Usa la
plantilla Meta `aviso_saldo_vencido`, idioma `es`, configurada mediante
`STAFF_TEMPLATE_OVERDUE_NAME`. El canal TEXT, el enlace al panel, la ventana,
DEFERRED y la reapertura siguen las reglas de B3. Se deduplica por destinatario,
evento y reserva. El aviso informa al asesor; no cancela ni libera la reserva.

Los parámetros se calculan al encolar: nombre y teléfono, o solo teléfono si no
hay nombre; nombre del plan; inicio presentado en America/Bogota; abono esperado
pendiente en COP. El teléfono colombiano se presenta como `+57 3xx xxx xxxx`.
Cuando el comprobante corresponde al saldo de una reserva RESERVED, el parámetro
4 es el saldo total pendiente, en lugar del anticipo faltante.
Cada parámetro reemplaza saltos y tabuladores por espacios, colapsa espacios,
quita espacios exteriores y se recorta a 120 caracteres; vacío se convierte en
`-`. TEST utiliza `Prueba del panel`, `Plan de prueba`, fecha y hora actual de
Bogotá y `$0`.

TEXT agrega una nueva línea literal:

```text
Panel: https://admin.ceibaclubhouse.com
```

Las plantillas a registrar y aprobar en Meta son `aviso_comprobante_reserva` y
`aviso_solicitud_reserva`, idioma `es`, con los cuerpos literales anteriores y
cuatro parámetros de texto en ese orden. Incluyen un botón de URL estática
`https://admin.ceibaclubhouse.com`; el POST no envía componentes para ese botón.
Este PR no registra plantillas ni modifica producción.

## Ventana, reintentos y operación interina

La ventana útil comienza con un mensaje entrante del asesor y termina 24 horas
después, menos el margen de seguridad configurado (30 minutos por defecto).
Dentro se usa TEXT; fuera se usa TEMPLATE si su nombre está configurado. Sin
plantilla disponible se difiere sin HTTP. Un fallo Meta 131047 de TEXT fuerza
TEMPLATE en el siguiente intento; sin plantilla vuelve a DEFERRED. Los estados
DELIVERED y READ avanzan sin retroceder. Errores permanentes terminan en FAILED;
los transitorios usan backoff y un máximo de cinco intentos por defecto.

Un mensaje de un destinatario activo no crea cliente, conversación, mensaje de
cliente ni trabajo de inbox, y el bot no responde. La fecha del proveedor debe
avanzar para actualizar la ventana y auditar; una reentrega no produce efectos.
La misma transacción reencola sus DEFERRED con antigüedad menor de 48 horas. Los
más antiguos vencen en el barrido del worker. Un destinatario desactivado se
procesa como cliente normal al escribir y sus avisos pendientes vencen sin envío.

**Un número de asesor activo no puede usarse como número de prueba de cliente.**
El formulario del panel muestra esta advertencia.

Mientras Meta aprueba las plantillas, dejar sus nombres vacíos y pedir al asesor
que escriba al WhatsApp del negocio permite enviar dentro de la ventana útil.
Activar el flag solo después de aplicar la migración y configurar destinatarios.
El botón Enviar prueba respeta el flag: apagado devuelve 409 «Avisos desactivados».

| Variable | Default | Regla |
| --- | --- | --- |
| STAFF_NOTIFICATIONS_ENABLED | false | No encola ni envía al estar apagado; administración disponible |
| STAFF_TEMPLATE_EVIDENCE_NAME | vacío | EVIDENCE_RECEIVED y TEST; usar aviso_comprobante_reserva tras aprobación |
| STAFF_TEMPLATE_PENDING_NAME | vacío | PAYMENT_PENDING_CREATED; usar aviso_solicitud_reserva tras aprobación |
| STAFF_TEMPLATE_OVERDUE_NAME | vacío | BALANCE_OVERDUE; usar aviso_saldo_vencido tras aprobación |
| STAFF_TEMPLATE_LANGUAGE | es | Idioma de las plantillas |
| STAFF_WINDOW_SAFETY_MINUTES | 30 | Entre 0 y 180 |
| STAFF_DEFERRED_MAX_AGE_HOURS | 48 | Entero positivo |
| STAFF_OUTBOX_MAX_ATTEMPTS | 5 | Entero positivo |

El loop usa claims UUID y FOR UPDATE SKIP LOCKED. Recupera SENDING atascados con
el mismo umbral del outbox de clientes. El claim se confirma antes de HTTP y su
liquidación ocurre en otra transacción, condicionada al token. Un error de
programación al insertar el aviso se propaga: no se oculta con un try/except.

## B4 — recordatorios programados de saldo al cliente

`customer_notification` es una cola separada. Un recordatorio no tiene mensaje
entrante de origen y debe poder enviarse con la conversación cerrada. No usa la
admisión del outbox conversacional ni la ventana de 24 horas: siempre sale como
plantilla Meta aprobada. El claim con SKIP LOCKED, recuperación de leases,
settlement condicionado al token y backoff se comparten con staff_outbox mediante
`app/notifications/queue.py`; los status del proveedor comparten el mismo avance
monotónico y registran `message_provider_status.message_id=NULL`. Los callbacks
duplicados no repiten cambios ni auditoría. Los errores permanentes y transitorios
son los mismos de B3; una plantilla inexistente (132001) termina en FAILED.

La plantilla `recordatorio_saldo_reserva`, idioma `es`, fue aprobada por Leandro
el 2026-10-02 con este cuerpo literal:

> Hola, {{1}}. Te recordamos que tu reserva de {{2}} es el {{3}}. Para realizarla, el saldo de {{4}} debe estar pagado a más tardar el {{5}}. Puedes transferir a Bancolombia, cuenta de ahorros No. 756-748987-62, a nombre de Emerson Pulgarin Restrepo, y enviarnos aquí el comprobante.

Sus cinco parámetros se calculan al encolar y pasan por `sanitize_param`: primer
nombre de Customer.full_name o `cliente` cuando no existe; nombre del plan;
`present_start(starts_at)`; saldo total en COP; `present_start(balance_due_at)`.
El primer nombre y demás variables se insertan una sola vez dentro de la plantilla
aprobada. El renderer no convierte texto del cliente en una respuesta libre.
Si cambian los datos bancarios, hay que modificar y volver a aprobar
`recordatorio_saldo_reserva` antes de usar la nueva versión.

El programador se ejecuta cada cinco minutos con reloj UTC explícito y reglas
horarias de America/Bogota. Evalúa únicamente reservas RESERVED futuras con saldo.
EARLY corresponde al día del evento menos tres días; DUE, al día del vencimiento.
Ambos se programan a las 10:00 Bogotá y exigen que la reserva ya estuviera RESERVED
antes de esa hora y que aún no haya vencido el saldo. La fecha de confirmación se
lee de RESERVATION_STATUS_CHANGED; para históricos creados directamente RESERVED
sin ese evento, se usa created_at. No se usa updated_at como fecha de confirmación.
Una hora pasada antes de confirmar genera BALANCE_REMINDER_SKIPPED_LATE una sola
vez por reserva/tipo, sin enviar el recordatorio omitido. Si las 10:00 del día DUE
ya son posteriores al vencimiento, no se envía: prevalece `now < balance_due_at`.

| Variable | Default | Regla |
| --- | --- | --- |
| BALANCE_REMINDERS_ENABLED | false | Desactiva programación y envío al cliente |
| BOOKING_REMINDER_DAYS_BEFORE | 3 | Entero mayor o igual a uno |
| BOOKING_REMINDER_TIME | 10:00 | HH:MM válido, hora de Bogotá |
| CUSTOMER_TEMPLATE_BALANCE_REMINDER_NAME | vacío | Usar recordatorio_saldo_reserva tras aprobación |

Sin nombre de plantilla configurado no se encola y se audita
BALANCE_REMINDER_NO_TEMPLATE una sola vez por reserva/tipo. UNIQUE(reservation_id,
kind) impide duplicados. Si el cliente paga todo antes de programar, no se genera
aviso; si paga cuando ya está encolado, el claim lo deja EXPIRED sin HTTP. También
vence sin enviar si la reserva fue cancelada o el evento ya pasó. El flag de
recordatorios no sustituye STAFF_NOTIFICATIONS_ENABLED para avisos internos.

Cuando `now >= balance_due_at`, el sistema marca balance_overdue_at una sola vez,
audita RESERVATION_BALANCE_OVERDUE y encola BALANCE_OVERDUE. La reserva sigue RESERVED
y conserva su franja; la decisión de cancelación pertenece al asesor. El pago
completo borra balance_due_at y balance_overdue_at.

## Teléfonos de destinatarios y reapertura

La administración y el webhook comparten la normalización: diez dígitos sin
prefijo se convierten a +57; números con + conservan su prefijo y se eliminan
espacios y separadores. Después se valida E.164 y, para +57, exactamente diez
dígitos nacionales. Los duplicados se detectan después de normalizar. El panel
muestra el número persistido. Si ese número tiene conversaciones de cliente,
POST/PATCH incluye la advertencia y el panel la muestra sin bloquear:

> Este número tiene conversaciones como cliente. Mientras esté activo como asesor, el bot no le responderá.

## Revisión de comprobantes y nombre de reserva

Para rechazar un comprobante sin reserva, el panel separa Nota interna de Motivo
visible para el cliente. Este último es obligatorio, se normaliza a una línea,
se limita a 200 caracteres y rechaza URLs http/www. El backend lo persiste en
`payment_evidence.customer_reason` y solo lo presenta dentro de RESP-PAYMENT-005
aprobada. Los comprobantes vinculados mantienen RESP-BOOKING-REJECTED-001.

El flujo de reserva pide el nombre antes de confirmar si Customer.full_name es
NULL. Lo extrae de forma determinista, sin repetirlo al cliente, y lo usa en el
título de Calendar y en el primer parámetro del aviso interno.
