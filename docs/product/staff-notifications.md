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

Los parámetros se calculan al encolar: nombre y teléfono, o solo teléfono si no
hay nombre; nombre del plan; inicio presentado en America/Bogota; abono esperado
pendiente en COP. El teléfono colombiano se presenta como `+57 3xx xxx xxxx`.
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
| STAFF_TEMPLATE_LANGUAGE | es | Idioma de las plantillas |
| STAFF_WINDOW_SAFETY_MINUTES | 30 | Entre 0 y 180 |
| STAFF_DEFERRED_MAX_AGE_HOURS | 48 | Entero positivo |
| STAFF_OUTBOX_MAX_ATTEMPTS | 5 | Entero positivo |

El loop usa claims UUID y FOR UPDATE SKIP LOCKED. Recupera SENDING atascados con
el mismo umbral del outbox de clientes. El claim se confirma antes de HTTP y su
liquidación ocurre en otra transacción, condicionada al token. Un error de
programación al insertar el aviso se propaga: no se oculta con un try/except.

## Revisión de comprobantes y nombre de reserva

Para rechazar un comprobante sin reserva, el panel separa Nota interna de Motivo
visible para el cliente. Este último es obligatorio, se normaliza a una línea,
se limita a 200 caracteres y rechaza URLs http/www. El backend lo persiste en
`payment_evidence.customer_reason` y solo lo presenta dentro de RESP-PAYMENT-005
aprobada. Los comprobantes vinculados mantienen RESP-BOOKING-REJECTED-001.

El flujo de reserva pide el nombre antes de confirmar si Customer.full_name es
NULL. Lo extrae de forma determinista, sin repetirlo al cliente, y lo usa en el
título de Calendar y en el primer parámetro del aviso interno.
