# Catálogo de entidades conversacionales

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/conversation/entities.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Zona horaria oficial:** `America/Bogota`
**Canal inicial:** WhatsApp

**Documentos relacionados:**

* `/docs/product/vision.md`
* `/docs/product/scope.md`
* `/docs/product/business-rules.md`
* `/docs/product/use-cases.md`
* `/docs/product/data-matrix.md`
* `/docs/conversation/intents.md`

---

# 1. Propósito

Este documento define el catálogo oficial de entidades que el Asistente Conversacional de La Ceiba Club House podrá identificar, extraer, normalizar, validar, confirmar y entregar a los servicios del backend.

Una entidad representa un dato concreto mencionado por el cliente dentro de una conversación.

Ejemplos:

```text
“Quiero una boda para 45 personas el 12 de diciembre”
```

Entidades extraídas:

```json
{
  "event_type": "WEDDING",
  "guest_count": 45,
  "event_date": "2026-12-12"
}
```

El catálogo de entidades permitirá:

* transformar lenguaje natural en datos estructurados;
* evitar preguntas repetidas;
* completar solicitudes de cotización;
* gestionar visitas;
* reconocer correcciones;
* interpretar fechas relativas;
* registrar servicios;
* identificar pagos;
* detectar quejas y urgencias;
* validar que una acción puede ejecutarse;
* mantener trazabilidad sobre el origen y calidad de cada dato.

La inteligencia artificial podrá proponer entidades, pero el backend será responsable de validarlas antes de utilizarlas en operaciones críticas.

---

# 2. Principios generales de extracción

## ENT-GEN-001 — No inventar valores

El sistema no deberá completar un dato que el cliente no haya proporcionado o que no pueda derivarse de forma segura.

Ejemplo incorrecto:

```text
Cliente: “Quiero una boda en diciembre”.
```

No se deberá guardar:

```json
{
  "event_date": "2026-12-12"
}
```

Se deberá guardar:

```json
{
  "event_month": "2026-12",
  "event_date_type": "APPROXIMATE"
}
```

---

## ENT-GEN-002 — Conservar la expresión original

Cuando sea relevante, el sistema deberá conservar:

* texto original;
* valor normalizado;
* nivel de confianza;
* necesidad de confirmación.

Ejemplo:

```json
{
  "raw_value": "el próximo sábado",
  "normalized_value": "2026-08-08",
  "confidence": 0.91,
  "needs_confirmation": true
}
```

---

## ENT-GEN-003 — Diferenciar extracción y confirmación

Extraer un dato no significa que esté confirmado.

Cada entidad deberá tener un estado de calidad:

```text
UNKNOWN
INFERRED
PROVIDED
PENDING_CONFIRMATION
CONFIRMED
CORRECTED
INVALID
```

---

## ENT-GEN-004 — Extraer todos los datos disponibles

Si un mensaje contiene varios datos, todos deberán ser procesados.

Mensaje:

> Hola, soy Camila. Quiero una boda para 50 personas el 20 de diciembre y tengo un presupuesto de 12 millones.

Resultado:

```json
{
  "full_name": "Camila",
  "event_type": "WEDDING",
  "guest_count": 50,
  "event_date": "2026-12-20",
  "estimated_budget": 12000000,
  "currency": "COP"
}
```

El bot no deberá preguntar nuevamente por estos campos.

---

## ENT-GEN-005 — No sobrescribir datos confirmados silenciosamente

Cuando un nuevo mensaje contradiga un dato confirmado:

1. Se detectará la diferencia.
2. Se identificará como corrección potencial.
3. Se validará el nuevo dato.
4. Se confirmará cuando sea necesario.
5. Se conservará el valor anterior en auditoría.

---

## ENT-GEN-006 — Contexto conversacional

Las entidades podrán depender de:

* última pregunta;
* intención actual;
* estado;
* acción pendiente;
* opciones mostradas;
* datos ya registrados.

Ejemplo:

```text
Bot: “Tenemos 8:00, 9:00 y 11:00. ¿Cuál prefieres?”
Cliente: “La de las 9”.
```

Entidad:

```json
{
  "preferred_visit_time": "09:00"
}
```

---

## ENT-GEN-007 — Operaciones críticas

Las entidades relacionadas con estas operaciones requieren validación reforzada:

* creación de citas;
* reprogramaciones;
* cancelaciones;
* pagos;
* reservas;
* devoluciones;
* cambio de fecha de un evento reservado;
* descuentos;
* condiciones contractuales.

---

# 3. Estructura estándar de una entidad extraída

Cada entidad deberá poder representarse mediante la siguiente estructura lógica:

```json
{
  "entity_name": "event_date",
  "raw_value": "el próximo sábado",
  "normalized_value": "2026-08-08",
  "data_type": "date",
  "quality_status": "PENDING_CONFIRMATION",
  "confidence": 0.91,
  "source": "CUSTOMER_MESSAGE",
  "message_id": "uuid",
  "needs_confirmation": true,
  "validation_errors": [],
  "metadata": {
    "timezone": "America/Bogota"
  }
}
```

## Campos

| Campo                | Descripción                               |
| -------------------- | ----------------------------------------- |
| `entity_name`        | Nombre oficial de la entidad              |
| `raw_value`          | Expresión exacta usada por el cliente     |
| `normalized_value`   | Valor transformado al formato del sistema |
| `data_type`          | Tipo lógico                               |
| `quality_status`     | Estado de calidad                         |
| `confidence`         | Confianza entre 0 y 1                     |
| `source`             | Origen del dato                           |
| `message_id`         | Mensaje donde apareció                    |
| `needs_confirmation` | Indica si debe preguntarse al cliente     |
| `validation_errors`  | Errores detectados                        |
| `metadata`           | Información adicional                     |

---

# 4. Fuentes de entidades

Las fuentes permitidas serán:

```text
CUSTOMER_MESSAGE
CHANNEL_METADATA
AGENT_INPUT
SYSTEM_CALCULATION
CALENDAR_PROVIDER
PAYMENT_REVIEW
KNOWLEDGE_CONFIGURATION
AI_INFERENCE
IMPORTED_DATA
```

## 4.1 CUSTOMER_MESSAGE

Dato declarado explícitamente por el cliente.

Ejemplo:

> “Me llamo Natalia”.

## 4.2 CHANNEL_METADATA

Dato obtenido automáticamente desde WhatsApp.

Ejemplo:

* número de teléfono;
* identificador del mensaje;
* fecha de recepción.

## 4.3 AGENT_INPUT

Dato registrado o confirmado por un asesor.

## 4.4 SYSTEM_CALCULATION

Dato derivado mediante una regla determinista.

Ejemplo:

* total de invitados;
* hora de finalización de una visita;
* fecha límite de cotización.

## 4.5 CALENDAR_PROVIDER

Dato recuperado de la agenda.

Ejemplo:

* horario disponible;
* identificador externo.

## 4.6 AI_INFERENCE

Dato inferido por IA que todavía requiere validación.

---

# 5. Clasificación del catálogo

Las entidades se agrupan en:

```text
Cliente
Evento
Fecha y tiempo
Invitados
Presupuesto
Espacios
Servicios
Cotización
Visitas
Pagos
Reservas
Cancelaciones
Handoff
Quejas
Urgencias
Contexto conversacional
Archivos
```

---

# 6. Entidades del cliente

## 6.1 `full_name`

### Definición

Nombre completo o nombre principal con el que se identifica el cliente.

### Tipo

```text
string
```

### Ejemplos positivos

* “Me llamo Natalia Pérez”.
* “Soy Andrés”.
* “Mi nombre es Camila”.
* “Hablas con Juan Carlos”.

### Ejemplos negativos

* “La novia se llama Natalia”.
* “El fotógrafo es Andrés”.

El sistema deberá distinguir al cliente de terceros mencionados.

### Normalización

* eliminar espacios duplicados;
* preservar tildes;
* aplicar capitalización razonable;
* no añadir apellidos inexistentes.

### Validaciones

* entre 2 y 120 caracteres;
* no debe ser únicamente un emoji;
* no debe contener únicamente números;
* no debe confundirse con el nombre del evento.

### Confirmación

Obligatoria si:

* el nombre fue inferido;
* existe ambigüedad;
* se utilizará en una cita o cotización.

### Intenciones relacionadas

* `GREETING`;
* `QUOTE_REQUEST`;
* `SCHEDULE_VISIT`;
* `EVENT_INFORMATION`.

---

## 6.2 `preferred_name`

### Definición

Nombre corto o forma preferida de trato.

Ejemplos:

* “Me llamo Alejandro, pero dime Alejo”.
* “Puedes decirme Nati”.

### Tipo

```text
string
```

### Uso

Personalización de respuestas.

No sustituye obligatoriamente al nombre formal en documentos.

---

## 6.3 `phone_number`

### Definición

Número de contacto del cliente.

### Fuente principal

```text
CHANNEL_METADATA
```

### Tipo normalizado

```text
E.164
```

Ejemplo:

```text
+573001234567
```

### Regla

El bot no deberá preguntar el número cuando ya provenga del canal, salvo que el cliente quiera registrar un número alternativo.

---

## 6.4 `email`

### Tipo

```text
email
```

### Ejemplos

* “Mi correo es [natalia@gmail.com](mailto:natalia@gmail.com)”.
* “Puedes enviarla a [eventos@empresa.com](mailto:eventos@empresa.com)”.

### Validaciones

* formato válido;
* máximo 254 caracteres;
* convertir a minúsculas;
* eliminar espacios.

### Confirmación

Recomendada antes de enviar documentos.

---

## 6.5 `city`

### Definición

Ciudad de residencia o procedencia del cliente cuando sea relevante.

### Tipo

```text
string
```

### Regla

No es obligatoria para los flujos del MVP.

---

## 6.6 `preferred_contact_channel`

### Valores

```text
WHATSAPP
PHONE_CALL
EMAIL
```

### Ejemplos

* “Prefiero que me escriban”.
* “¿Me pueden llamar?”
* “Envíenme la información al correo”.

### Regla

No se ejecutarán llamadas automáticas en el MVP.

---

## 6.7 `preferred_contact_time`

### Tipo

```text
time_range
```

### Ejemplos

* “Pueden llamarme después de las 2”.
* “Prefiero en la mañana”.
* “Escríbanme después de las 5”.

### Normalización

Los periodos generales podrán convertirse en rangos configurados:

```text
MORNING
AFTERNOON
EVENING
EXACT_TIME
```

---

# 7. Entidades del evento

## 7.1 `event_type`

### Definición

Tipo normalizado de celebración.

### Valores permitidos

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
OTHER
```

### Ejemplos

| Expresión                        | Valor             |
| -------------------------------- | ----------------- |
| “Quiero casarme”                 | `WEDDING`         |
| “Será una ceremonia civil”       | `CIVIL_WEDDING`   |
| “Quiero pedirle matrimonio”      | `PROPOSAL`        |
| “Es el cumpleaños de mi mamá”    | `BIRTHDAY`        |
| “Celebramos nuestro aniversario” | `ANNIVERSARY`     |
| “Es una reunión de empresa”      | `CORPORATE_EVENT` |
| “Quiero una cena para mi pareja” | `ROMANTIC_DINNER` |

### Confirmación

Se requiere cuando:

* la expresión pueda corresponder a varias categorías;
* fue inferida indirectamente;
* se utilizará para cotizar.

---

## 7.2 `event_type_other`

### Definición

Descripción libre cuando `event_type = OTHER`.

### Ejemplos

* exhibición de autos;
* lanzamiento de producto;
* ceremonia simbólica;
* sesión fotográfica;
* evento cultural.

### Validación

Entre 3 y 150 caracteres.

---

## 7.3 `event_description`

### Definición

Explicación general de lo que imagina el cliente.

### Ejemplos

* “Quiero algo natural y elegante”.
* “Será una reunión familiar tranquila”.
* “Queremos una boda boho al atardecer”.

### Tipo

```text
string
```

### Uso

Contexto para el asesor, no cálculo automático.

---

## 7.4 `special_requests`

### Definición

Solicitudes particulares que no encajan en campos específicos.

### Ejemplos

* “Necesitamos espacio para una ceremonia religiosa”.
* “Queremos que todo sea azul y blanco”.
* “Uno de los invitados usa silla de ruedas”.

### Regla

No deben utilizarse como sustituto de entidades estructuradas conocidas.

---

# 8. Entidades de fecha del evento

## 8.1 `event_date`

### Tipo

```text
date: YYYY-MM-DD
```

### Ejemplos

* “El 12 de diciembre de 2026”.
* “Para el 20 de noviembre”.
* “El día 15 de febrero”.

### Reglas

* el año podrá inferirse únicamente cuando el contexto sea claro;
* una fecha pasada deberá validarse;
* una fecha sin año puede requerir confirmación;
* se utiliza `America/Bogota`.

### Ejemplo estructurado

```json
{
  "raw_value": "12 de diciembre",
  "normalized_value": "2026-12-12",
  "needs_confirmation": true
}
```

---

## 8.2 `event_month`

### Tipo

```text
year-month: YYYY-MM
```

### Ejemplos

* “En diciembre”.
* “Para marzo del otro año”.
* “Más o menos en junio”.

### Regla

No se inventará un día.

---

## 8.3 `event_date_type`

### Valores

```text
EXACT
APPROXIMATE
FLEXIBLE
UNKNOWN
```

### Asignación

| Expresión                     | Tipo          |
| ----------------------------- | ------------- |
| “12 de diciembre de 2026”     | `EXACT`       |
| “En diciembre”                | `APPROXIMATE` |
| “Cualquier sábado de febrero” | `FLEXIBLE`    |
| “Todavía no sé”               | `UNKNOWN`     |

---

## 8.4 `date_flexibility`

### Valores sugeridos

```text
NONE
PLUS_MINUS_DAYS
SAME_WEEK
SAME_MONTH
MULTIPLE_MONTHS
FULLY_FLEXIBLE
```

### Ejemplos

* “Puede ser una semana antes o después”.
* “Cualquier sábado de diciembre”.
* “No importa la fecha”.

---

## 8.5 `alternative_dates`

### Tipo

```text
array<date>
```

### Ejemplo

> “Puede ser el 12, 19 o 26 de diciembre”.

Resultado:

```json
{
  "alternative_dates": [
    "2026-12-12",
    "2026-12-19",
    "2026-12-26"
  ]
}
```

---

## 8.6 `preferred_weekday`

### Valores

```text
MONDAY
TUESDAY
WEDNESDAY
THURSDAY
FRIDAY
SATURDAY
SUNDAY
```

### Ejemplo

> “Preferiblemente un sábado”.

---

## 8.7 Invariante de consistencia del triplete de fecha

```text
event_date != null              → event_date_type = EXACT
event_date_type = EXACT         → event_date != null
event_date_type = APPROXIMATE   → event_date = null AND event_month != null
event_date_type = FLEXIBLE      → event_date = null (event_month opcional)
event_date_type = UNKNOWN       → event_date = null AND event_month = null
event_date_raw != null en todo caso donde el cliente haya mencionado fecha
```

Este invariante se valida en el orquestador al persistir, no en el clasificador.

Toda escritura de fecha actualiza `event_date`, `event_month`, `event_date_type` y `event_date_raw` de forma atómica; nunca campos sueltos.

---

# 9. Entidades de horario del evento

## 9.1 `event_start_time`

### Tipo

```text
time: HH:mm
```

### Ejemplos

* “A las 5 de la tarde”.
* “Desde las 3”.
* “Queremos empezar a las 7 p. m.”

### Normalización

```text
17:00
15:00
19:00
```

### Confirmación

Obligatoria si:

* no se indica a. m. o p. m.;
* el horario resulta poco probable;
* se usará en una propuesta formal.

---

## 9.2 `event_end_time`

### Ejemplos

* “Hasta las 10”.
* “Queremos terminar a medianoche”.
* “La fiesta sería hasta la 1 a. m.”

### Regla

Solicitudes posteriores a las 10:00 p. m. deberán marcar:

```text
special_schedule_review_required = true
```

---

## 9.3 `estimated_duration_minutes`

### Fuente

Puede calcularse cuando existen inicio y fin.

### Regla

La IA no deberá hacer cálculos ambiguos. El backend realizará la diferencia.

---

# 10. Entidades de invitados

## 10.1 `guest_count`

### Definición

Cantidad total aproximada o confirmada de invitados.

### Tipo

```text
integer
```

### Ejemplos

* “Somos 40”.
* “Para 55 personas”.
* “Van aproximadamente 30 invitados”.

### Validaciones

* mayor a cero;
* máximo técnico configurable;
* más de 60 activa revisión;
* debe diferenciarse entre estimado y confirmado.

---

## 10.2 `guest_count_min`

### Tipo

```text
integer
```

### Ejemplo

> “Entre 40 y 50”.

Resultado:

```json
{
  "guest_count_min": 40,
  "guest_count_max": 50,
  "guest_count_status": "ESTIMATED"
}
```

---

## 10.3 `guest_count_max`

Debe ser mayor o igual a `guest_count_min`.

---

## 10.4 `guest_count_status`

### Valores

```text
ESTIMATED
CONFIRMED
RANGE
UNKNOWN
```

---

## 10.5 `adult_guest_count`

### Ejemplos

* “Van 30 adultos”.
* “Somos 25 mayores”.

### Tipo

```text
integer
```

---

## 10.6 `child_guest_count`

### Ejemplos

* “Van 10 niños”.
* “Hay cinco menores”.

### Regla

Se incluirán en la capacidad total.

---

## 10.7 `infant_guest_count`

### Ejemplos

* “Van dos bebés”.
* “Hay tres niños de brazos”.

---

## 10.8 `children_age_ranges`

### Tipo

```text
array<age_or_range>
```

### Ejemplos

* “Los niños tienen entre 4 y 10 años”.
* “Hay dos de 5 y uno de 8”.
* “Los bebés tienen menos de 2”.

### Uso

* menú;
* sillas;
* piscina;
* operación.

No se recopilarán nombres o documentos de menores.

---

## 10.9 `capacity_review_required`

### Tipo

```text
boolean
```

### Fuente

```text
SYSTEM_CALCULATION
```

### Regla

```text
guest_count > 60
→ capacity_review_required = true
```

---

# 11. Entidades de presupuesto

## 11.1 `estimated_budget`

### Tipo

```text
decimal
```

### Moneda inicial

```text
COP
```

### Ejemplos

| Expresión                         |    Valor |
| --------------------------------- | -------: |
| “Tengo 10 millones”               | 10000000 |
| “Mi presupuesto es de $4.500.000” |  4500000 |
| “Unos ocho palos”                 |  8000000 |
| “2 millones y medio”              |  2500000 |

### Confirmación

Recomendada cuando:

* la expresión es coloquial;
* existe duda entre valor total o por persona;
* se menciona una moneda diferente.

---

## 11.2 `budget_min`

Ejemplo:

> “Entre 8 y 10 millones”.

```json
{
  "budget_min": 8000000,
  "budget_max": 10000000,
  "currency": "COP"
}
```

---

## 11.3 `budget_max`

Debe ser mayor o igual al mínimo.

---

## 11.4 `budget_range`

### Valores

```text
NOT_PROVIDED
BELOW_REFERENCE
REFERENCE_RANGE
PREMIUM
CUSTOM
```

### Fuente

```text
SYSTEM_CALCULATION
```

### Regla inicial

```text
estimated_budget < 4000000
→ BELOW_REFERENCE
```

Esta clasificación no se muestra al cliente.

---

## 11.5 `currency`

### Valores iniciales

```text
COP
USD
OTHER
UNKNOWN
```

El MVP operará comercialmente en COP.

---

## 11.6 `budget_is_per_person`

### Tipo

```text
boolean
```

### Ejemplo

> “Tengo 150.000 por persona”.

La entidad deberá diferenciar:

```json
{
  "estimated_budget": 150000,
  "budget_is_per_person": true
}
```

No debe confundirse con el presupuesto total.

---

# 12. Entidades de espacios

## 12.1 `preferred_space`

### Valores

```text
TERRAZA_LA_CEIBA
SALON_CEIBA_1
SALON_CEIBA_2
SALONES_COMBINADOS
QUIOSCO_PISCINA
POOL_AREA
UNSPECIFIED
OTHER
```

### Ejemplos

* “Quiero la terraza”.
* “Me interesa el quiosco”.
* “Prefiero un espacio interior”.
* “Quiero hacerlo cerca de la piscina”.

### Regla

La preferencia no confirma disponibilidad ni asignación final.

---

## 12.2 `space_requirement`

### Tipo

```text
string
```

### Ejemplos

* “Necesito pista de baile”.
* “Quiero ceremonia y cena en espacios diferentes”.
* “Debe ser cubierto por si llueve”.

---

## 12.3 `space_confirmed`

### Tipo

```text
boolean
```

### Autoridad

Solo asesor o backend autorizado.

La IA no podrá establecerlo como verdadero.

---

# 13. Entidades de servicios

## 13.1 `requested_services`

### Tipo

```text
array<ServiceRequest>
```

### Ejemplo

```json
{
  "requested_services": [
    {
      "service_code": "FOOD",
      "status": "REQUESTED"
    },
    {
      "service_code": "DECORATION",
      "status": "REQUESTED"
    },
    {
      "service_code": "DJ",
      "status": "PENDING_CONFIRMATION"
    }
  ]
}
```

---

## 13.2 Códigos iniciales de servicios

```text
VENUE
FURNITURE
TABLEWARE
GLASSWARE
WAITSTAFF
FOOD
BRUNCH
DINNER
SNACKS
NON_ALCOHOLIC_BEVERAGES
COCKTAILS
ALCOHOL_SERVICE
DECORATION
FLORAL_DESIGN
PHOTOGRAPHY
VIDEO
DJ
LIVE_MUSIC
VIOLINIST
SAXOPHONIST
SOUND
SCREEN
MICROPHONE
LIGHTING
CAKE
DESSERT_TABLE
MAKEUP
HAIR_STYLING
ACCOMMODATION
POOL
WELCOME_MIRROR
GIANT_LETTERS
SHOT_CART
ADDITIONAL_FURNITURE
CHILDREN_ENTERTAINMENT
SECURITY
OTHER
```

---

## 13.3 `service_status`

### Valores

```text
REQUESTED
AVAILABLE
PENDING_CONFIRMATION
UNAVAILABLE
INCLUDED
ADDITIONAL_COST
CLIENT_PROVIDED
CANCELLED
```

### Regla

La IA solo podrá asignar inicialmente:

```text
REQUESTED
CLIENT_PROVIDED
PENDING_CONFIRMATION
CANCELLED
```

Los demás estados requieren catálogo, backend o asesor.

---

## 13.4 `client_provided_services`

### Ejemplos

* “Ya tengo fotógrafo”.
* “El DJ lo llevo yo”.
* “La torta la hace mi hermana”.

Resultado:

```json
{
  "service_code": "PHOTOGRAPHY",
  "status": "CLIENT_PROVIDED"
}
```

---

## 13.5 `decoration_style`

### Ejemplos

* boho;
* clásica;
* romántica;
* natural;
* tropical;
* minimalista;
* elegante;
* campestre.

### Tipo

```text
string or controlled tags
```

---

## 13.6 `color_preferences`

### Tipo

```text
array<string>
```

### Ejemplo

> “Quiero azul, blanco y dorado”.

---

## 13.7 `menu_preferences`

### Ejemplos

* pollo;
* salmón;
* cerdo;
* menú vegetariano;
* brunch;
* pasabocas;
* cena formal.

### Regla

Una preferencia no confirma menú ni precio.

---

## 13.8 `dietary_requirements`

### Ejemplos

* alergia a frutos secos;
* vegetariano;
* sin gluten;
* sin lactosa.

### Sensibilidad

```text
SENSITIVE_OPERATIONAL
```

### Regla

No solicitar diagnósticos médicos adicionales.

---

## 13.9 `external_food`

### Tipo

```text
boolean
```

---

## 13.10 `external_beverages`

### Tipo

```text
boolean
```

---

## 13.11 `alcohol_expected`

### Tipo

```text
boolean
```

### Ejemplos

* “Vamos a llevar whisky”.
* “Queremos barra”.
* “No vamos a ofrecer licor”.

---

## 13.12 `external_suppliers`

### Tipo

```text
array<ExternalSupplier>
```

### Campos posibles

```json
{
  "supplier_type": "PHOTOGRAPHER",
  "supplier_name": null,
  "client_provided": true,
  "notes": "Pendiente coordinar ingreso"
}
```

No es obligatorio recopilar el nombre del proveedor en la primera conversación.

---

# 14. Entidades de mascotas y piscina

## 14.1 `pet_attendance`

### Tipo

```text
boolean
```

### Ejemplos

* “Voy con mi perro”.
* “No habrá mascotas”.

---

## 14.2 `pet_count`

### Tipo

```text
integer
```

---

## 14.3 `pet_type`

### Valores sugeridos

```text
DOG
CAT
OTHER
UNKNOWN
```

---

## 14.4 `pool_use_expected`

### Tipo

```text
boolean
```

### Ejemplos

* “Queremos usar la piscina”.
* “La piscina no se va a utilizar”.

---

## 14.5 `children_pool_use`

### Tipo

```text
boolean
```

### Uso

Información operacional de seguridad.

---

# 15. Entidades de alojamiento

## 15.1 `accommodation_required`

### Tipo

```text
boolean
```

---

## 15.2 `accommodation_guest_count`

### Tipo

```text
integer
```

---

## 15.3 `accommodation_nights`

### Tipo

```text
integer
```

---

## 15.4 `preferred_accommodation`

### Valores iniciales

```text
SUITE_OASIS
OTHER
UNSPECIFIED
```

### Regla

Registrar interés no confirma disponibilidad.

---

# 16. Entidades de solicitud de cotización

## 16.1 `quote_request_status`

### Valores

```text
DRAFT
READY
ASSIGNED
IN_PROGRESS
COMPLETED
CANCELLED
EXPIRED
```

### Fuente

Principalmente backend.

La IA no deberá determinar estados finales libremente.

---

## 16.2 `quote_missing_fields`

### Tipo

```text
array<string>
```

### Fuente

```text
SYSTEM_CALCULATION
```

### Campos mínimos evaluados

```text
full_name
phone_number
event_type
date_resolved
guest_count OR guest_count_range
```

Donde `date_resolved` significa fecha exacta, mes aproximado o tipo `FLEXIBLE`/`UNKNOWN` declarado explícitamente por el cliente.

---

## 16.3 `quote_change_requested`

### Tipo

```text
boolean
```

### Ejemplo

> “Quiero otra cotización sin DJ”.

---

## 16.4 `quote_status_query`

### Tipo conceptual

Indica que el cliente pregunta por el avance de una propuesta.

No representa un campo persistente principal; activa una consulta al backend.

---

## 16.5 `quote_version_reference`

### Tipo

```text
integer or identifier
```

### Ejemplos

* “La primera cotización”.
* “La versión que me enviaron ayer”.
* “La propuesta de 50 personas”.

---

# 17. Entidades de visitas

## 17.1 `preferred_visit_date`

### Tipo

```text
date
```

### Reglas

* confirmar fechas relativas;
* validar martes a sábado;
* no festivos;
* mínimo tres días.

---

## 17.2 `preferred_visit_time`

### Valores permitidos

```text
08:00
09:00
10:00
11:00
```

### Regla

Un valor fuera del catálogo puede registrarse como preferencia, pero no ofrecerse como horario válido.

---

## 17.3 `visit_attendee_count`

### Tipo

```text
integer
```

### Validación

```text
1 <= visit_attendee_count <= 3
```

Si es mayor:

```text
visit_exception_requested = true
```

cuando el cliente insista.

---

## 17.4 `visit_reason`

### Valores sugeridos

```text
KNOW_VENUE
WEDDING_INQUIRY
SOCIAL_EVENT_INQUIRY
CORPORATE_EVENT_INQUIRY
QUOTE_REVIEW
RESERVATION_FOLLOW_UP
OTHER
```

---

## 17.5 `appointment_reference`

### Definición

Identificador o conjunto de datos que permite localizar una visita.

Puede obtenerse mediante:

* ID interno;
* fecha y hora;
* cliente;
* última cita activa.

---

## 17.6 `new_visit_date`

Usada para reprogramación.

---

## 17.7 `new_visit_time`

Usada para reprogramación.

---

## 17.8 `visit_cancellation_reason`

### Tipo

```text
string
```

### Regla

Opcional.

---

## 17.9 `visit_confirmation`

### Valores

```text
CONFIRMED
REJECTED
PENDING
```

### Fuente

Respuesta contextual del cliente.

---

# 18. Entidades de pagos

## 18.1 `payment_method`

### Valores

```text
BANK_TRANSFER
CASH
CARD
NEQUI
DAVIPLATA
PAYMENT_LINK
OTHER_AUTHORIZED
UNKNOWN
```

---

## 18.2 `reported_payment_amount`

### Tipo

```text
decimal
```

### Regla

No equivale al monto confirmado.

---

## 18.3 `expected_payment_amount`

### Fuente

```text
SYSTEM_CALCULATION
```

No deberá ser inferido por IA.

---

## 18.4 `payment_reference`

### Tipo

```text
string
```

### Ejemplos

* número de comprobante;
* últimos dígitos autorizados de referencia;
* código de transacción.

### Restricción

No almacenar:

* PIN;
* CVV;
* contraseña;
* OTP;
* tarjeta completa.

---

## 18.5 `payment_proof_attachment`

### Tipo

```text
attachment_reference
```

### Clasificación

```text
PAYMENT_PROOF
```

---

## 18.6 `payment_status`

### Valores

```text
PAYMENT_PENDING
PAYMENT_REVIEW
PAYMENT_CONFIRMED
PAYMENT_REJECTED
PAYMENT_CANCELLED
```

### Autoridad

La IA solo podrá solicitar que el backend establezca:

```text
PAYMENT_REVIEW
```

cuando se recibe información.

Solo un asesor podrá confirmar o rechazar.

---

## 18.7 `payment_problem_type`

### Valores sugeridos

```text
PAYMENT_NOT_FOUND
DUPLICATE_CHARGE
PAYMENT_LINK_FAILURE
WRONG_AMOUNT
PAYMENT_REJECTED
PAYMENT_ASSIGNED_TO_WRONG_EVENT
OTHER
```

### Prioridad

`URGENT` o `CRITICAL`, según el caso.

---

# 19. Entidades de reserva

## 19.1 `reservation_reference`

Identificador de la reserva o evento reservado.

---

## 19.2 `deposit_percentage`

### Valor inicial

```text
50
```

### Fuente

Configuración.

La IA no deberá extraer otro porcentaje como regla válida sin tratarlo como una consulta o excepción.

---

## 19.3 `reservation_status`

### Valores

```text
INQUIRY
QUOTED
PAYMENT_PENDING
PAYMENT_REVIEW
RESERVED
CANCEL_REQUESTED
CANCELLED
COMPLETED
```

### Autoridad

Backend y asesores.

---

## 19.4 `requested_date_hold`

### Tipo

```text
boolean
```

### Ejemplo

> “¿Me pueden guardar la fecha mientras decido?”

### Regla

No crea bloqueo real.

---

## 19.5 `reservation_confirmation_requested`

### Tipo

```text
boolean
```

### Ejemplo

> “¿Ya quedó reservada?”

Activa consulta al backend.

---

# 20. Entidades de cancelación de evento

## 20.1 `event_cancellation_requested`

### Tipo

```text
boolean
```

---

## 20.2 `event_cancellation_reason`

### Tipo

```text
string
```

### Ejemplos

* emergencia familiar;
* cambio de planes;
* presupuesto;
* cambio de ciudad;
* motivo no informado.

### Regla

Opcional para iniciar el proceso.

---

## 20.3 `refund_requested`

### Tipo

```text
boolean
```

### Ejemplos

* “Quiero que me devuelvan el dinero”.
* “Necesito el reembolso”.

---

## 20.4 `days_before_event`

### Tipo

```text
integer
```

### Fuente

Backend.

No debe calcularse mediante texto libre de IA si ya existe fecha registrada.

### Regla

```text
days_before_event < 30
→ no devolución según política general
```

Las excepciones son humanas.

---

## 20.5 `reschedule_event_requested`

### Tipo

```text
boolean
```

### Ejemplo

> “No quiero cancelar, quiero cambiar la fecha”.

Siempre requiere atención humana si el evento está reservado.

---

# 21. Entidades de atención humana

## 21.1 `human_requested`

### Tipo

```text
boolean
```

---

## 21.2 `requested_agent`

### Tipo

```text
string or user_reference
```

### Ejemplos

* Leandro;
* ventas;
* un asesor;
* la persona que me atendió.

### Regla

La solicitud de una persona específica no garantiza disponibilidad.

---

## 21.3 `handoff_reason`

### Valores

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
OTHER
```

---

## 21.4 `handoff_priority`

### Valores

```text
NORMAL
HIGH
URGENT
CRITICAL
```

---

## 21.5 `assigned_agent`

### Autoridad

Sistema o asesor.

La IA no asignará directamente a una persona.

---

# 22. Entidades de negociación

## 22.1 `discount_requested`

### Tipo

```text
boolean
```

### Ejemplos

* “¿Me hacen descuento?”
* “¿Pueden bajar el precio?”
* “¿Qué rebaja me dan?”

### Acción

Handoff comercial.

---

## 22.2 `requested_discount_amount`

### Tipo

```text
decimal or percentage
```

### Ejemplos

* “¿Me descuentan 500.000?”
* “¿Me hacen un 10 %?”

Registrar la solicitud no implica aprobación.

---

## 22.3 `special_payment_terms_requested`

### Tipo

```text
boolean
```

### Ejemplos

* pago por cuotas;
* pago después del evento;
* crédito;
* forma de pago especial.

---

## 22.4 `collaboration_requested`

### Tipo

```text
boolean
```

### Ejemplos

* intercambio;
* patrocinio;
* colaboración con creador;
* canje.

### Responsable

Manager Leandro.

---

# 23. Entidades de queja

## 23.1 `complaint_topic`

### Valores sugeridos

```text
LACK_OF_RESPONSE
SERVICE_QUALITY
QUOTE_ERROR
PAYMENT_DELAY
RESERVATION_ERROR
APPOINTMENT_PROBLEM
EVENT_EXECUTION
STAFF_BEHAVIOR
SUPPLIER_PROBLEM
FOOD_QUALITY
PROPERTY_DAMAGE
OTHER
```

---

## 23.2 `complaint_description`

### Tipo

```text
string
```

Debe conservar el contenido del cliente sin reinterpretarlo de forma acusatoria.

---

## 23.3 `requested_resolution`

### Ejemplos

* devolución;
* explicación;
* llamada;
* corrección;
* compensación;
* respuesta formal.

### Regla

Registrar la solicitud no significa aceptarla.

---

## 23.4 `complaint_severity`

### Valores

```text
NORMAL
HIGH
URGENT
CRITICAL
```

### Fuente

IA validada y reglas.

---

# 24. Entidades de urgencia

## 24.1 `emergency_type`

### Valores

```text
MEDICAL_EMERGENCY
SECURITY_INCIDENT
FOOD_SAFETY_INCIDENT
CLIENT_ON_SITE_UNATTENDED
ACCESS_PROBLEM
DOUBLE_BOOKING
CRITICAL_PAYMENT_ERROR
CRITICAL_RESERVATION_ERROR
EVENT_WITHIN_72_HOURS
PROPERTY_DAMAGE
LOST_PROPERTY
SUPPLIER_ACCESS_PROBLEM
OTHER
```

---

## 24.2 `emergency_location`

### Tipo

```text
string or location
```

### Ejemplos

* entrada;
* piscina;
* terraza;
* cocina;
* dirección externa.

---

## 24.3 `people_affected`

### Tipo

```text
integer or description
```

---

## 24.4 `immediate_danger`

### Tipo

```text
boolean
```

### Regla

Si es verdadero, el bot deberá recomendar contacto inmediato con personal presente o servicios de emergencia.

---

## 24.5 `event_within_72_hours`

### Tipo

```text
boolean
```

### Fuente

Backend, calculado desde la fecha.

---

# 25. Entidades de accesibilidad y seguridad

## 25.1 `accessibility_requirements`

### Ejemplos

* acceso para silla de ruedas;
* adulto mayor con movilidad reducida;
* necesidad de ingreso cercano;
* espacio para coche de bebé.

### Sensibilidad

```text
SENSITIVE_OPERATIONAL
```

### Regla

Solo se solicitará información necesaria.

---

## 25.2 `safety_requirements`

### Ejemplos

* supervisión de menores;
* cuidado alrededor de piscina;
* ingreso de equipos;
* instalación eléctrica especial.

---

# 26. Entidades de archivos

## 26.1 `attachment_type`

### Valores

```text
PAYMENT_PROOF
INSPIRATION_IMAGE
QUOTE_DOCUMENT
CONTRACT_DOCUMENT
GENERAL_DOCUMENT
AUDIO_MESSAGE
VIDEO_REFERENCE
LOCATION
OTHER
```

---

## 26.2 `attachment_context`

### Definición

Describe por qué se envió el archivo.

Ejemplos:

* referencia de decoración;
* comprobante;
* propuesta anterior;
* contrato;
* menú.

---

## 26.3 `attachment_requires_human_review`

### Tipo

```text
boolean
```

Se marcará verdadero para:

* comprobantes;
* contratos;
* reclamaciones;
* documentos no soportados;
* referencias complejas.

---

# 27. Entidades de contexto conversacional

## 27.1 `confirmation_response`

### Valores

```text
YES
NO
UNCLEAR
```

### Ejemplos positivos para `YES`

* sí;
* confirmo;
* correcto;
* de acuerdo;
* agéndala;
* hazlo.

Debe interpretarse según `pending_action`.

---

## 27.2 `selected_option_index`

### Tipo

```text
integer
```

### Ejemplo

> “La segunda”.

Requiere opciones previas.

---

## 27.3 `selected_option_value`

### Ejemplo

> “La de las 9”.

Valor:

```text
09:00
```

---

## 27.4 `pending_action`

### Valores sugeridos

```text
COLLECT_EVENT_DATA
CONFIRM_QUOTE_REQUEST
SELECT_VISIT_DATE
SELECT_VISIT_TIME
CONFIRM_APPOINTMENT
CONFIRM_RESCHEDULE
CONFIRM_VISIT_CANCELLATION
CONFIRM_EVENT_CANCELLATION
WAIT_FOR_HUMAN
WAIT_FOR_PAYMENT_REVIEW
OTHER
```

---

## 27.5 `conversation_reference`

Permite interpretar expresiones como:

* “lo anterior”;
* “esa propuesta”;
* “el evento”;
* “la cita”;
* “la primera opción”.

---

# 28. Reglas de normalización de fechas

## 28.1 Fechas absolutas

Formato:

```text
YYYY-MM-DD
```

## 28.2 Horas

Formato:

```text
HH:mm
```

## 28.3 Zona horaria

```text
America/Bogota
```

## 28.4 Expresiones relativas

Deberán resolverse usando la fecha actual del sistema.

Ejemplos:

* hoy;
* mañana;
* pasado mañana;
* este sábado;
* próximo sábado;
* dentro de tres días;
* la otra semana;
* a finales de mes.

## 28.5 Confirmación

Siempre deberá confirmarse una fecha relativa antes de:

* crear una visita;
* reprogramar;
* cancelar una operación específica;
* crear una cotización con fecha exacta;
* modificar un evento reservado.

## 28.6 Fechas incompletas

### Día y mes sin año

Podrá inferirse el siguiente año válido, pero deberá confirmarse.

### Mes sin día

Guardar `event_month`.

### Día de la semana sin fecha

Resolver y confirmar.

---

# 29. Reglas de normalización monetaria

## 29.1 Moneda predeterminada

```text
COP
```

cuando el cliente se encuentre en el contexto local y no indique otra moneda.

## 29.2 Expresiones coloquiales

| Expresión            |    Valor |
| -------------------- | -------: |
| un millón            |  1000000 |
| millón y medio       |  1500000 |
| dos millones y medio |  2500000 |
| cuatro palos         |  4000000 |
| diez millones        | 10000000 |
| 150 mil              |   150000 |

## 29.3 Ambigüedad

> “Tengo 150”.

No deberá asumirse si significa:

* $150.000;
* $150 por persona;
* USD 150;
* otra cantidad.

Se deberá pedir aclaración.

## 29.4 Presupuesto total frente a individual

Debe diferenciarse:

```text
budget_is_per_person
```

---

# 30. Reglas de fusión de entidades

Cuando la misma entidad aparece varias veces:

## 30.1 Mismo valor

Se refuerza la confianza y puede marcarse como confirmado.

## 30.2 Valor diferente sin marcador de corrección

Se detecta conflicto.

Ejemplo:

* mensaje anterior: 30 personas;
* mensaje actual: “Vamos 40”.

El sistema deberá determinar si es corrección y confirmar cuando sea necesario.

## 30.3 Corrección explícita

Expresiones:

* no son;
* finalmente;
* cambiamos;
* realmente;
* mejor;
* ya no;
* ahora serán.

El valor nuevo reemplaza al anterior después de validación.

## 30.4 Datos de asesor

Una confirmación autorizada de asesor podrá prevalecer en campos restringidos.

## 30.5 Datos críticos

Nunca se fusionarán automáticamente:

* pagos;
* reservas;
* descuentos;
* devoluciones;
* fechas reservadas;
* condiciones contractuales.

---

# 31. Matriz de entidades por intención

| Intención                 | Entidades obligatorias o principales                                                         |
| ------------------------- | -------------------------------------------------------------------------------------------- |
| `GREETING`                | `full_name`, opcional                                                                        |
| `GENERAL_INFORMATION`     | `information_category`, `guest_count`, `preferred_space`, `service_code`                     |
| `EVENT_INFORMATION`       | `event_type`, `event_date`, `guest_count`, `requested_services`                              |
| `QUOTE_REQUEST`           | `full_name`, `event_type`, `event_date/event_month`, `guest_count`                           |
| `MODIFY_EVENT_DATA`       | `target_entity`, `new_value`, `previous_value`                                               |
| `SCHEDULE_VISIT`          | `preferred_visit_date`, `preferred_visit_time`, `visit_attendee_count`, `visit_reason`       |
| `RESCHEDULE_VISIT`        | `appointment_reference`, `new_visit_date`, `new_visit_time`                                  |
| `CANCEL_VISIT`            | `appointment_reference`, `visit_cancellation_reason`                                         |
| `PAYMENT_MESSAGE`         | `payment_method`, `reported_payment_amount`, `payment_reference`, `payment_proof_attachment` |
| `RESERVATION_INFORMATION` | `reservation_reference`, `requested_date_hold`                                               |
| `EVENT_CANCELLATION`      | `reservation_reference`, `event_cancellation_reason`, `refund_requested`                     |
| `HUMAN_REQUEST`           | `requested_agent`, `handoff_reason`                                                          |
| `COMPLAINT`               | `complaint_topic`, `complaint_description`, `requested_resolution`                           |
| `EMERGENCY`               | `emergency_type`, `emergency_location`, `immediate_danger`                                   |
| `FAREWELL`                | Ninguna obligatoria                                                                          |
| `UNKNOWN`                 | Ninguna confirmada                                                                           |

---

# 32. Matriz de confirmación obligatoria

| Entidad                |            Confirmación obligatoria |
| ---------------------- | ----------------------------------: |
| `full_name`            |                 Cuando fue inferido |
| `event_type`           |            Cuando existe ambigüedad |
| `event_date`           |        Si fue relativa o incompleta |
| `guest_count`          | Cuando existe rango o contradicción |
| `estimated_budget`     |           Si es coloquial o ambiguo |
| `preferred_visit_date` |                Sí, antes de agendar |
| `preferred_visit_time` |                Sí, antes de agendar |
| `visit_attendee_count` |                Sí, antes de agendar |
| `new_visit_date`       |                                  Sí |
| `new_visit_time`       |                                  Sí |
| `visit_cancellation`   |                                  Sí |
| `event_cancellation`   |                                  Sí |
| `payment_status`       |                   Validación humana |
| `reservation_status`   |                   Validación humana |
| `discount`             |                   Aprobación humana |
| `refund_decision`      |                   Aprobación humana |
| `space_confirmed`      |                 Confirmación humana |
| `service_included`     |                   Catálogo o asesor |

---

# 33. Matriz de autoridad de actualización

| Entidad               | IA puede proponer | Backend puede calcular | Asesor puede confirmar |
| --------------------- | ----------------: | ---------------------: | ---------------------: |
| Nombre                |                Sí |                     No |                     Sí |
| Tipo de evento        |                Sí |                     No |                     Sí |
| Fecha                 |                Sí |                Validar |                     Sí |
| Invitados             |                Sí |       Sumar categorías |                     Sí |
| Presupuesto           |                Sí |             Clasificar |                     Sí |
| Servicios solicitados |                Sí |     Consultar catálogo |                     Sí |
| Disponibilidad        |                No |                     Sí |                     Sí |
| Cita                  |                No |                     Sí |                     Sí |
| Precio                |                No |                 Futuro |                     Sí |
| Descuento             |                No |                Validar |          Sí autorizado |
| Pago                  |     Solo detectar |                     No |                     Sí |
| Reserva               |                No |    Validar invariantes |                     Sí |
| Devolución            |                No |                     No |          Sí autorizado |
| Prioridad de urgencia |                Sí |         Validar reglas |                     Sí |

---

# 34. Contrato JSON recomendado de extracción

```json
{
  "entities": [
    {
      "name": "event_type",
      "raw_value": "boda",
      "normalized_value": "WEDDING",
      "data_type": "enum",
      "quality_status": "PROVIDED",
      "confidence": 0.98,
      "needs_confirmation": false,
      "validation_errors": []
    },
    {
      "name": "guest_count",
      "raw_value": "unas 45 personas",
      "normalized_value": 45,
      "data_type": "integer",
      "quality_status": "PROVIDED",
      "confidence": 0.94,
      "needs_confirmation": false,
      "validation_errors": [],
      "metadata": {
        "is_estimated": true
      }
    }
  ],
  "corrections": [],
  "conflicts": [],
  "missing_required_entities": [
    "event_date"
  ],
  "requires_human_review": false
}
```

---

# 35. Contrato de corrección

Cuando se detecte una corrección:

```json
{
  "corrections": [
    {
      "entity_name": "guest_count",
      "previous_value": 30,
      "new_value": 55,
      "raw_expression": "ya no son 30, finalmente serán 55",
      "confidence": 0.99,
      "needs_confirmation": false,
      "impact_flags": [
        "QUOTE_REVIEW_REQUIRED"
      ]
    }
  ]
}
```

Si el nuevo valor supera 60:

```json
{
  "impact_flags": [
    "QUOTE_REVIEW_REQUIRED",
    "CAPACITY_REVIEW_REQUIRED",
    "HUMAN_HANDOFF_REQUIRED"
  ]
}
```

---

# 36. Entidades inválidas

Una entidad se marcará `INVALID` cuando:

* fecha imposible;
* valor numérico negativo;
* correo incorrecto;
* cantidad de asistentes de visita igual a cero;
* hora no interpretable;
* rango invertido;
* moneda desconocida sin posibilidad de aclaración;
* categoría fuera del catálogo;
* archivo inseguro;
* dato contradictorio con una regla crítica.

Ejemplo:

```json
{
  "name": "event_date",
  "raw_value": "31 de febrero",
  "normalized_value": null,
  "quality_status": "INVALID",
  "validation_errors": [
    "INVALID_CALENDAR_DATE"
  ]
}
```

---

# 37. Códigos de error de validación

```text
REQUIRED_VALUE_MISSING
INVALID_FORMAT
INVALID_DATE
DATE_IN_PAST
AMBIGUOUS_DATE
INVALID_TIME
TIME_OUTSIDE_ALLOWED_RANGE
INVALID_NUMBER
NEGATIVE_VALUE
RANGE_INVERTED
CAPACITY_REVIEW_REQUIRED
VISIT_ATTENDEE_LIMIT_EXCEEDED
UNSUPPORTED_ENUM_VALUE
CONFLICT_WITH_CONFIRMED_DATA
HUMAN_CONFIRMATION_REQUIRED
SENSITIVE_DATA_NOT_ALLOWED
INVALID_ATTACHMENT
```

---

# 38. Reglas de privacidad

## 38.1 Datos prohibidos

No se extraerán ni almacenarán como entidades comerciales:

* contraseñas;
* PIN;
* CVV;
* OTP;
* número completo de tarjeta;
* claves bancarias;
* diagnósticos médicos completos;
* orientación política;
* religión;
* origen étnico;
* información íntima innecesaria;
* documentos sin finalidad aprobada.

## 38.2 Datos sensibles accidentales

Cuando el cliente envíe datos prohibidos:

1. No se reutilizarán.
2. Se minimizarán en logs.
3. Se advertirá al cliente.
4. Se conservarán solo si técnicamente es inevitable y con acceso restringido.
5. Se aplicará la política de eliminación correspondiente.

---

# 39. Métricas de entidades

El sistema deberá medir:

* entidades extraídas por tipo;
* precisión;
* correcciones humanas;
* campos faltantes;
* entidades ambiguas;
* entidades inválidas;
* confianza media;
* frecuencia de confirmación;
* contradicciones;
* datos preguntados repetidamente;
* errores de normalización;
* campos que causan handoff.

---

# 40. Dataset de evaluación

Para cada entidad principal se recomienda crear:

* 20 expresiones directas;
* 10 expresiones informales;
* 10 expresiones con errores ortográficos;
* 10 expresiones ambiguas;
* 5 contradicciones;
* 5 correcciones;
* 5 casos negativos.

## Entidades críticas con mayor cobertura

```text
event_date
guest_count
estimated_budget
preferred_visit_date
preferred_visit_time
payment_status
reservation_status
event_cancellation_requested
emergency_type
```

Se recomienda mínimo 50 ejemplos para cada entidad crítica.

---

# 41. Casos de prueba mínimos

## Entidad múltiple

Mensaje:

> Soy Carolina, quiero una boda para 50 personas el 19 de diciembre y tengo 10 millones.

Debe extraer cinco datos sin repetir preguntas.

## Fecha aproximada

Mensaje:

> La boda sería en diciembre.

Debe guardar mes y no día.

## Rango

Mensaje:

> Seremos entre 40 y 50.

Debe guardar rango.

## Corrección

Mensaje:

> Ya no son 40, serán 60.

Debe generar corrección.

## Presupuesto coloquial

Mensaje:

> Tengo unos ocho palos.

Debe normalizar a 8.000.000 COP, con confirmación si el contexto lo requiere.

## Servicio del cliente

Mensaje:

> El fotógrafo lo llevo yo.

Debe marcar `CLIENT_PROVIDED`.

## Fecha relativa

Mensaje:

> Quiero ir el próximo sábado.

Debe resolver fecha y pedir confirmación.

## Pago

Mensaje:

> Ya transferí el 50 %.

Debe detectar pago informado, pero no confirmarlo.

## Cancelación de visita

Mensaje:

> No voy a poder ir a la cita.

Debe utilizar el contexto para distinguir visita de evento.

## Cancelación de evento

Mensaje:

> Ya no vamos a hacer la boda.

Debe detectar cancelación de evento y escalar.

---

# 42. Criterios de aceptación

El catálogo de entidades se considerará correctamente implementado cuando:

1. Solo se devuelvan nombres de entidad autorizados.
2. Los valores normalizados cumplan los tipos definidos.
3. El valor original se conserve.
4. Los datos inferidos se diferencien de los proporcionados.
5. Las fechas relativas se confirmen.
6. Los meses no se conviertan en fechas exactas inventadas.
7. Los rangos se mantengan como rangos.
8. Las correcciones conserven el valor anterior.
9. Los invitados menores se sumen a la capacidad.
10. Los presupuestos coloquiales se normalicen correctamente.
11. Se diferencie presupuesto total y por persona.
12. Los servicios solicitados no se marquen como incluidos.
13. La disponibilidad no sea una entidad inferida por IA.
14. Los pagos no sean confirmados por IA.
15. Las reservas no sean confirmadas por IA.
16. Los descuentos y devoluciones requieran autorización humana.
17. Los datos prohibidos no se almacenen como entidades normales.
18. Los conflictos sean reportados.
19. Las entidades críticas tengan pruebas.
20. El backend valide la salida antes de persistirla.

---

# 43. Definición de terminado

La implementación del catálogo estará terminada cuando:

* exista un esquema JSON de extracción;
* existan enumeraciones;
* existan validadores por tipo;
* exista normalización de fechas;
* exista normalización monetaria;
* exista manejo de rangos;
* exista detección de correcciones;
* exista detección de conflictos;
* exista registro de calidad;
* exista confirmación contextual;
* existan pruebas unitarias;
* existan pruebas conversacionales;
* existan métricas;
* exista trazabilidad entre mensaje y entidad;
* las entidades puedan persistirse en el modelo de datos;
* las operaciones críticas estén protegidas.

---

# 44. Aprobación

Este documento queda listo como fuente oficial para:

* prompts de extracción;
* esquemas JSON;
* validadores;
* máquina de estados;
* servicios del dominio;
* persistencia;
* pruebas conversacionales;
* pruebas de normalización;
* seguimiento de calidad;
* integración con OpenRouter.

Su aprobación implica que:

* las entidades principales están definidas;
* los formatos normalizados están establecidos;
* las reglas de confirmación están delimitadas;
* las correcciones y contradicciones están contempladas;
* los datos sensibles tienen restricciones;
* el MVP puede convertir mensajes de WhatsApp en información estructurada;
* la futura cotización automática podrá consumir estos datos sin rediseñar la conversación.
