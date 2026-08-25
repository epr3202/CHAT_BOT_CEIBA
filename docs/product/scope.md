# Alcance del producto

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/product/scope.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Documento relacionado:** `/docs/product/vision.md`
**Canal inicial:** WhatsApp
**Zona horaria oficial:** `America/Bogota`

---

# 1. Propósito del documento

Este documento define el alcance funcional, técnico y operativo del MVP del Asistente Conversacional de La Ceiba Club House.

Su objetivo es establecer con precisión:

* qué debe hacer el sistema;
* qué no debe hacer;
* cuáles son sus módulos;
* dónde comienza y termina cada responsabilidad;
* qué operaciones requieren intervención humana;
* qué componentes deben quedar preparados para futuras fases;
* qué elementos no deben bloquear el lanzamiento;
* cuáles son los criterios de aceptación de cada módulo.

Este documento constituye el límite oficial del MVP.

Cualquier funcionalidad que no esté expresamente incluida deberá considerarse fuera del alcance hasta que sea aprobada mediante control de cambios.

---

# 2. Declaración de alcance

El MVP permitirá que La Ceiba Club House atienda automáticamente conversaciones iniciales por WhatsApp, responda preguntas frecuentes, capture información comercial, registre leads, reciba solicitudes de cotización, gestione visitas y transfiera conversaciones a asesores humanos.

La primera versión estará orientada a:

```text
Atención informativa
+
captura comercial
+
agenda de visitas
+
solicitudes de cotización humana
+
escalamiento a asesores
+
trazabilidad operativa
```

El MVP no generará cotizaciones personalizadas automáticamente.

Las propuestas serán preparadas o aprobadas por asesores humanos.

La solución deberá quedar estructurada para incorporar posteriormente un motor determinista de cotizaciones sin tener que rediseñar:

* conversaciones;
* clientes;
* leads;
* eventos;
* solicitudes;
* servicios;
* cotizaciones;
* versionado;
* agenda;
* auditoría.

---

# 3. Objetivo funcional del MVP

El MVP deberá permitir que un cliente complete uno o varios de estos recorridos:

## Recorrido 1 — Consulta informativa

```text
Mensaje
→ identificación de la pregunta
→ consulta de respuesta aprobada
→ respuesta
→ cierre o continuidad comercial
```

## Recorrido 2 — Solicitud de cotización

```text
Interés comercial
→ captura de datos
→ validación de información mínima
→ confirmación del cliente
→ creación de solicitud
→ asignación a asesor
→ preparación humana de propuesta
```

## Recorrido 3 — Agenda de visita

```text
Solicitud de visita
→ validación de reglas
→ consulta de disponibilidad
→ selección de horario
→ confirmación
→ creación de cita
→ recordatorio
```

## Recorrido 4 — Atención humana

```text
Solicitud o condición de escalamiento
→ generación de resumen
→ entrada en bandeja compartida
→ asignación de asesor
→ pausa del bot
→ atención humana
```

## Recorrido 5 — Información de pago

```text
Cliente informa o envía pago
→ registro de información
→ estado PAYMENT_REVIEW
→ escalamiento
→ validación humana
→ confirmación o rechazo
```

---

# 4. Alcance por canal

## 4.1 Canal incluido

### WhatsApp

El MVP incluirá:

* recepción de mensajes;
* envío de respuestas;
* identificación por número telefónico;
* recepción de eventos del proveedor;
* registro de estados de entrega;
* registro de lectura, cuando el proveedor lo permita;
* manejo de mensajes interactivos básicos;
* asociación de mensajes con conversaciones;
* deduplicación de webhooks;
* almacenamiento del historial.

## 4.2 Tipos de mensajes incluidos

El MVP deberá soportar como mínimo:

* mensajes de texto;
* respuestas a botones;
* selección de opciones interactivas;
* eventos de entrega;
* eventos de lectura;
* imágenes recibidas;
* documentos recibidos;
* comprobantes enviados como archivo.

## 4.3 Tratamiento inicial de multimedia

### Imágenes

El sistema podrá:

* recibirlas;
* almacenarlas;
* asociarlas a una conversación;
* asociarlas a una solicitud;
* informar al asesor.

No realizará análisis avanzado de imágenes durante el MVP.

### Documentos

El sistema podrá:

* recibirlos;
* almacenarlos;
* registrar nombre y tipo;
* permitir su consulta por el asesor.

No interpretará automáticamente contratos o documentos legales.

### Audios

Durante el alcance inicial:

* podrán registrarse como mensajes;
* no será obligatorio transcribirlos;
* el bot podrá pedir al cliente que escriba la información;
* podrán escalarse a un asesor.

La transcripción automática de audios queda fuera del MVP.

### Videos

Se podrán almacenar como referencia, pero no analizar automáticamente.

## 4.4 Canal preparado, pero no implementado

### Instagram Direct

El dominio deberá quedar preparado para Instagram, pero el canal no será implementado en el MVP.

La preparación implica:

* interfaz común de canales;
* identificadores normalizados;
* conservación del origen;
* lógica conversacional independiente de WhatsApp;
* clientes unificados por canal cuando sea posible.

---

# 5. Alcance del módulo de identidad y clientes

## 5.1 Incluido

El sistema deberá:

* identificar al cliente por número de WhatsApp;
* crear un perfil provisional;
* actualizar el nombre;
* registrar correo cuando sea necesario;
* registrar ciudad de forma opcional;
* conservar preferencias de contacto;
* detectar perfiles duplicados;
* relacionar un cliente con varios eventos;
* conservar historial de actividad;
* registrar número de inasistencias.

## 5.2 Reglas

* El teléfono será el identificador externo inicial.
* Un cliente podrá tener varios leads.
* Un lead representará una oportunidad o evento específico.
* El nombre no se solicitará nuevamente si ya está confirmado.
* Los datos inferidos deberán distinguirse de los confirmados.
* Las notas internas no podrán mostrarse al cliente.

## 5.3 Fuera del alcance

* verificación de identidad;
* validación mediante documento;
* consulta a bases externas;
* reconocimiento biométrico;
* perfiles familiares complejos;
* unificación avanzada de identidades entre múltiples canales.

---

# 6. Alcance del módulo de conversaciones

## 6.1 Incluido

El módulo deberá:

* crear conversaciones;
* recuperar conversaciones abiertas;
* guardar mensajes entrantes y salientes;
* mantener estado conversacional;
* conservar la última intención;
* conservar acciones pendientes;
* registrar campos faltantes;
* evitar preguntas repetidas;
* generar resúmenes;
* cerrar conversaciones;
* reabrir o continuar conversaciones;
* relacionar una conversación con un lead.

## 6.2 Estados mínimos

```text
NEW
BOT_ACTIVE
ANSWERING_INFORMATION
COLLECTING_EVENT_DATA
QUOTE_REQUEST_READY
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED
WAITING_FOR_HUMAN
HUMAN_ACTIVE
RETURNED_TO_BOT
RESOLVED
CLOSED
```

## 6.3 Reglas

* Una conversación no equivale a un lead.
* Una conversación podrá tratar varios temas.
* El sistema deberá conservar la acción pendiente cuando el cliente cambie temporalmente de tema.
* El bot deberá interpretar respuestas breves según la última pregunta.
* El historial completo será la fuente primaria.
* Los resúmenes servirán como apoyo, no como sustitución del historial.

## 6.4 Fuera del alcance

* conversaciones grupales;
* llamadas de voz;
* videollamadas;
* traducción simultánea completa;
* enrutamiento internacional complejo;
* análisis emocional avanzado.

---

# 7. Alcance de la atención informativa

## 7.1 Información incluida

El bot podrá responder sobre:

* identidad de La Ceiba;
* ubicación;
* enlace de Google Maps;
* parqueadero;
* espacios;
* capacidades;
* tipos de eventos;
* piscina;
* mascotas;
* alimentos externos;
* bebidas externas;
* licor;
* descorche;
* proveedores externos;
* servicios generales;
* alojamiento;
* cafetería;
* horarios de eventos;
* visitas;
* proceso para cotizar;
* proceso para separar una fecha;
* medios de pago;
* tiempos de respuesta.

## 7.2 Fuente de información

Las respuestas deberán provenir de una base de conocimiento con:

* preguntas equivalentes;
* respuesta aprobada;
* versión;
* fecha de vigencia;
* responsable de aprobación;
* estado activo o inactivo.

## 7.3 Restricción

Solo podrán enviarse automáticamente respuestas en estado:

```text
APPROVED
```

## 7.4 Información sensible o condicionada

El bot deberá utilizar respuestas especialmente controladas para:

* precios;
* devoluciones;
* cancelaciones;
* pagos;
* reservas;
* aforo;
* alojamiento;
* extensión de horario;
* disponibilidad de proveedores;
* servicios especiales.

## 7.5 Fuera del alcance

* respuestas libres sobre condiciones no documentadas;
* asesoría jurídica;
* interpretación contractual;
* promesas comerciales no aprobadas;
* recomendaciones de proveedores externos no autorizados.

---

# 8. Alcance del módulo de leads

## 8.1 Incluido

El sistema deberá:

* crear leads;
* relacionarlos con clientes;
* registrar canal de origen;
* registrar tipo de evento;
* registrar fecha;
* registrar invitados;
* registrar presupuesto;
* registrar servicios;
* asignar asesor;
* registrar prioridad;
* registrar siguiente acción;
* cambiar estado comercial;
* detectar información faltante;
* cerrar como ganado o perdido.

## 8.2 Estados mínimos

```text
NEW
QUALIFYING
QUALIFIED
QUOTE_REQUESTED
QUOTE_IN_PROGRESS
QUOTE_SENT
VISIT_SCHEDULED
FOLLOW_UP
WON
LOST
ARCHIVED
```

## 8.3 Datos mínimos para crear un lead

Se podrá crear un lead cuando exista:

* número telefónico;
* canal;
* intención comercial.

## 8.4 Datos mínimos para calificarlo

* tipo de evento;
* fecha o periodo;
* cantidad aproximada de invitados.

## 8.5 Presupuesto

El presupuesto:

* será preferible;
* no será obligatorio;
* podrá guardarse como valor o rango;
* tendrá como referencia comercial $4.000.000 COP;
* no producirá rechazo automático.

## 8.6 Fuera del alcance

* scoring predictivo;
* automatización completa del embudo;
* asignación mediante inteligencia comercial avanzada;
* campañas de nutrición;
* importación masiva de bases de datos;
* integración completa con CRM externo.

---

# 9. Alcance del módulo de eventos

## 9.1 Incluido

El sistema almacenará:

* tipo de evento;
* fecha exacta;
* mes aproximado;
* flexibilidad;
* alternativas;
* cantidad de adultos;
* cantidad de niños;
* cantidad de bebés;
* total de invitados;
* horario aproximado;
* duración;
* espacio de interés;
* uso esperado de piscina;
* presencia de mascotas;
* requerimientos de accesibilidad;
* observaciones;
* servicios deseados.

## 9.2 Tipos iniciales

```text
WEDDING
CIVIL_WEDDING
PROPOSAL
BIRTHDAY
GRADUATION
ANNIVERSARY
ROMANTIC_DINNER
CORPORATE_EVENT
FAMILY_EVENT
BAPTISM
FIRST_COMMUNION
BABY_SHOWER
WORKSHOP
POOL_DAY
PRIVATE_DINNER
GENDER_REVEAL
OTHER
```

## 9.3 Reglas

* Si el cliente proporciona un mes, no se inventará el día.
* Las fechas relativas deberán convertirse y confirmarse.
* Los invitados expresados como rango no se almacenarán como una cifra exacta confirmada.
* Los cambios conservarán auditoría.
* Eventos con más de 60 invitados se marcarán para revisión.
* Los niños deberán formar parte de la capacidad total.

## 9.4 Fuera del alcance

* planos de montaje automáticos;
* simulación de distribución;
* gestión de mesas e invitados;
* lista nominal de invitados;
* asignación automática de puestos;
* diseño de decoración.

---

# 10. Alcance del módulo de servicios

## 10.1 Servicios propios o gestionados

El sistema podrá registrar interés en:

* espacio;
* mobiliario;
* montaje;
* vajilla;
* cubiertos;
* cristalería;
* atención de meseros;
* gastronomía;
* bebidas;
* coctelería;
* piscina;
* cafetería;
* apoyo audiovisual;
* coordinación comercial.

## 10.2 Servicios sujetos a confirmación

* decoración especializada;
* floristería;
* fotografía;
* video;
* DJ;
* violinista;
* saxofonista;
* música en vivo;
* maquillaje;
* peinado;
* tortas;
* postres;
* letras gigantes;
* carrito de shots;
* mobiliario adicional;
* iluminación especial;
* pantallas adicionales;
* alojamiento;
* seguridad;
* entretenimiento infantil.

## 10.3 Estados de servicio

```text
REQUESTED
AVAILABLE
PENDING_CONFIRMATION
UNAVAILABLE
INCLUDED
ADDITIONAL_COST
CLIENT_PROVIDED
```

## 10.4 Restricción

Solicitar un servicio no significa que esté:

* incluido;
* reservado;
* disponible;
* cotizado;
* confirmado.

## 10.5 Fuera del alcance

* contratación automática de proveedores;
* liquidación de proveedores;
* portal de proveedores;
* órdenes de compra;
* control avanzado de inventario;
* disponibilidad automática de artistas externos.

---

# 11. Alcance de solicitudes de cotización

## 11.1 Incluido

El bot podrá:

* detectar intención de cotizar;
* recopilar datos;
* identificar datos faltantes;
* confirmar información;
* crear solicitud;
* asignarla a bandeja;
* calcular fecha límite;
* generar resumen;
* informar al cliente;
* registrar cumplimiento.

## 11.2 Datos mínimos

```text
Nombre
Teléfono
Tipo de evento
Fecha, mes o periodo
Cantidad aproximada de invitados
```

## 11.3 Datos preferibles

```text
Presupuesto
Horario
Espacio
Gastronomía
Bebidas
Decoración
Servicios
Observaciones
Correo
```

## 11.4 Plazo

El sistema comunicará:

**Hasta tres días hábiles.**

## 11.5 Estados

```text
DRAFT
READY
ASSIGNED
IN_PROGRESS
COMPLETED
CANCELLED
EXPIRED
```

## 11.6 Comportamiento esperado

Cuando se complete la información mínima:

1. El bot mostrará resumen.
2. El cliente confirmará.
3. El sistema creará la solicitud.
4. Se enviará a la bandeja.
5. Se notificará el plazo.

## 11.7 Fuera del alcance

* cálculo automático de precio;
* recomendación automática de paquetes;
* descuentos automáticos;
* negociación mediante IA;
* envío automático de propuesta sin revisión;
* aprobación contractual.

---

# 12. Alcance de cotizaciones humanas

## 12.1 Incluido

Aunque el cálculo sea humano, el sistema deberá permitir:

* crear una cotización;
* asociarla a una solicitud;
* registrar versión;
* registrar subtotal;
* registrar impuestos;
* registrar descuento autorizado;
* registrar total;
* registrar vigencia;
* adjuntar documento;
* registrar responsable;
* registrar envío;
* registrar respuesta del cliente.

## 12.2 Estados

```text
DRAFT
PRELIMINARY
REVIEW_REQUIRED
APPROVED
SENT
ACCEPTED
REJECTED
EXPIRED
SUPERSEDED
```

## 12.3 Versionado

Una cotización enviada nunca se sobrescribirá.

Una modificación generará una nueva versión cuando cambien:

* fecha;
* invitados;
* menú;
* servicios;
* precio;
* descuento;
* duración;
* condiciones.

## 12.4 Preparación para la opción A

La estructura deberá permitir en el futuro:

* catálogo de paquetes;
* catálogo de servicios;
* reglas de precio;
* cálculo;
* desglose;
* vigencia automática;
* aprobación;
* generación de documento.

## 12.5 Fuera del alcance del MVP

* motor de precios;
* cálculo por temporada;
* cálculo por día;
* cálculo por invitado;
* promociones;
* descuentos automáticos;
* impuestos automáticos;
* generación autónoma de propuesta.

---

# 13. Alcance del módulo de agenda

## 13.1 Incluido

El sistema podrá:

* consultar fechas;
* consultar horarios;
* excluir festivos;
* excluir bloqueos;
* excluir citas existentes;
* ofrecer opciones;
* crear citas;
* reprogramar;
* cancelar;
* registrar asistencia;
* registrar inasistencia;
* programar recordatorios;
* sincronizar con calendario.

## 13.2 Horarios oficiales

```text
Martes a sábado
8:00 a. m.
9:00 a. m.
10:00 a. m.
11:00 a. m.
```

## 13.3 Duración

```text
45 minutos de visita
15 minutos de margen operativo
```

## 13.4 Reglas

* mínimo tres días de anticipación;
* no mismo día;
* no día siguiente;
* no festivos;
* máximo cuatro por día;
* máximo tres asistentes;
* validación antes de ofrecer;
* nueva validación antes de crear;
* una cita activa por horario;
* zona horaria `America/Bogota`.

## 13.5 Datos obligatorios

* nombre;
* teléfono;
* fecha;
* hora;
* asistentes;
* motivo;
* confirmación final.

## 13.6 Estados

```text
PENDING_CONFIRMATION
CONFIRMED
RESCHEDULED
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

## 13.7 Reprogramación

* no tendrá límite automático;
* conservará historial;
* incrementará contador;
* podrá notificar reincidencia.

## 13.8 Inasistencia

* primera: registro y reprogramación;
* segunda: notificación interna;
* tercera: nueva solicitud escalada.

## 13.9 Fuera del alcance

* agenda de eventos completos;
* asignación de personal del evento;
* calendarios de proveedores;
* reservas de habitaciones;
* planificación de montajes;
* agenda multipropiedad.

---

# 14. Alcance de recordatorios

## 14.1 Incluido

Se enviará un recordatorio:

**Un día antes de la visita.**

## 14.2 Contenido

* nombre;
* fecha;
* hora;
* ubicación;
* enlace de Maps;
* cantidad de asistentes;
* recomendación de puntualidad;
* opción de reprogramar o cancelar.

## 14.3 Reglas

* enviar una sola vez;
* no enviar si está cancelada;
* registrar resultado;
* reprogramar el recordatorio cuando cambie la cita.

## 14.4 Fuera del alcance

* secuencias comerciales complejas;
* múltiples recordatorios;
* recordatorios por correo y SMS;
* campañas automáticas;
* notificaciones push.

---

# 15. Alcance del handoff humano

## 15.1 Incluido

El sistema deberá:

* crear escalamiento;
* clasificar motivo;
* asignar prioridad;
* generar resumen;
* enviar a bandeja común;
* permitir toma manual;
* permitir toma manual desde una conversación sin handoff previo;
* registrar asesor;
* reasignar explícitamente una conversación tomada;
* pausar bot;
* impedir respuestas simultáneas;
* mostrar el hilo de mensajes al asesor;
* actualizar el hilo operativo sin recarga manual;
* permitir devolver al bot;
* cerrar conversación.

## 15.2 Motivos

```text
CUSTOMER_REQUEST
QUOTE_PREPARATION
PRICE_NEGOTIATION
DISCOUNT_REQUEST
PAYMENT_REVIEW
RESERVATION_CONFIRMATION
CANCELLATION
COMPLAINT
LOW_CONFIDENCE
UNSUPPORTED_REQUEST
CAPACITY_REVIEW
SPECIAL_EVENT
SUPPLIER_CONFIRMATION
URGENT_EVENT
SYSTEM_ERROR
REPEATED_NO_SHOW
MANUAL_TAKEOVER
TEMPLATE_UNAVAILABLE
CATALOG_NOT_AVAILABLE
OTHER
```

## 15.3 Prioridades

```text
NORMAL
HIGH
URGENT
CRITICAL
```

## 15.4 Modelo de asignación

```text
Conversación escalada
→ bandeja compartida
→ asesor selecciona “Tomar conversación”
→ asignación exclusiva
→ bot pausado
```

También se admite toma manual operativa desde la bandeja general de conversaciones:

```text
Conversación existente
→ asesor selecciona “Tomar”
→ backend valida estado elegible
→ backend crea Handoff(reason = MANUAL_TAKEOVER)
→ asigna asesor autenticado
→ conversation_status = HUMAN_ACTIVE
→ bot_enabled = false
→ auditoría de toma manual
```

Esta acción no depende de una clasificación previa del bot. Se usa cuando el equipo
humano identifica que debe intervenir en una conversación que aún estaba siendo
atendida por automatización.

Estados elegibles:

```text
BOT_ACTIVE
ANSWERING_INFORMATION
COLLECTING_EVENT_DATA
WAITING_FOR_APPOINTMENT_DATE
WAITING_FOR_APPOINTMENT_SELECTION
APPOINTMENT_PENDING_CONFIRMATION
APPOINTMENT_CONFIRMED
RESOLVED
```

Estados no elegibles:

```text
HUMAN_ACTIVE
CLOSED
WAITING_FOR_HUMAN
```

`WAITING_FOR_HUMAN` debe tomarse mediante el handoff pendiente existente. La toma
directa no debe crear un segundo handoff.

La toma manual deberá preservar la trazabilidad:

* no elimina mensajes existentes;
* no borra el historial del bot;
* no confirma pagos, reservas, citas, precios ni disponibilidad;
* registra `audit_event`;
* deja al bot pausado hasta que un asesor devuelva la conversación;
* no envía ningún mensaje automático al cliente.

## 15.4.1 Persistencia operativa

Los handoffs y conversaciones son persistentes. Reiniciar API, worker, frontend o
túnel público no deberá liberar un caso tomado. Mientras la base de datos se conserve,
el estado operativo queda definido por:

```text
conversation.state = HUMAN_ACTIVE
conversation.bot_enabled = false
handoff.status = TAKEN
handoff.assigned_to = <asesor>
```

Si el cliente escribe durante `HUMAN_ACTIVE`, el sistema guarda el mensaje y lo
muestra en la vista administrativa, pero el bot no responde automáticamente.

## 15.4.2 Vista operativa del chat

La bandeja humana deberá permitir ver el hilo de mensajes de una conversación tomada.
La actualización puede implementarse con polling AJAX mientras no exista un canal de
eventos en tiempo real. El hilo debe distinguir:

* mensajes entrantes del cliente;
* mensajes salientes ya enviados;
* mensajes salientes pendientes o fallidos en outbox.

El resumen determinístico del handoff es contexto operativo, no reemplaza el historial
de mensajes.

## 15.5 Responsable general

**Manager Leandro**

## 15.6 Horario humano

```text
Martes a sábado
8:00 a. m. a 4:00 p. m.
```

## 15.7 Fuera del alcance

* asignación inteligente por carga;
* distribución por especialidad;
* turnos automáticos;
* escalamiento telefónico;
* centro de contacto avanzado;
* supervisión en tiempo real estilo call center.

---

# 16. Alcance de pagos

## 16.1 Incluido

El sistema podrá:

* recibir información de pago;
* recibir comprobante;
* asociarlo a una reserva;
* registrar método;
* marcar revisión;
* notificar al asesor;
* registrar confirmación o rechazo;
* conservar auditoría.

## 16.2 Métodos

```text
Transferencia
Efectivo
Tarjeta
Nequi
Daviplata
Enlace de pago
```

## 16.3 Estados

```text
PAYMENT_PENDING
PAYMENT_REVIEW
PAYMENT_CONFIRMED
PAYMENT_REJECTED
PAYMENT_CANCELLED
```

## 16.4 Autoridad

Solo un asesor podrá cambiar a:

```text
PAYMENT_CONFIRMED
```

## 16.5 Tiempo

La revisión deberá realizarse en máximo:

**1 día.**

## 16.6 Restricciones

El bot no podrá:

* confirmar recepción bancaria;
* validar autenticidad del comprobante;
* guardar tarjetas completas;
* solicitar CVV;
* solicitar PIN;
* solicitar contraseñas;
* emitir recibos oficiales;
* crear devoluciones;
* cambiar la reserva automáticamente.

## 16.7 Fuera del alcance

* pasarela integrada;
* conciliación bancaria automática;
* cobro recurrente;
* emisión de factura;
* devolución automática;
* enlace de pago generado dinámicamente;
* verificación antifraude.

---

# 17. Alcance de reservas

## 17.1 Incluido

El sistema podrá registrar:

* cotización aceptada;
* valor acordado;
* abono esperado;
* porcentaje;
* estado del pago;
* aceptación de condiciones;
* asesor confirmante;
* fecha de reserva.

## 17.2 Regla principal

La fecha queda separada con:

**50 % del valor acordado.**

## 17.3 Condición obligatoria

```text
payment_status = PAYMENT_CONFIRMED
```

Solo después podrá cambiar a:

```text
reservation_status = RESERVED
```

## 17.4 Sin bloqueo previo

No se crearán bloqueos de fecha por:

* conversación;
* visita;
* solicitud;
* cotización;
* intención de compra;
* comprobante sin revisar.

## 17.5 Cancelaciones

### Un mes o más

* decisión de asesor;
* revisión de condiciones;
* sin promesa automática.

### Menos de un mes

* no devolución;
* escalamiento obligatorio;
* excepciones únicamente humanas.

## 17.6 Fuera del alcance

* bloqueo temporal;
* reserva automática;
* contratos electrónicos;
* devolución automática;
* cambios de fecha automáticos;
* penalidades calculadas;
* gestión jurídica.

---

# 18. Alcance del panel administrativo mínimo

## 18.1 Objetivo

Permitir la operación diaria sin acceder directamente a la base de datos.

## 18.2 Pantallas incluidas

### Conversaciones

* cliente;
* estado;
* canal;
* último mensaje;
* asesor;
* fecha;
* prioridad.

### Detalle

* historial;
* datos del cliente;
* lead;
* evento;
* cita;
* cotización;
* archivos;
* resumen;
* acciones.

### Leads

* datos;
* estado;
* origen;
* responsable;
* evento;
* siguiente acción.

### Visitas

* fecha;
* hora;
* cliente;
* asistentes;
* estado;
* responsable;
* acciones.

### Solicitudes de cotización

* cliente;
* datos;
* campos faltantes;
* plazo;
* asesor;
* estado.

### Cotizaciones

* versión;
* valor;
* vigencia;
* documento;
* estado;
* responsable.

### Base de conocimiento

* categoría;
* pregunta;
* respuesta;
* versión;
* estado;
* aprobación.

### Catálogos por categoría

* vista de los 17 tipos de evento del catálogo oficial;
* PDFs mapeados a cada tipo, conservando la relación muchos a muchos: una categoría
  puede tener varios PDFs y un mismo asset puede estar mapeado a varias categorías;
* carga directa de un PDF desde el panel y mapeo a la categoría seleccionada en una
  sola operación de negocio;
* activación y desactivación de assets sin borrar su historial;
* indicador visible de cobertura por categoría, donde existe cobertura únicamente
  si hay al menos un PDF activo mapeado;
* señalización de las categorías sin cobertura con la nota de que sus solicitudes
  pasan a atención manual.

La carga y administración exigen sesión y rol administrativo. Los nombres de archivo
recibidos no se usan como rutas de almacenamiento y nunca pueden permitir traversal.

### Configuración básica

* horarios;
* días bloqueados;
* festivos;
* asesores;
* respuestas aprobadas;
* parámetros operativos.

## 18.3 Roles

```text
ADMIN
MANAGER
ADVISOR
CONTENT_OPERATOR
READ_ONLY
```

## 18.4 Fuera del alcance

* CRM completo;
* tableros financieros avanzados;
* diseño visual complejo;
* constructor de automatizaciones;
* aplicación móvil;
* gestión de nómina;
* inventario detallado;
* contabilidad.

---

# 19. Alcance de inteligencia artificial

## 19.1 Usos incluidos

* clasificación de intención;
* extracción de entidades;
* redacción;
* resumen;
* evaluación de confianza.

## 19.2 Usos separados

No se utilizará una única llamada para todo.

Funciones:

```text
INTENT_CLASSIFICATION
ENTITY_EXTRACTION
RESPONSE_DRAFTING
CONVERSATION_SUMMARY
CONFIDENCE_EVALUATION
```

## 19.3 Salida estructurada

La IA deberá devolver datos validados, por ejemplo:

```json
{
  "intent": "SCHEDULE_VISIT",
  "confidence": 0.92,
  "entities": {
    "preferred_date": "2026-08-15"
  },
  "requested_action": "CHECK_AVAILABILITY",
  "missing_fields": [],
  "needs_human": false
}
```

## 19.4 Validaciones

* JSON válido;
* intención permitida;
* acción permitida;
* tipos correctos;
* fechas válidas;
* confianza válida;
* campos conocidos;
* ausencia de precios inventados;
* ausencia de acciones críticas no autorizadas.

## 19.5 Prohibiciones

La IA no podrá:

* calcular cotizaciones;
* confirmar disponibilidad;
* crear cita directamente;
* confirmar pago;
* reservar fecha;
* decidir devolución;
* otorgar descuento;
* modificar reglas;
* confirmar proveedor;
* ejecutar cambios sin backend.

## 19.6 Fallback

Ante indisponibilidad:

* guardar mensaje;
* usar FAQ determinista;
* usar menú básico;
* registrar error;
* escalar operaciones críticas;
* evitar respuestas inventadas.

---

# 20. Alcance de persistencia

## 20.1 Entidades incluidas

```text
Customer
Lead
Event
Conversation
Message
QuoteRequest
Quote
QuoteItem
Appointment
AppointmentChange
Reservation
Payment
PaymentEvidence
Handoff
KnowledgeEntry
AIExecution
AuditEvent
User
Role
Configuration
```

## 20.2 Reglas de integridad

* mensaje externo único;
* cotización versionada;
* mensajes no sobrescritos;
* reservas solo con pago confirmado;
* citas sin duplicidad;
* auditoría en cambios críticos;
* datos sensibles restringidos.

## 20.3 Retención inicial

### Conversaciones informativas

12 meses, configurable.

### Leads y cotizaciones

5 años, sujeto a revisión legal.

### Reservas y pagos

Según obligaciones legales y contractuales.

### Evidencias de pago

Los archivos de evidencia se conservan inicialmente durante 365 días, configurable con
`PAYMENT_EVIDENCE_RETENTION_DAYS`. W2-b registra la política, pero no ejecuta purga
automática: eliminar archivos y conservar la trazabilidad correspondiente requiere un
flujo posterior revisado.

### IA

Conservar información técnica minimizada.

---

# 21. Alcance de seguridad y privacidad

## 21.1 Incluido

* secretos fuera del código;
* acceso por roles;
* auditoría;
* cifrado en tránsito;
* cifrado o protección en reposo;
* control de archivos;
* minimización de datos;
* límites de tamaño;
* validación de webhook;
* rate limiting;
* respaldo;
* política de eliminación.

## 21.2 Datos prohibidos

El bot no solicitará:

* contraseñas;
* PIN;
* CVV;
* códigos de autenticación;
* tarjeta completa;
* claves bancarias;
* diagnósticos médicos completos;
* información política;
* religión;
* origen étnico;
* información íntima innecesaria;
* documentos sin finalidad aprobada.

## 21.3 Datos permitidos por necesidad

* alergias;
* requerimientos alimentarios;
* accesibilidad;
* edades aproximadas de niños;
* necesidades de seguridad.

## 21.4 Fuera del alcance

* certificaciones de seguridad avanzadas;
* gestión de identidades corporativa;
* autenticación biométrica;
* cumplimiento internacional multijurisdiccional.

---

# 22. Alcance de auditoría

## 22.1 Acciones auditadas

* cambio de fecha;
* cambio de invitados;
* cambio de presupuesto;
* asignación;
* cotización;
* descuento;
* cita;
* reprogramación;
* cancelación;
* pago;
* reserva;
* devolución;
* pausa del bot;
* modificación de reglas;
* modificación de respuesta aprobada.

## 22.2 Datos mínimos

```text
Actor
Acción
Entidad
Valor anterior
Valor nuevo
Motivo
Fecha
Solicitud técnica
```

## 22.3 Actores

```text
CUSTOMER
BOT
AGENT
MANAGER
ADMIN
SYSTEM
INTEGRATION
```

---

# 23. Alcance de observabilidad

## 23.1 Logs

* webhook;
* mensaje;
* conversación;
* intención;
* entidades;
* IA;
* acción;
* resultado;
* error;
* tiempo;
* costo.

## 23.2 Métricas

* mensajes;
* respuestas;
* latencia;
* errores;
* coste;
* leads;
* solicitudes;
* visitas;
* escalaciones;
* citas;
* inasistencias;
* fallbacks.

## 23.3 Alertas

* webhook caído;
* errores repetidos;
* IA indisponible;
* calendario indisponible;
* mensajes sin procesar;
* citas inconsistentes;
* costo anormal;
* pagos pendientes;
* conversaciones críticas.

---

# 24. Alcance de ambientes

El proyecto deberá contar con:

```text
DEVELOPMENT
TESTING
PRODUCTION
```

## 24.1 Desarrollo

* datos de prueba;
* números de prueba;
* modelos y servicios configurables;
* logs detallados.

## 24.2 Pruebas

* integración controlada;
* calendario de prueba;
* escenarios automatizados;
* simulación de webhooks.

## 24.3 Producción

* secretos independientes;
* base de datos separada;
* alertas;
* respaldo;
* monitoreo;
* rollback.

---

# 25. Dependencias externas

## 25.1 Proveedor de WhatsApp

Debe permitir:

* webhook;
* envío;
* recepción;
* estados;
* archivos;
* identificadores externos.

## 25.2 OpenRouter

Se utilizará como adaptador para modelos de lenguaje.

## 25.3 Calendario

Deberá permitir:

* consulta;
* creación;
* actualización;
* cancelación;
* identificador externo.

## 25.4 Almacenamiento

Será necesario para:

* documentos;
* comprobantes;
* imágenes;
* cotizaciones.

## 25.5 Proveedor de festivos

El sistema deberá disponer de una fuente confiable o calendario configurado de festivos colombianos.

---

# 26. Supuestos del alcance

1. La Ceiba utilizará un número oficial de WhatsApp.
2. Los asesores operarán desde una bandeja compartida.
3. Existirá acceso a un calendario.
4. Los precios permanecerán bajo control humano.
5. El equipo revisará las respuestas de conocimiento.
6. Manager Leandro será responsable de excepciones.
7. Los horarios podrán configurarse.
8. Los festivos podrán actualizarse.
9. Los archivos podrán almacenarse de forma segura.
10. El sistema tendrá acceso estable a OpenRouter.

---

# 27. Restricciones del alcance

## 27.1 De negocio

* presupuesto referente de $4.000.000;
* cotización humana;
* separación con 50 %;
* no bloqueo sin pago;
* pago validado por asesor;
* sin devolución con menos de un mes;
* visitas limitadas.

## 27.2 Operativas

* atención humana de martes a sábado;
* máximo cuatro visitas;
* máximo tres asistentes;
* visitas solo en la mañana;
* festivos bloqueados.

## 27.3 Técnicas

* riesgo de webhooks duplicados;
* dependencia de proveedores;
* respuestas de IA no confiables sin validación;
* calendario sujeto a conflictos;
* archivos potencialmente inseguros.

---

# 28. Funcionalidades expresamente excluidas

## Comercial

* cotización automática;
* negociación autónoma;
* promociones automáticas;
* cierre automático;
* scoring predictivo;
* campañas comerciales.

## Financiero

* pagos integrados;
* conciliación;
* facturación;
* contabilidad;
* devolución automática.

## Eventos

* planificación integral;
* invitados;
* mesas;
* proveedores;
* cronograma;
* inventario;
* logística completa.

## Canales

* Instagram activo;
* Facebook Messenger;
* correo automatizado;
* llamadas;
* SMS.

## Inteligencia artificial

* voz;
* análisis de video;
* reconocimiento facial;
* análisis avanzado de imágenes;
* decisión contractual;
* fijación de precios.

## Plataforma

* aplicación móvil;
* CRM empresarial;
* ERP;
* portal para clientes;
* portal para proveedores.

---

# 29. Backlog posterior al MVP

## Entradas cerradas

* Incidente de hash de evidencia #1 (cerrado el 2026-08-25): Meta puede representar el
  mismo SHA-256 en base64 en el webhook y en hexadecimal en la metadata. La descarga
  normaliza ambas codificaciones, compara el digest calculado de los bytes y conserva el
  valor verificado en hexadecimal.

## Prioridad alta

* purga automática de evidencias de pago al vencer
  `PAYMENT_EVIDENCE_RETENTION_DAYS`, conservando auditoría y referencias necesarias;
* W2-b.1: notificar al cliente el resultado de la revisión cuando
  `RESP-PAYMENT-004` y `RESP-PAYMENT-005` estén aprobadas; mientras sigan en `DRAFT`,
  la revisión se registra como `customer_notification=DEFERRED` y no crea outbox;
* mostrar en el panel el historial de evidencias ya revisadas; W2-b lista únicamente
  `PENDING_REVIEW`;
* etiquetar explícitamente la nota de rechazo como texto que podrá recibir el cliente antes
  de habilitar `RESP-PAYMENT-005`;
* ejecutar `app` y `worker` como usuario no-root con permisos mínimos sobre el volumen de
  evidencias; hoy ambos contenedores corren como `root` y montan el volumen read-write;
* completar la detección de contexto de pago por código de la última plantilla saliente,
  hoy no persistido como dato consultable en `outbox`/`message`;
* textos pendientes Leandro: `sticker`, `reaction`, `location`, `contacts`, `unsupported`,
  `unknown`;
* motor de cotización;
* paquetes;
* servicios adicionales;
* reglas de precio;
* generación de PDF;
* aprobación digital;
* mayor automatización de seguimiento.
* corregir el bucle de confirmación de clasificaciones en banda incierta: una intención
  aceptada explícitamente por el cliente debe recibir un uplift definitivo antes de volver
  a evaluar las bandas. Requiere censo propio porque afecta todas las intenciones; no forma
  parte de PR-B.2.
* persistir y restaurar la `pending_action` previa en el payload de `pending_confirmation`;
  PR-B.3 solo limpia `CLASSIFY_MESSAGE` tras una confirmación aceptada.
* normalizar puntuación en `is_affirmative`: actualmente `«Sí.»` no cuenta como afirmativo.
  Requiere censo de semántica de confirmaciones y queda como candidato M2.

## Prioridad media

* Instagram;
* W2-c: transcripción de audio; decidir su prioridad con el conteo de auditorías
  `NON_TEXT_MESSAGE_RECEIVED` cuyo `message_type` sea `audio`;
* admitir audio y video como evidencia de pago; W2-b solo admite imagen y documento;
* análisis básico de imágenes;
* enlaces de pago;
* correos;
* panel de métricas ampliado.

## Prioridad futura

* pagos completos;
* contratos;
* firma;
* facturación;
* proveedores;
* inventario;
* operación posventa;
* CRM avanzado.

---

# 30. Criterios de aceptación por módulo

## WhatsApp

* recibe mensajes reales;
* envía respuestas;
* deduplica webhooks;
* registra estados.

## Conversaciones

* conserva contexto;
* no repite preguntas;
* retoma después de varios días;
* permite cambio de tema.

## FAQ

* responde contenido aprobado;
* no inventa;
* funciona sin IA cuando sea determinista.

## Leads

* crea oportunidad;
* registra datos;
* permite corrección;
* conserva estados.

## Solicitudes de cotización

* valida mínimos;
* confirma;
* asigna;
* calcula plazo.

## Agenda

* respeta días;
* respeta horarios;
* respeta anticipación;
* evita duplicados;
* reprograma;
* cancela;
* recuerda.

## Handoff

* genera resumen;
* asigna;
* pausa bot;
* evita respuestas dobles;
* devuelve al bot.

## Pagos

* registra información;
* escala;
* no confirma automáticamente.

## Reservas

* solo reserva después de pago confirmado;
* conserva auditoría.

## Panel

* permite operación básica;
* respeta roles;
* evita acceso directo a base de datos.

---

# 31. Condiciones para declarar completo el alcance

El alcance del MVP se considerará entregado cuando:

1. Todos los módulos incluidos estén implementados.
2. Las exclusiones no hayan sido incorporadas accidentalmente.
3. Los casos críticos estén probados.
4. No existan citas duplicadas.
5. La IA no confirme pagos.
6. La IA no reserve fechas.
7. Los precios permanezcan bajo control humano.
8. La agenda respete las reglas.
9. El handoff pause el bot.
10. Las acciones críticas tengan auditoría.
11. El equipo pueda operar el sistema.
12. Exista un mecanismo de desactivación.
13. Exista documentación.
14. Exista respaldo.
15. Exista monitoreo.

---

# 32. Control de cambios del alcance

Todo cambio deberá registrar:

* descripción;
* razón;
* impacto;
* módulos afectados;
* prioridad;
* aprobación;
* fecha de vigencia;
* pruebas necesarias;
* actualización documental.

No se permitirá incorporar una funcionalidad fuera del alcance únicamente porque sea técnicamente sencilla.

Cada nueva función deberá evaluarse por:

* valor;
* riesgo;
* dependencia;
* costo;
* impacto operativo;
* impacto en fechas del MVP.

---

# 33. Aprobación

Este documento se considerará aprobado cuando el propietario del producto confirme que:

* representa el MVP esperado;
* los módulos incluidos son correctos;
* las exclusiones son aceptables;
* las reglas comerciales están reflejadas;
* la opción B está claramente delimitada;
* la arquitectura queda preparada para la opción A.

Una vez aprobado, será la referencia para:

* requerimientos funcionales;
* arquitectura;
* modelo de datos;
* backlog;
* pruebas;
* desarrollo;
* piloto;
* lanzamiento.
