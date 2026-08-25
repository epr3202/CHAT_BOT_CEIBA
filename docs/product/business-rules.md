# Reglas de negocio

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/product/business-rules.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Documentos relacionados:**

* `/docs/product/vision.md`
* `/docs/product/scope.md`

**Canal inicial:** WhatsApp
**Zona horaria oficial:** `America/Bogota`

---

# 1. Propósito

Este documento define las reglas de negocio que deberán controlar el comportamiento del Asistente Conversacional de La Ceiba Club House.

Las reglas aquí establecidas deberán utilizarse para:

* diseñar la arquitectura;
* construir servicios de dominio;
* controlar el orquestador conversacional;
* validar acciones;
* diseñar la base de datos;
* crear casos de prueba;
* configurar el panel administrativo;
* capacitar a los asesores;
* resolver inconsistencias operativas.

Las reglas de negocio no deberán quedar implementadas únicamente dentro de prompts de inteligencia artificial.

Toda regla crítica deberá ser validada por el backend.

---

# 2. Convenciones

## 2.1 Identificación

Cada regla tendrá un identificador único.

Ejemplo:

```text
BR-CUS-001
```

Donde:

* `BR`: Business Rule.
* `CUS`: dominio de la regla.
* `001`: número consecutivo.

## 2.2 Dominios

| Código  | Dominio                   |
| ------- | ------------------------- |
| `GEN`   | Reglas generales          |
| `CUS`   | Clientes                  |
| `CON`   | Conversaciones            |
| `LEAD`  | Leads                     |
| `EVT`   | Eventos                   |
| `KB`    | Base de conocimiento      |
| `QREQ`  | Solicitudes de cotización |
| `QUOTE` | Cotizaciones              |
| `APT`   | Visitas y agenda          |
| `PAY`   | Pagos                     |
| `RES`   | Reservas                  |
| `CAN`   | Cancelaciones             |
| `HAND`  | Escalamiento humano       |
| `URG`   | Urgencias                 |
| `AI`    | Inteligencia artificial   |
| `SEC`   | Seguridad y privacidad    |
| `AUD`   | Auditoría                 |
| `CFG`   | Configuración             |
| `NOT`   | Notificaciones            |
| `SLA`   | Tiempos de atención       |

## 2.3 Niveles de obligatoriedad

### Obligatoria

La regla debe cumplirse siempre.

### Configurable

La regla tiene un valor inicial aprobado, pero podrá modificarse desde configuración autorizada.

### Recomendada

La regla orienta la experiencia, pero podrá ajustarse sin afectar una operación crítica.

### Restringida

Solo determinados roles podrán ejecutar o modificar la regla.

---

# 3. Principios generales

## BR-GEN-001 — Identidad comercial

El nombre oficial utilizado por el sistema será:

**La Ceiba Club House**

No deberá utilizarse públicamente:

* Seiba Casa Lago;
* Casa Lago;
* nombres técnicos del proyecto;
* nombres internos de módulos.

---

## BR-GEN-002 — Presentación del bot

El asistente se presentará como:

**Equipo de La Ceiba**

No deberá presentarse como:

* inteligencia artificial;
* robot;
* ChatGPT;
* OpenRouter;
* modelo de lenguaje;
* asistente virtual técnico.

---

## BR-GEN-003 — Idioma inicial

El idioma predeterminado del MVP será español.

El sistema podrá detectar otros idiomas, pero la atención multilingüe completa no será obligatoria en el MVP.

---

## BR-GEN-004 — Zona horaria

Todas las operaciones de:

* agenda;
* recordatorios;
* fechas relativas;
* plazos;
* vencimientos;
* horarios de atención;

se calcularán usando:

```text
America/Bogota
```

---

## BR-GEN-005 — Separación entre interpretación y ejecución

La inteligencia artificial podrá interpretar una solicitud, pero no ejecutará directamente acciones críticas.

Toda acción deberá atravesar:

```text
Interpretación
→ validación
→ autorización
→ servicio de dominio
→ persistencia
→ auditoría
```

---

## BR-GEN-006 — Fuente de verdad

Las fuentes oficiales serán:

* base de datos para clientes, leads y estados;
* servicio de agenda para disponibilidad;
* catálogo y reglas para precios futuros;
* asesor para pagos y reservas;
* base de conocimiento aprobada para respuestas;
* auditoría para historial de cambios.

El resumen generado por IA no será fuente de verdad.

---

## BR-GEN-007 — Configurabilidad

Los siguientes valores deberán ser configurables:

* horarios de visitas;
* días permitidos;
* duración;
* margen;
* anticipación mínima;
* máximo diario;
* asistentes;
* horario humano;
* porcentaje de separación;
* tiempo para validar pagos;
* plazo para cotizaciones;
* presupuesto de referencia;
* capacidad;
* respuestas autorizadas;
* días bloqueados.

---

## BR-GEN-008 — Prioridad de reglas

Cuando exista conflicto entre:

1. respuesta de IA;
2. estado conversacional;
3. regla de negocio;
4. estado de base de datos;

prevalecerá:

```text
Regla de negocio
→ estado persistido
→ permisos
→ salida de IA
```

---

# 4. Reglas de ubicación e información general

## BR-KB-001 — Dirección oficial

La dirección autorizada será:

**Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander.**

---

## BR-KB-002 — Enlace oficial de Google Maps

El enlace autorizado será:

```text
https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw
```

---

## BR-KB-003 — Parqueadero

El bot podrá afirmar que La Ceiba cuenta con parqueadero.

No podrá afirmar automáticamente:

* capacidad exacta;
* vigilancia;
* parqueadero cubierto;
* disponibilidad ilimitada;
* reserva de cupos.

Respuesta autorizada:

> Sí, contamos con parqueadero para nuestros clientes e invitados. La disponibilidad depende de la cantidad de asistentes y del montaje del evento.

---

## BR-KB-004 — Capacidad general

El bot podrá comunicar:

* capacidad cómoda aproximada: 50 personas;
* capacidad máxima aproximada: 60 personas;
* capacidad final sujeta al montaje.

---

## BR-KB-005 — Eventos superiores a 60 personas

Cuando el cliente informe más de 60 invitados:

```text
capacity_review_required = true
```

El sistema deberá:

1. registrar la cantidad;
2. evitar confirmar capacidad;
3. escalar a un asesor;
4. utilizar motivo `CAPACITY_REVIEW`.

---

## BR-KB-006 — Espacios oficiales

Los nombres iniciales serán:

* Terraza La Ceiba;
* Salón Ceiba 1;
* Salón Ceiba 2;
* Quiosco de la Piscina.

---

## BR-KB-007 — Capacidades por espacio

| Espacio                   | Capacidad operativa |
| ------------------------- | ------------------: |
| Terraza La Ceiba          |      50 cómodamente |
| Terraza máxima aproximada |                  60 |
| Salón Ceiba 1             |                  15 |
| Salón Ceiba 2             |                  15 |
| Salones combinados        |                  30 |
| Quiosco de la Piscina     |                  20 |

Estas capacidades son orientativas y dependen del montaje.

---

## BR-KB-008 — Prohibición de suma automática de capacidades

La capacidad total no se calculará sumando todos los espacios.

No deberá inferirse:

```text
60 + 15 + 15 + 20 = 110 personas
```

La capacidad combinada deberá ser evaluada por un asesor.

---

## BR-KB-009 — Horario habitual de eventos

El horario habitual de eventos será hasta:

**10:00 p. m.**

Solicitudes posteriores deberán pasar a revisión humana.

---

## BR-KB-010 — Cafetería

La cafetería tendrá como horario inicial:

**Martes a sábado, de 8:00 a. m. a 12:00 m.**

El bot no deberá garantizar productos específicos si no existe menú vigente.

---

## BR-KB-011 — Piscina

La piscina estará incluida en los eventos.

Su uso estará sujeto a:

* horario contratado;
* seguridad;
* clima;
* instrucciones del equipo;
* supervisión de menores;
* condiciones operativas.

---

## BR-KB-012 — Mascotas

Se permiten mascotas.

Deberán permanecer:

* acompañadas;
* bajo responsabilidad de sus responsables;
* con comportamiento adecuado;
* sin afectar a otros clientes.

---

## BR-KB-013 — Proveedores externos

Se permiten proveedores externos.

No existe cobro general por su ingreso.

Su acceso deberá coordinarse previamente.

---

## BR-KB-014 — Alimentos externos

Se permite el ingreso de alimentos externos.

El bot no podrá afirmar que La Ceiba asume responsabilidad por:

* manipulación;
* calidad;
* conservación;
* preparación;
* efectos de alimentos suministrados por terceros.

---

## BR-KB-015 — Licor externo

Se permite el ingreso de bebidas y licor externos.

No se cobrará descorche.

El ingreso deberá coordinarse con el equipo.

---

## BR-KB-016 — Alojamiento

El bot podrá informar que existen opciones de alojamiento, incluida la Suite Oasis.

Toda disponibilidad deberá confirmarse antes de prometer:

* habitación;
* desayuno;
* número de huéspedes;
* precio;
* inclusión en paquete.

---

# 5. Reglas de clientes

## BR-CUS-001 — Identificación inicial

El cliente será identificado inicialmente por su número de WhatsApp.

---

## BR-CUS-002 — Creación provisional

Cuando un número nuevo envíe un mensaje, el sistema podrá crear un cliente provisional con:

* teléfono;
* canal;
* fecha de primer contacto;
* idioma;
* estado activo.

---

## BR-CUS-003 — Nombre

El nombre será obligatorio para:

* solicitar cotización;
* agendar visita;
* registrar reserva.

No será obligatorio para responder preguntas frecuentes.

---

## BR-CUS-004 — No repetición de datos

El bot no solicitará nuevamente un dato que se encuentre:

```text
CONFIRMED
```

---

## BR-CUS-005 — Datos inferidos

Un dato inferido deberá marcarse como:

```text
INFERRED
```

No deberá tratarse como confirmado en operaciones críticas.

---

## BR-CUS-006 — Correcciones

Cuando el cliente corrija un dato:

1. se conservará el valor anterior;
2. se registrará el valor nuevo;
3. se marcará `CORRECTED`;
4. se creará auditoría;
5. se revisará si afecta citas, solicitudes o cotizaciones.

---

## BR-CUS-007 — Múltiples eventos

Un cliente podrá tener varios leads y eventos.

No deberá sobrescribirse un evento anterior al crear uno nuevo.

---

## BR-CUS-008 — Duplicados

El sistema deberá detectar posibles duplicados mediante:

* teléfono;
* correo;
* identificadores de canal.

La consolidación de perfiles requerirá acción autorizada.

---

## BR-CUS-009 — Inasistencias

El sistema mantendrá:

```text
no_show_count
```

Este valor no será visible para el cliente.

---

# 6. Reglas de conversación

## BR-CON-001 — Una pregunta principal

Cada mensaje del bot deberá contener como máximo una pregunta principal compleja.

---

## BR-CON-002 — Extracción múltiple

Si el cliente entrega varios datos en un mensaje, todos deberán extraerse.

Ejemplo:

> Soy Natalia, quiero una boda para 45 personas el 12 de diciembre.

El bot deberá extraer:

* nombre;
* tipo de evento;
* invitados;
* fecha.

---

## BR-CON-003 — Continuidad

Cuando el cliente cambie temporalmente de tema, el sistema deberá:

1. responder el nuevo tema;
2. conservar la acción pendiente;
3. retomar el flujo anterior cuando sea apropiado.

---

## BR-CON-004 — Respuestas cortas

Las respuestas deberán ser breves y apropiadas para WhatsApp.

Como referencia:

* una a cuatro frases;
* una pregunta principal;
* sin bloques extensos innecesarios.

---

## BR-CON-005 — Respuestas contextuales

Mensajes como:

* sí;
* no;
* esa;
* la primera;
* el sábado;
* está bien;

deberán interpretarse según:

* última pregunta;
* opciones mostradas;
* estado;
* acción pendiente.

---

## BR-CON-006 — Ambigüedad

Si la respuesta no puede interpretarse con seguridad, el bot deberá solicitar aclaración.

---

## BR-CON-007 — Fallos de comprensión

### Primer fallo

Ofrecer categorías básicas.

### Segundo fallo

Pedir reformulación o asesor.

### Tercer fallo

Escalar automáticamente.

---

## BR-CON-008 — Retorno del cliente

Cuando el cliente regrese y exista un solo lead activo, el sistema podrá mencionarlo.

Cuando existan varios leads, deberá preguntar cuál desea continuar.

---

## BR-CON-009 — Cierre

Una conversación podrá pasar a `RESOLVED` cuando:

* la pregunta fue resuelta;
* no hay acción pendiente;
* el cliente se despide;
* el flujo fue completado.

---

## BR-CON-010 — Persistencia del contexto

La conversación podrá retomarse después de varios días.

El sistema deberá conservar:

* datos del lead;
* acción pendiente;
* campos faltantes;
* última pregunta;
* historial.

---

# 7. Reglas de leads

## BR-LEAD-001 — Creación de lead

Se podrá crear un lead cuando exista:

* cliente;
* canal;
* intención comercial.

---

## BR-LEAD-002 — Un lead por oportunidad

Cada evento u oportunidad deberá tener un lead independiente.

---

## BR-LEAD-003 — Estados

Los estados permitidos serán:

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

---

## BR-LEAD-004 — Presupuesto preferible

Preguntar el presupuesto será preferible, no obligatorio.

El cliente podrá negarse sin bloquear el flujo.

---

## BR-LEAD-005 — Pregunta de presupuesto

Respuesta autorizada:

> Para recomendarte una experiencia acorde con lo que imaginas, ¿tienes un presupuesto aproximado destinado a la celebración?

---

## BR-LEAD-006 — Presupuesto de referencia

El presupuesto de referencia será:

**$4.000.000 COP.**

---

## BR-LEAD-007 — Presupuesto inferior

Un presupuesto inferior a $4.000.000:

* no rechazará el lead;
* no cerrará la conversación;
* no producirá una respuesta negativa;
* se marcará internamente como `BELOW_REFERENCE`.

---

## BR-LEAD-008 — Respuesta para presupuesto inferior

Respuesta autorizada:

> Gracias por compartirnos tu presupuesto. Nuestro equipo revisará qué alternativa puede ajustarse mejor a lo que estás buscando.

---

## BR-LEAD-009 — Presupuesto no informado

Cuando el cliente no informe presupuesto:

```text
budget_range = NOT_PROVIDED
```

El flujo continuará.

---

## BR-LEAD-010 — Asignación

Durante el MVP, los leads escalados entrarán en una bandeja común.

La asignación se realizará cuando un asesor seleccione:

**Tomar conversación**

---

## BR-LEAD-011 — Pregunta única de presupuesto

1. El presupuesto se pregunta máximo una vez por lead, en la posición del orden de FL-005, usando exclusivamente la plantilla aprobada de vision.md §12.3.
2. Si el cliente declina o evade, se registra `budget_data_status = DECLINED`, el campo se remueve de `pending_fields` y no vuelve a preguntarse en el mismo lead, ni por el bot ni por seguimientos automáticos.
3. Si el cliente lo informa espontáneamente después de declinar, se registra normalmente (`DECLINED → PROVIDED`) sin comentario sobre la negativa previa.
4. `budget_range = BELOW_REFERENCE` es clasificación estrictamente interna: nunca se comunica al cliente, nunca altera el tono ni el flujo visible, y no bloquea ninguna transición.
5. La ausencia de presupuesto nunca bloquea `QUOTE_REQUEST_READY`.

---

# 8. Reglas de eventos

## BR-EVT-001 — Tipos de evento

Los tipos iniciales serán:

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

---

## BR-EVT-002 — Eventos no clasificados

Los eventos no reconocidos se guardarán como:

```text
event_type = OTHER
```

y deberán incluir una descripción.

---

## BR-EVT-003 — Fecha exacta

Cuando el cliente entregue una fecha completa válida:

```text
event_date_type = EXACT
```

---

## BR-EVT-004 — Mes aproximado

Cuando el cliente entregue únicamente un mes:

```text
event_date_type = APPROXIMATE
```

No se inventará día.

---

## BR-EVT-005 — Fecha flexible

Cuando el cliente admita varias fechas:

```text
event_date_type = FLEXIBLE
```

Se podrán registrar:

* mes;
* días preferidos;
* alternativas;
* margen de flexibilidad.

---

## BR-EVT-006 — Fechas relativas

Expresiones como:

* mañana;
* próximo sábado;
* dentro de dos semanas;

deberán convertirse a fecha absoluta y confirmarse.

---

## BR-EVT-007 — Invitados estimados

Si el cliente usa expresiones como:

* unos 40;
* entre 40 y 50;
* aproximadamente 30;

el dato se marcará como estimado.

---

## BR-EVT-008 — Invitados como rango

Cuando exista rango, deberán guardarse:

* mínimo;
* máximo;
* estado estimado.

No deberá convertirse automáticamente en el límite superior.

---

## BR-EVT-009 — Niños

Los niños se incluirán en la capacidad total.

La tarifa será determinada por un asesor según:

* edad;
* menú;
* puesto;
* servicios.

---

## BR-EVT-010 — Alergias

El sistema podrá registrar alergias o requerimientos alimentarios.

No deberá solicitar historia clínica.

---

## BR-EVT-011 — Accesibilidad

El sistema podrá registrar voluntariamente necesidades de accesibilidad.

---

# 9. Reglas de servicios

## BR-EVT-012 — Servicio solicitado

Un servicio mencionado por el cliente deberá guardarse inicialmente como:

```text
REQUESTED
```

---

## BR-EVT-013 — Servicio no confirmado

`REQUESTED` no significa:

* disponible;
* incluido;
* cotizado;
* reservado.

---

## BR-EVT-014 — Servicios sujetos a disponibilidad

Deberán confirmarse:

* DJ;
* músicos;
* fotografía;
* video;
* floristería especializada;
* maquillaje;
* peinado;
* tortas;
* mobiliario adicional;
* alojamiento;
* producción especial.

---

## BR-EVT-015 — Proveedor del cliente

Cuando el cliente lleve un proveedor:

```text
service_status = CLIENT_PROVIDED
```

---

## BR-EVT-016 — Confirmación humana

La disponibilidad final de servicios externos será aprobada por un asesor.

---

# 10. Reglas de solicitudes de cotización

## BR-QREQ-001 — Cotización humana

Durante el MVP, toda cotización personalizada será preparada o aprobada por un asesor.

---

## BR-QREQ-002 — Datos mínimos

Para crear una solicitud lista se requiere:

```text
full_name
phone_number
event_type
date_resolved (fecha, mes, o tipo FLEXIBLE/UNKNOWN declarado)
total_guest_count OR guest_count_range
```

Donde:

```text
date_resolved =
     event_date != null
  OR event_month != null
  OR event_date_type IN (FLEXIBLE, UNKNOWN)
```

El silencio del cliente sobre la fecha no cuenta como `UNKNOWN`.

---

## BR-QREQ-003 — Datos preferibles

Se deberá intentar obtener:

* presupuesto;
* horario;
* espacio;
* alimentos;
* bebidas;
* decoración;
* servicios;
* observaciones;
* correo.

Estos datos no bloquearán la solicitud.

---

## BR-QREQ-004 — Confirmación previa

Antes de crear una solicitud lista, el bot deberá resumir los datos principales y solicitar confirmación.

---

## BR-QREQ-005 — Estado inicial

Una solicitud incompleta se guardará como:

```text
DRAFT
```

---

## BR-QREQ-006 — Solicitud lista

Cuando los datos mínimos estén completos y confirmados:

```text
request_status = READY
```

---

## BR-QREQ-007 — Plazo

El plazo comunicado será:

**Hasta tres días hábiles.**

---

## BR-QREQ-008 — Cálculo del vencimiento

El `due_at` deberá calcularse en días hábiles según la operación definida.

No deberán contarse días no operativos cuando se configure esa política.

---

## BR-QREQ-009 — Respuesta al cliente

Respuesta autorizada:

> Perfecto, la información quedó registrada. Nuestro equipo preparará una propuesta personalizada y te la compartirá por este mismo medio en un plazo de hasta tres días hábiles.

---

## BR-QREQ-010 — Prohibición de precio inventado

El bot no podrá generar:

* precio estimado;
* rango;
* valor por persona;
* total;
* descuento;

sin una regla aprobada y motor activo.

---

## BR-QREQ-011 — Respuesta a “¿Cuánto cuesta?”

Respuesta autorizada:

> Cada evento en La Ceiba se diseña de manera personalizada. El valor depende principalmente de la fecha, la cantidad de invitados y los servicios que quieras incluir. ¿Qué tipo de celebración estás planeando y para cuántas personas aproximadamente?

---

## BR-QREQ-012 — Solicitud lista con fecha por definir

1. Una solicitud puede pasar a `READY` con `date_pending = true` solo si el cliente declaró explícitamente flexibilidad o desconocimiento de fecha.
2. `date_pending` debe ser visible para el asesor en bandeja y en el `summary_snapshot`, que incluirá siempre `event_date_raw`, por ejemplo: `Fecha: por definir — cliente dijo: "todavía no sabemos"`.
3. La ausencia de fecha en la solicitud no relaja INV-ST-009: las citas de visita siguen exigiendo fecha absoluta confirmada. Esta regla aplica únicamente a solicitudes de cotización.
4. El seguimiento de fecha posterior a `READY` queda a criterio del asesor; no se automatiza en este slice.

---

# 11. Reglas de cotizaciones

## BR-QUOTE-001 — Versionado

Toda cotización tendrá número de versión.

---

## BR-QUOTE-002 — Inmutabilidad

Una cotización enviada no se sobrescribirá.

---

## BR-QUOTE-003 — Nueva versión

Se generará una nueva versión cuando cambie:

* fecha;
* invitados;
* menú;
* servicios;
* duración;
* total;
* descuento;
* términos.

---

## BR-QUOTE-004 — Estados

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

---

## BR-QUOTE-005 — Descuentos

Solo un asesor autorizado podrá aplicar descuentos.

---

## BR-QUOTE-006 — Negociación

Toda negociación deberá escalarse.

---

## BR-QUOTE-007 — Futuro motor automático

Cuando se implemente, el motor deberá utilizar:

* reglas;
* catálogos;
* vigencia;
* precios configurados;
* cantidades;
* servicios.

La IA no calculará valores.

---

# 12. Reglas de agenda de visitas

## BR-APT-001 — Días permitidos

Las visitas podrán realizarse:

* martes;
* miércoles;
* jueves;
* viernes;
* sábado.

---

## BR-APT-002 — Días no permitidos

No se ofrecerán visitas:

* lunes;
* domingo;
* festivos oficiales de Colombia;
* fechas bloqueadas manualmente.

---

## BR-APT-003 — Horarios

Los horarios de inicio permitidos serán:

```text
08:00
09:00
10:00
11:00
```

---

## BR-APT-004 — Duración

Cada visita durará:

```text
45 minutos
```

---

## BR-APT-005 — Margen operativo

Entre inicios de visita existirá un intervalo de una hora.

Esto representa:

* 45 minutos de atención;
* 15 minutos de margen.

---

## BR-APT-006 — Máximo diario

Se permitirán máximo:

```text
4 visitas por día
```

---

## BR-APT-007 — Anticipación mínima

La visita deberá programarse con mínimo:

```text
3 días calendario
```

---

## BR-APT-008 — Mismo día

No se permitirán visitas el mismo día.

---

## BR-APT-009 — Día siguiente

No se permitirán visitas para el día siguiente.

---

## BR-APT-010 — Asistentes

El máximo será:

```text
3 asistentes
```

---

## BR-APT-011 — Responsable

Las visitas serán atendidas por el rol:

```text
BUSINESS_MANAGER
```

---

## BR-APT-012 — Datos obligatorios

Para crear una visita se requiere:

* cliente;
* nombre;
* teléfono;
* fecha;
* hora;
* asistentes;
* motivo;
* confirmación.

---

## BR-APT-013 — Confirmación previa

Antes de crear la visita, el bot deberá presentar:

* fecha;
* hora;
* asistentes;
* motivo.

El cliente deberá confirmar.

---

## BR-APT-014 — Doble validación

La disponibilidad deberá comprobarse:

1. antes de mostrar horarios;
2. inmediatamente antes de crear la cita.

---

## BR-APT-015 — Conflicto

Si el horario deja de estar disponible durante la confirmación:

* no se creará la cita;
* se informará al cliente;
* se ofrecerán nuevas opciones.

---

## BR-APT-016 — Unicidad

No podrá existir más de una visita activa para el mismo horario y recurso.

---

## BR-APT-017 — Zona horaria

La cita se guardará en:

```text
America/Bogota
```

---

## BR-APT-018 — Estados

```text
PENDING_CONFIRMATION
CONFIRMED
RESCHEDULED
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

---

## BR-APT-019 — Puntualidad

La hora final no se extenderá automáticamente por retraso del cliente.

---

## BR-APT-020 — Permanencia posterior

Después de la visita, el cliente podrá permanecer en la cafetería.

Esto no ampliará la asesoría formal.

---

# 13. Reglas de reprogramación

## BR-APT-021 — Reprogramación permitida

La visita podrá reprogramarse sin límite automático.

---

## BR-APT-022 — Historial

Cada reprogramación deberá conservar:

* fecha anterior;
* hora anterior;
* fecha nueva;
* hora nueva;
* motivo opcional;
* actor;
* fecha del cambio.

---

## BR-APT-023 — Nueva validación

El nuevo horario deberá validarse como una cita nueva.

---

## BR-APT-024 — Contador

Cada cambio incrementará:

```text
reschedule_count
```

---

## BR-APT-025 — Reincidencia

Varias reprogramaciones podrán generar una notificación interna, pero no bloqueo automático.

---

# 14. Reglas de cancelación de visitas

## BR-APT-026 — Confirmación obligatoria

El sistema no cancelará una visita sin confirmación expresa del cliente o acción autorizada de un asesor.

---

## BR-APT-027 — Cancelación ordinaria

La cancelación ordinaria deberá solicitarse con mínimo un día de anticipación.

---

## BR-APT-028 — Cancelación tardía

Si se cancela con menos de un día:

```text
appointment_status = LATE_CANCEL
```

---

## BR-APT-029 — Trato al cliente

El bot no reprenderá al cliente por cancelación tardía.

---

# 15. Reglas de inasistencia

## BR-APT-030 — Registro

Una inasistencia deberá registrarse como:

```text
NO_SHOW
```

---

## BR-APT-031 — Primera inasistencia

Se permitirá reprogramación.

---

## BR-APT-032 — Segunda inasistencia

Se notificará al equipo.

---

## BR-APT-033 — Tercera inasistencia

Una nueva solicitud de visita deberá escalarse.

---

## BR-APT-034 — No bloqueo automático

El sistema no bloqueará definitivamente al cliente.

---

# 16. Reglas de recordatorios

## BR-NOT-001 — Programación

Se enviará un recordatorio un día antes de la visita.

---

## BR-NOT-002 — Contenido

Deberá incluir:

* nombre;
* fecha;
* hora;
* dirección;
* Maps;
* asistentes;
* puntualidad;
* cancelación o reprogramación.

---

## BR-NOT-003 — Idempotencia

El recordatorio deberá enviarse una sola vez.

---

## BR-NOT-004 — Citas canceladas

No se enviará recordatorio si la visita está cancelada.

---

## BR-NOT-005 — Reprogramación

Si la visita cambia, el recordatorio anterior deberá anularse y crearse uno nuevo.

---

# 17. Reglas de pagos

## BR-PAY-001 — Métodos autorizados

Los métodos permitidos serán:

```text
BANK_TRANSFER
CASH
CARD
NEQUI
DAVIPLATA
PAYMENT_LINK
```

---

## BR-PAY-002 — Datos oficiales

Los datos de pago solo podrán provenir de:

* configuración autorizada;
* asesor;
* enlace oficial.

---

## BR-PAY-003 — Prohibición de invención

La IA no podrá inventar:

* número de cuenta;
* titular;
* banco;
* teléfono;
* enlace;
* instrucciones.

---

## BR-PAY-004 — Comprobante recibido

Cuando el cliente envíe comprobante:

```text
payment_status = PAYMENT_REVIEW
```

---

## BR-PAY-005 — Confirmación humana

Solo un asesor podrá cambiar a:

```text
PAYMENT_CONFIRMED
```

---

## BR-PAY-006 — Tiempo de revisión

El plazo máximo informado será:

**1 día.**

---

## BR-PAY-007 — Respuesta autorizada

> Gracias, recibimos la información de tu pago. Nuestro equipo realizará la validación y te dará confirmación en un plazo máximo de un día. La fecha quedará oficialmente separada cuando la verificación sea aprobada.

---

## BR-PAY-008 — Estado pendiente

Mientras esté en revisión, el sistema no podrá informar que la fecha está reservada.

---

## BR-PAY-009 — Información sensible

El bot no deberá solicitar:

* CVV;
* PIN;
* clave bancaria;
* contraseña;
* código OTP;
* número completo de tarjeta.

---

## BR-PAY-010 — Evidencia de pago Nivel 1

El sistema puede recibir, almacenar, encauzar y auditar comprobantes en imagen o PDF. No
aplica OCR, visión, lectura de montos ni validación automática del contenido. La IA nunca
acepta, rechaza o confirma un pago.

---

## BR-PAY-011 — Revisión restringida y trazable

Solo un administrador autenticado puede descargar y marcar una evidencia como `ACCEPTED`
o `REJECTED`. La transición es de una sola vía, exige nota, identifica al agente y genera
`PAYMENT_EVIDENCE_REVIEWED`. Una plantilla al cliente solo se encola si su versión vigente
está `APPROVED`.

---

# 18. Reglas de reservas

## BR-RES-001 — Porcentaje

La fecha se separará con:

```text
50 %
```

del valor acordado.

---

## BR-RES-002 — Aplicación

El porcentaje se aplicará a todos los eventos, salvo excepción aprobada.

---

## BR-RES-003 — Sin bloqueo previo

La fecha no se bloqueará por:

* interés;
* conversación;
* visita;
* cotización;
* promesa;
* comprobante sin validar.

---

## BR-RES-004 — Condición de reserva

La reserva solo podrá confirmarse cuando:

```text
payment_status = PAYMENT_CONFIRMED
```

---

## BR-RES-005 — Actor autorizado

La confirmación deberá ser realizada por un asesor.

---

## BR-RES-006 — Transición

Después de confirmar el pago:

```text
reservation_status = RESERVED
```

---

## BR-RES-007 — Auditoría

La reserva deberá registrar:

* pago;
* monto;
* porcentaje;
* asesor;
* fecha;
* cotización;
* condiciones.

---

# 19. Reglas de cancelación de eventos

## BR-CAN-001 — Escalamiento obligatorio

Toda cancelación de evento deberá escalarse a un asesor.

---

## BR-CAN-002 — Un mes o más

Cuando falte un mes o más:

* el bot no decidirá devolución;
* el asesor revisará el caso;
* se aplicarán condiciones particulares.

---

## BR-CAN-003 — Menos de un mes

Cuando falte menos de un mes:

```text
refund_allowed = false
```

---

## BR-CAN-004 — Respuesta autorizada

> De acuerdo con nuestras condiciones, las cancelaciones realizadas con menos de un mes de anticipación no generan devolución. De todas formas, voy a compartir tu caso con nuestro equipo para que puedan orientarte.

---

## BR-CAN-005 — Excepciones

Solo un asesor autorizado podrá aprobar:

* cambio de fecha;
* saldo a favor;
* devolución parcial;
* compensación;
* transferencia.

---

## BR-CAN-006 — Prohibición de promesas

El bot no podrá prometer ninguna excepción.

---

# 20. Reglas de handoff humano

## BR-HAND-001 — Motivos

El handoff se activará por:

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

`TEMPLATE_UNAVAILABLE` identifica un fallo al renderizar de forma segura una
plantilla aprobada sin alternativa aplicable. `CATALOG_NOT_AVAILABLE` identifica
una solicitud con `event_type` conocido pero sin PDF activo mapeado; requiere que el
resumen determinista incluya el tipo solicitado.

---

## BR-HAND-002 — Resumen obligatorio

Antes de escalar, el sistema deberá producir un resumen con:

* cliente;
* teléfono;
* motivo;
* evento;
* fecha;
* invitados;
* presupuesto;
* servicios;
* datos faltantes;
* acciones;
* último mensaje;
* prioridad.

---

## BR-HAND-003 — Bandeja compartida

Las conversaciones escaladas entrarán a una bandeja central.

---

## BR-HAND-004 — Toma manual

Un asesor se asignará mediante:

**Tomar conversación**

La toma directa de una conversación sin handoff previo creará un handoff con motivo:

```text
MANUAL_TAKEOVER
```

El handoff nacerá y será tomado en el mismo acto transaccional.

---

## BR-HAND-005 — Exclusividad

Solo un asesor podrá estar activo en una conversación.

---

## BR-HAND-006 — Pausa del bot

Cuando el asesor tome la conversación:

```text
bot_enabled = false
conversation_status = HUMAN_ACTIVE
```

---

## BR-HAND-007 — No simultaneidad

El bot no deberá responder mientras exista un asesor activo.

---

## BR-HAND-008 — Retorno

Un asesor podrá devolver la conversación al bot.

Deberá actualizar el resumen o registrar una nota.

---

## BR-HAND-009 — Horario humano

La atención humana será:

**Martes a sábado, de 8:00 a. m. a 4:00 p. m.**

---

## BR-HAND-010 — Fuera de horario

El bot continuará:

* respondiendo FAQ;
* recopilando datos;
* registrando solicitudes.

Cuando se requiera asesor:

> Tu solicitud ya quedó registrada. Un asesor continuará contigo dentro de nuestro horario de atención, de martes a sábado entre las 8:00 a. m. y las 4:00 p. m.

---

## BR-HAND-011 — Responsable general

El responsable general de escalaciones será:

**Manager Leandro**

---

## BR-HAND-012 — Toma directa sin mensaje automático

La toma directa de una conversación por un asesor no enviará ningún mensaje automático
al cliente.

El primer mensaje posterior a la toma directa deberá escribirlo el asesor humano desde
el panel operativo.

Esta regla evita introducir texto hacia cliente sin plantilla aprobada.

---

# 21. Reglas de quejas

## BR-HAND-013 — Detección

Una queja deberá detectarse cuando exista:

* inconformidad;
* reclamación;
* molestia;
* incumplimiento;
* solicitud de solución;
* lenguaje negativo persistente.

---

## BR-HAND-014 — Prioridad

Las quejas tendrán prioridad mínima:

```text
URGENT
```

---

## BR-HAND-015 — Respuesta

> Lamentamos que estés pasando por esta situación. Queremos revisar tu caso con la atención que merece. Voy a trasladar la conversación a nuestro equipo responsable.

---

## BR-HAND-016 — Prohibiciones

El bot no podrá:

* discutir;
* culpar;
* negar hechos;
* minimizar;
* prometer compensación;
* confirmar devolución.

---

# 22. Reglas de urgencia

## BR-URG-001 — Categorías

Las prioridades serán:

```text
NORMAL
HIGH
URGENT
CRITICAL
```

---

## BR-URG-002 — Evento próximo

Un evento dentro de las próximas 72 horas se marcará como `URGENT`.

---

## BR-URG-003 — Pago pendiente

Un pago reportado pendiente de verificación se marcará como mínimo `URGENT`.

---

## BR-URG-004 — Situaciones críticas

Serán `CRITICAL`:

* emergencia médica;
* incidente de seguridad;
* problema sanitario;
* doble reserva;
* cliente presente sin atención;
* confirmación incorrecta de pago;
* confirmación incorrecta de reserva.

---

## BR-URG-005 — Acción crítica

Un caso crítico deberá:

1. pausar automatización cuando corresponda;
2. notificar responsables;
3. registrar evento;
4. mostrar respuesta segura;
5. evitar decisiones automáticas.

---

## BR-URG-006 — Emergencias físicas

El bot deberá indicar contacto inmediato con:

* personal presente;
* servicios de emergencia.

---

# 23. Reglas de inteligencia artificial

## BR-AI-001 — Funciones autorizadas

La IA podrá utilizarse para:

```text
INTENT_CLASSIFICATION
ENTITY_EXTRACTION
RESPONSE_DRAFTING
CONVERSATION_SUMMARY
CONFIDENCE_EVALUATION
```

---

## BR-AI-002 — Separación de funciones

No deberá utilizarse una única llamada de IA para interpretar, ejecutar y responder.

---

## BR-AI-003 — Salida estructurada

Clasificación y extracción deberán devolver JSON validable.

---

## BR-AI-004 — Confianza

Cuando la confianza sea inferior al umbral configurado:

* no se ejecutará acción crítica;
* se solicitará aclaración;
* podrá escalarse.

Precisión: en una posición que pregunta directamente el tipo de evento, una clasificación
`EVENT_INFORMATION` en banda incierta puede continuar por el camino confiado únicamente si
incluye una entidad `event_type` `PROVIDED` o `CORRECTED`, sin confirmación pendiente, con
confianza de entidad mayor o igual a `AI_CONFIDENCE_SAFE` y valor normalizable. Esta
excepción no cambia los umbrales, no aplica a intenciones sensibles ni a otras entidades,
y debe auditarse como decisión del backend sin alterar la ejecución literal de la IA.

Una clasificación recuperada desde `pending_confirmation` después de una afirmación
explícita constituye una decisión humana definitiva: se despacha sin reevaluar las bandas,
para cualquier intención, manteniendo intactas su confianza y trazabilidad original. El
backend registra `CONFIRMATION_UPLIFT`; las clasificaciones frescas conservan sin cambios
los umbrales configurados.

---

## BR-AI-005 — Acciones prohibidas

La IA no podrá:

* calcular precios;
* confirmar disponibilidad;
* crear una cita sin backend;
* confirmar pagos;
* reservar;
* aprobar devolución;
* ofrecer descuento;
* cambiar reglas;
* asignar permisos.

---

## BR-AI-006 — Validación

Toda salida deberá validarse mediante esquema.

---

## BR-AI-007 — Fallo de IA

Ante fallo:

* guardar mensaje;
* registrar error;
* usar FAQ determinista;
* permitir menú;
* escalar operaciones críticas.

---

## BR-AI-008 — No exposición técnica

El cliente no deberá recibir:

* nombre de modelo;
* prompt;
* error interno;
* JSON;
* stack trace;
* proveedor.

---

# 24. Reglas de seguridad y privacidad

## BR-SEC-001 — Minimización

Solo se solicitarán datos necesarios para el flujo.

---

## BR-SEC-002 — Datos prohibidos

El bot no solicitará:

* contraseñas;
* PIN;
* CVV;
* OTP;
* claves bancarias;
* información financiera innecesaria;
* documentos sin finalidad;
* datos médicos completos;
* información política;
* religión;
* datos íntimos.

---

## BR-SEC-003 — Archivos

Los archivos recibidos deberán:

* almacenarse de forma protegida;
* asociarse al cliente;
* tener acceso controlado;
* registrar tipo y tamaño.

---

## BR-SEC-004 — Roles

Las funciones administrativas deberán restringirse por rol.

---

## BR-SEC-005 — Secretos

Los secretos no deberán almacenarse en código fuente.

---

## BR-SEC-006 — Webhook

El webhook deberá validar:

* firma;
* origen;
* tamaño;
* estructura;
* identificador.

---

## BR-SEC-007 — Idempotencia

El identificador externo de mensaje deberá ser único.

---

# 25. Reglas de auditoría

## BR-AUD-001 — Cambios críticos

Siempre deberán auditarse:

* fecha;
* invitados;
* presupuesto;
* asignación;
* cita;
* cotización;
* descuento;
* pago;
* reserva;
* cancelación;
* devolución;
* pausa del bot;
* reglas;
* respuestas.

---

## BR-AUD-002 — Datos de auditoría

Cada evento deberá registrar:

* actor;
* acción;
* entidad;
* valor anterior;
* valor nuevo;
* motivo;
* fecha;
* identificador de solicitud.

---

## BR-AUD-003 — Inmutabilidad de mensajes

Los mensajes no deberán sobrescribirse.

---

## BR-AUD-004 — Versionado documental

Las respuestas y cotizaciones deberán conservar versiones.

---

# 26. Reglas de SLA

## BR-SLA-001 — Cotización

El plazo será:

**Hasta tres días hábiles.**

---

## BR-SLA-002 — Pago

La validación deberá realizarse en máximo:

**1 día.**

---

## BR-SLA-003 — Recordatorio

El recordatorio deberá enviarse un día antes de la visita.

---

## BR-SLA-004 — Solicitudes fuera de horario

Se informará el próximo horario humano, sin prometer una hora exacta.

---

## BR-SLA-005 — Medición

El sistema deberá registrar:

* fecha de solicitud;
* fecha límite;
* fecha de asignación;
* fecha de resolución;
* cumplimiento.

---

# 27. Reglas de configuración

## BR-CFG-001 — Valores iniciales

| Parámetro                   | Valor                    |
| --------------------------- | ------------------------ |
| Zona horaria                | America/Bogota           |
| Presupuesto referente       | $4.000.000 COP           |
| Plazo de cotización         | 3 días hábiles           |
| Porcentaje de separación    | 50 %                     |
| Validación de pago          | 1 día                    |
| Días de visita              | Martes a sábado          |
| Horarios de visita          | 8:00, 9:00, 10:00, 11:00 |
| Duración                    | 45 minutos               |
| Margen                      | 15 minutos               |
| Anticipación                | 3 días                   |
| Máximo diario               | 4                        |
| Asistentes                  | 3                        |
| Recordatorio                | 1 día antes              |
| Horario humano              | 8:00 a. m.–4:00 p. m.    |
| Capacidad cómoda            | 50                       |
| Capacidad máxima aproximada | 60                       |
| Cierre habitual de eventos  | 10:00 p. m.              |

---

## BR-CFG-002 — Modificación

Solo roles autorizados podrán modificar valores.

---

## BR-CFG-003 — Vigencia

Los cambios deberán registrar:

* valor anterior;
* valor nuevo;
* responsable;
* fecha;
* vigencia.

---

## BR-CFG-004 — Aplicación histórica

Los cambios de reglas no deberán alterar retroactivamente:

* cotizaciones enviadas;
* reservas confirmadas;
* condiciones aceptadas;
* pagos.

---

# 28. Matriz de autoridad

| Acción                        |                     Bot |      Asesor |          Manager |        Backend |
| ----------------------------- | ----------------------: | ----------: | ---------------: | -------------: |
| Responder FAQ                 |                      Sí |          Sí |               Sí |         Valida |
| Registrar cliente             |                      Sí |          Sí |               Sí |             Sí |
| Crear lead                    |                      Sí |          Sí |               Sí |             Sí |
| Solicitar datos               |                      Sí |          Sí |               Sí |       Controla |
| Crear solicitud de cotización |                      Sí |          Sí |               Sí |             Sí |
| Definir precio                |                      No |          Sí |               Sí | Guarda/calcula |
| Aplicar descuento             |                      No | Restringido |               Sí |         Valida |
| Consultar agenda              |                Solicita |          Sí |               Sí |             Sí |
| Crear visita                  |                Solicita |          Sí |               Sí |        Ejecuta |
| Reprogramar visita            |                Solicita |          Sí |               Sí |        Ejecuta |
| Cancelar visita               |                Solicita |          Sí |               Sí |        Ejecuta |
| Confirmar pago                |                      No |          Sí |               Sí |       Persiste |
| Confirmar reserva             |                      No |          Sí |               Sí |         Valida |
| Aprobar devolución            |                      No | Restringido |               Sí |       Persiste |
| Modificar reglas              |                      No |          No | Sí/Administrador |       Persiste |
| Pausar bot                    | No autónomo salvo regla |          Sí |               Sí |        Ejecuta |
| Resolver queja                |                      No |          Sí |               Sí |       Registra |

---

# 29. Invariantes críticas

Las siguientes condiciones nunca deberán violarse:

## INV-001

No puede existir una reserva sin pago confirmado.

```text
reservation_status = RESERVED
→ payment_status = PAYMENT_CONFIRMED
```

## INV-002

No puede existir doble visita activa para el mismo horario.

## INV-003

No puede responder el bot cuando:

```text
conversation_status = HUMAN_ACTIVE
```

## INV-004

Una cotización enviada no puede sobrescribirse.

## INV-005

Un mensaje externo no puede procesarse dos veces.

## INV-006

La IA no puede cambiar estados de pago o reserva directamente.

## INV-007

Una fecha relativa crítica debe confirmarse en formato absoluto.

## INV-008

Un servicio solicitado no puede presentarse como incluido sin confirmación.

## INV-009

Un presupuesto inferior al referente no puede generar rechazo automático.

## INV-010

Una cancelación de evento debe escalarse.

---

# 30. Criterios de aceptación

Este documento se considerará correctamente implementado cuando:

1. Cada regla crítica tenga una validación en backend.
2. Las reglas configurables no estén codificadas únicamente en prompts.
3. Existan pruebas unitarias para agenda, pagos y reservas.
4. Existan pruebas de integración para mensajes duplicados.
5. Existan pruebas conversacionales para respuestas sensibles.
6. La IA no pueda ejecutar operaciones restringidas.
7. Cada cambio crítico genere auditoría.
8. Los asesores tengan permisos diferenciados.
9. El bot se pause durante atención humana.
10. Los plazos se calculen correctamente.
11. Los festivos sean excluidos.
12. Las reglas históricas no se modifiquen retroactivamente.
13. La operación continúe si OpenRouter falla.
14. Las respuestas aprobadas tengan versión.
15. Las reservas solo se creen después de confirmación humana.

---

# 31. Trazabilidad requerida

Cada requerimiento funcional futuro deberá indicar qué reglas implementa.

Ejemplo:

```text
FR-APT-001 — Consultar disponibilidad
Implementa:
- BR-APT-001
- BR-APT-002
- BR-APT-003
- BR-APT-006
- BR-APT-007
- BR-APT-014
```

---

# 31A. BR-AUTH — Autenticación operativa

## BR-AUTH-001

Toda acción administrativa u operativa queda atribuida a un usuario (`agent`) con rol
`ADMIN` o `AGENT`; no existen acciones anónimas.

## BR-AUTH-002

La credencial de login es cédula como identificador y PIN como secreto de mínimo 6
caracteres. El PIN se almacena únicamente con hash bcrypt.

## BR-AUTH-003

Las sesiones expiran a las 12 horas y pueden revocarse.

## BR-AUTH-004

Solo `ADMIN` puede crear usuarios, restablecer credenciales, desactivar usuarios y
reabrir conversaciones `CLOSED`.

## BR-AUTH-005

Los roles `ADMIN` y `AGENT` pueden tomar conversaciones, responder y devolver. En todos
los casos la operación usa un `assigned_agent_id` real.

Cada prueba deberá indicar:

* requerimiento;
* regla;
* resultado esperado.

---

# 32. Control de cambios

Cualquier cambio deberá incluir:

1. Identificador de regla.
2. Descripción del cambio.
3. Justificación.
4. Fecha de aprobación.
5. Responsable.
6. Fecha de vigencia.
7. Módulos afectados.
8. Pruebas que deben actualizarse.
9. Impacto en conversaciones existentes.
10. Impacto en cotizaciones o reservas.

Las reglas eliminadas no deberán borrarse del historial. Se marcarán como:

```text
INACTIVE
```

---

# 33. Aprobación

Este documento queda listo para utilizarse como fuente oficial de reglas del MVP.

Su aprobación implica que:

* las reglas reflejan la operación definida;
* los límites de autoridad están claros;
* la agenda está completamente especificada;
* pagos y reservas requieren validación humana;
* la cotización permanece bajo control del asesor;
* las excepciones son humanas;
* el backend será responsable de validar operaciones;
* la IA se limita a interpretar, extraer, resumir y redactar.
