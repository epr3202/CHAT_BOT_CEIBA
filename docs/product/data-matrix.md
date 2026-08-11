# Matriz de datos del producto

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/product/data-matrix.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Zona horaria oficial:** `America/Bogota`

**Documentos relacionados:**

* `/docs/product/vision.md`
* `/docs/product/scope.md`
* `/docs/product/business-rules.md`
* `/docs/product/use-cases.md`

---

# 1. Propósito

Este documento define la estructura funcional de los datos utilizados por el MVP del Asistente Conversacional de La Ceiba Club House.

La matriz establece:

* qué información debe almacenar el sistema;
* qué datos son obligatorios;
* qué datos son opcionales;
* cuáles se obtienen automáticamente;
* qué información puede inferir la IA;
* qué datos requieren confirmación;
* qué roles pueden modificarlos;
* qué validaciones deben aplicarse;
* qué información es sensible;
* cuánto tiempo debe conservarse;
* en qué casos de uso interviene cada campo;
* qué datos no debe solicitar el bot.

Este documento es funcional y no sustituye el modelo físico de base de datos. Sus definiciones deberán convertirse posteriormente en:

* entidades;
* tablas;
* campos;
* enumeraciones;
* índices;
* restricciones;
* políticas de acceso;
* migraciones;
* contratos de API;
* esquemas de validación.

---

# 2. Principios de gestión de datos

## DM-GEN-001 — Minimización

El sistema solo deberá solicitar y almacenar datos necesarios para:

* responder consultas;
* registrar clientes;
* gestionar eventos;
* preparar cotizaciones;
* agendar visitas;
* validar pagos;
* confirmar reservas;
* atender situaciones operativas.

No deberán recopilarse datos personales sin una finalidad concreta.

---

## DM-GEN-002 — Separación por dominio

Los datos deberán dividirse en entidades independientes.

No se almacenará toda la información dentro de:

* una conversación;
* un único documento JSON;
* un resumen de IA;
* un campo de observaciones.

La estructura mínima deberá distinguir:

```text
Cliente
Lead
Evento
Conversación
Mensaje
Solicitud de cotización
Cotización
Visita
Reserva
Pago
Handoff
Base de conocimiento
Ejecución de IA
Auditoría
Configuración
```

---

## DM-GEN-003 — Fuente de verdad

Cada dominio tendrá una fuente de verdad definida:

| Dominio                | Fuente de verdad                                 |
| ---------------------- | ------------------------------------------------ |
| Cliente                | Registro `Customer`                              |
| Oportunidad comercial  | Registro `Lead`                                  |
| Datos del evento       | Registro `Event`                                 |
| Mensajes               | Registro `Message`                               |
| Estado conversacional  | Registro `Conversation`                          |
| Agenda                 | Registro `Appointment` y proveedor de calendario |
| Solicitud comercial    | Registro `QuoteRequest`                          |
| Cotización             | Registro `Quote` y sus versiones                 |
| Pago                   | Registro `Payment`, validado por asesor          |
| Reserva                | Registro `Reservation`                           |
| Respuestas autorizadas | Registro `KnowledgeEntry`                        |
| Historial de cambios   | Registro `AuditEvent`                            |

Los resúmenes creados por inteligencia artificial serán información auxiliar.

---

## DM-GEN-004 — Inmutabilidad

No deberán sobrescribirse:

* mensajes;
* eventos de auditoría;
* cotizaciones enviadas;
* comprobantes;
* versiones de respuestas aprobadas;
* cambios históricos de citas.

Cuando un dato cambie, se conservará su trazabilidad.

---

## DM-GEN-005 — Identificadores internos

Las entidades principales deberán utilizar identificadores internos no dependientes del proveedor.

Formato recomendado:

```text
UUID
```

Los identificadores de WhatsApp, calendario, archivos y otros proveedores se almacenarán como referencias externas.

---

## DM-GEN-006 — Fechas y horas

Las fechas y horas operativas se interpretarán en:

```text
America/Bogota
```

Los valores técnicos podrán almacenarse en UTC, pero deberán conservar la zona horaria o contexto necesario para mostrarlos correctamente.

---

# 3. Clasificación de obligatoriedad

## 3.1 Obligatorio global

El dato debe existir para crear la entidad.

Ejemplo:

* identificador;
* fecha de creación;
* cliente asociado.

## 3.2 Obligatorio por flujo

El dato se vuelve obligatorio únicamente para completar una acción.

Ejemplo:

* el nombre no es obligatorio para responder una FAQ;
* el nombre sí es obligatorio para agendar una visita.

## 3.3 Preferible

El bot intentará obtenerlo, pero su ausencia no bloqueará la operación.

Ejemplo:

* presupuesto para solicitar una cotización.

## 3.4 Opcional

Solo se solicitará cuando sea relevante para el caso.

## 3.5 Automático

Se obtiene desde:

* canal;
* sistema;
* integración;
* regla de negocio.

## 3.6 Calculado

Se deriva de otros datos y no debe capturarse manualmente sin autorización.

## 3.7 Restringido

Solo puede ser creado o modificado por roles autorizados.

## 3.8 Prohibido

No debe solicitarse ni almacenarse dentro del flujo normal.

---

# 4. Estados de calidad del dato

Cada dato comercial importante podrá tener un estado de calidad:

```text
UNKNOWN
INFERRED
PROVIDED
PENDING_CONFIRMATION
CONFIRMED
CORRECTED
INVALID
```

## 4.1 UNKNOWN

El sistema no conoce el valor.

## 4.2 INFERRED

La IA dedujo el valor, pero el cliente no lo declaró explícitamente.

Ejemplo:

> “Quiero celebrar mis 30 años”.

El sistema puede inferir `BIRTHDAY`, pero deberá confirmarlo cuando afecte una operación.

## 4.3 PROVIDED

El cliente proporcionó el dato directamente.

## 4.4 PENDING_CONFIRMATION

El valor es ambiguo o debe verificarse.

Ejemplo:

> “El próximo sábado”.

## 4.5 CONFIRMED

El cliente o un asesor confirmó el valor.

## 4.6 CORRECTED

El valor reemplazó otro previamente registrado.

## 4.7 INVALID

El dato no cumple una regla o formato válido.

---

# 5. Clasificación de sensibilidad

## 5.1 Público

Información de La Ceiba que puede comunicarse libremente.

Ejemplo:

* dirección;
* horarios;
* servicios generales.

## 5.2 Interno

Información operativa que no debe exponerse al cliente.

Ejemplo:

* estado de prioridad;
* notas internas;
* número de inasistencias.

## 5.3 Personal

Información identificable del cliente.

Ejemplo:

* nombre;
* teléfono;
* correo.

## 5.4 Sensible operacional

Información que requiere acceso restringido por su impacto.

Ejemplo:

* alergias;
* requerimientos de accesibilidad;
* comprobantes;
* estado de pago;
* decisiones de devolución.

## 5.5 Técnica

Datos destinados a integración, diagnóstico y auditoría.

Ejemplo:

* identificadores externos;
* latencia;
* código de error;
* tokens.

---

# 6. Entidad Customer

## 6.1 Propósito

Representar a la persona que se comunica con La Ceiba.

Un cliente puede tener:

* varias conversaciones;
* varios leads;
* varios eventos;
* varias visitas;
* varias reservas.

## 6.2 Matriz de campos

| Campo                       | Tipo lógico       | Clasificación              | Fuente          | Sensibilidad | Validación            | Uso                          |
| --------------------------- | ----------------- | -------------------------- | --------------- | ------------ | --------------------- | ---------------------------- |
| `customer_id`               | UUID              | Automático                 | Sistema         | Técnica      | Único y no nulo       | Identificación interna       |
| `full_name`                 | Texto             | Obligatorio por flujo      | Cliente/asesor  | Personal     | 2–120 caracteres      | Cotización, visita y reserva |
| `preferred_name`            | Texto             | Opcional                   | Cliente         | Personal     | 2–60 caracteres       | Personalización              |
| `phone_number`              | Texto normalizado | Automático en WhatsApp     | Canal           | Personal     | Formato internacional | Identidad y contacto         |
| `phone_country_code`        | Texto             | Automático                 | Canal           | Personal     | Código válido         | Normalización                |
| `email`                     | Correo            | Opcional                   | Cliente         | Personal     | Correo válido         | Envío documental             |
| `language`                  | Enum              | Automático/confirmado      | Sistema/cliente | Interno      | Idioma soportado      | Respuesta                    |
| `city`                      | Texto             | Opcional                   | Cliente         | Personal     | 2–100 caracteres      | Contexto                     |
| `preferred_contact_channel` | Enum              | Opcional                   | Cliente         | Personal     | Canal permitido       | Seguimiento                  |
| `preferred_contact_time`    | Rango             | Opcional                   | Cliente         | Personal     | Hora válida           | Seguimiento                  |
| `customer_status`           | Enum              | Automático/restringido     | Sistema/asesor  | Interno      | Estado permitido      | Gestión                      |
| `no_show_count`             | Entero            | Calculado                  | Sistema         | Interno      | Mayor o igual a cero  | Reincidencia                 |
| `internal_notes`            | Texto             | Restringido                | Asesor          | Interno      | Longitud limitada     | Contexto operativo           |
| `consent_status`            | Enum              | Obligatorio según política | Cliente/sistema | Personal     | Estado permitido      | Privacidad                   |
| `created_at`                | Fecha/hora        | Automático                 | Sistema         | Técnica      | No editable           | Auditoría                    |
| `updated_at`                | Fecha/hora        | Automático                 | Sistema         | Técnica      | No editable           | Auditoría                    |
| `last_contact_at`           | Fecha/hora        | Automático                 | Sistema         | Técnica      | No editable           | Seguimiento                  |

## 6.3 Estados permitidos

```text
ACTIVE
INACTIVE
DUPLICATE
RESTRICTED
ARCHIVED
```

## 6.4 Reglas

* El teléfono será el identificador externo inicial.
* El nombre no deberá preguntarse nuevamente si está confirmado.
* No se fusionarán clientes automáticamente.
* Las notas internas no se mostrarán al cliente.
* Un cambio de teléfono no eliminará el teléfono anterior sin auditoría.

---

# 7. Entidad Lead

## 7.1 Propósito

Representar una oportunidad comercial específica.

Ejemplos:

* boda de diciembre;
* cumpleaños familiar;
* evento corporativo;
* cena romántica.

Un cliente podrá tener más de un lead.

## 7.2 Matriz de campos

| Campo                 | Tipo lógico | Clasificación          | Fuente         | Sensibilidad | Validación              | Uso               |
| --------------------- | ----------- | ---------------------- | -------------- | ------------ | ----------------------- | ----------------- |
| `lead_id`             | UUID        | Automático             | Sistema        | Técnica      | Único                   | Identificación    |
| `customer_id`         | UUID        | Obligatorio            | Sistema        | Técnica      | Cliente existente       | Relación          |
| `source_channel`      | Enum        | Automático             | Canal          | Interno      | Canal permitido         | Origen            |
| `source_campaign`     | Texto       | Opcional               | Integración    | Interno      | Valor controlado        | Marketing         |
| `lead_status`         | Enum        | Automático/restringido | Sistema/asesor | Interno      | Estado válido           | Embudo            |
| `assigned_agent_id`   | UUID        | Restringido            | Sistema/asesor | Interno      | Usuario activo          | Responsable       |
| `commercial_priority` | Enum        | Calculado/restringido  | Sistema/asesor | Interno      | Prioridad válida        | Orden de atención |
| `estimated_budget`    | Decimal COP | Preferible             | Cliente        | Personal     | Mayor o igual a cero    | Calificación      |
| `budget_min`          | Decimal COP | Opcional               | Cliente/IA     | Personal     | Mayor o igual a cero    | Rangos            |
| `budget_max`          | Decimal COP | Opcional               | Cliente/IA     | Personal     | Mayor o igual al mínimo | Rangos            |
| `budget_range`        | Enum        | Calculado              | Sistema        | Interno      | Catálogo válido         | Segmentación      |
| `budget_data_status`  | Enum        | Automático             | Sistema        | Interno      | Estado de calidad       | Confianza         |
| `commercial_fit`      | Enum        | Calculado/restringido  | Sistema/asesor | Interno      | Catálogo válido         | Priorización      |
| `next_action`         | Enum/texto  | Opcional               | Sistema/asesor | Interno      | Acción permitida        | Seguimiento       |
| `next_action_at`      | Fecha/hora  | Opcional               | Sistema/asesor | Interno      | Fecha válida            | Recordatorio      |
| `loss_reason`         | Enum/texto  | Obligatorio en `LOST`  | Asesor         | Interno      | Motivo válido           | Análisis          |
| `won_at`              | Fecha/hora  | Automático             | Sistema        | Técnica      | Solo `WON`              | Métricas          |
| `lost_at`             | Fecha/hora  | Automático             | Sistema        | Técnica      | Solo `LOST`             | Métricas          |
| `created_at`          | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable             | Auditoría         |
| `updated_at`          | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable             | Auditoría         |

## 7.3 Estados

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

## 7.4 Rangos de presupuesto

```text
NOT_PROVIDED
BELOW_REFERENCE
REFERENCE_RANGE
PREMIUM
CUSTOM
```

Valor de referencia inicial:

```text
4.000.000 COP
```

## 7.5 Reglas

* Un presupuesto inferior al referente no cierra el lead.
* No debe mostrarse al cliente la clasificación `BELOW_REFERENCE`.
* El estado `WON` deberá estar relacionado con una reserva o decisión comercial válida.
* El motivo de pérdida deberá quedar documentado.

---

# 8. Entidad Event

## 8.1 Propósito

Representar el evento que el cliente desea realizar.

## 8.2 Matriz de campos

| Campo                        | Tipo lógico     | Clasificación                     | Fuente              | Sensibilidad         | Validación              | Uso                   |
| ---------------------------- | --------------- | --------------------------------- | ------------------- | -------------------- | ----------------------- | --------------------- |
| `event_id`                   | UUID            | Automático                        | Sistema             | Técnica              | Único                   | Identificación        |
| `lead_id`                    | UUID            | Obligatorio                       | Sistema             | Técnica              | Lead existente          | Relación              |
| `event_type`                 | Enum            | Obligatorio para cotizar          | Cliente/IA validada | Interno              | Catálogo permitido      | Clasificación         |
| `event_type_other`           | Texto           | Obligatorio si `OTHER`            | Cliente             | Personal             | 3–150 caracteres        | Descripción           |
| `event_date`                 | Fecha           | Obligatorio o sustituible por mes | Cliente             | Personal             | Fecha válida            | Planeación            |
| `event_month`                | Año-mes         | Alternativa a fecha               | Cliente             | Personal             | Mes válido              | Cotización aproximada |
| `event_date_type`            | Enum            | Obligatorio                       | Sistema             | Interno              | Catálogo válido         | Calidad               |
| `date_flexibility`           | Enum            | Opcional                          | Cliente             | Personal             | Catálogo válido         | Alternativas          |
| `preferred_weekday`          | Enum            | Opcional                          | Cliente             | Personal             | Día válido              | Preferencia           |
| `alternative_dates`          | Lista de fechas | Opcional                          | Cliente             | Personal             | Fechas válidas          | Disponibilidad        |
| `start_time`                 | Hora            | Opcional para solicitud           | Cliente/asesor      | Personal             | Hora válida             | Operación             |
| `end_time`                   | Hora            | Opcional                          | Cliente/asesor      | Personal             | Posterior al inicio     | Operación             |
| `estimated_duration_minutes` | Entero          | Opcional/calculado                | Sistema/asesor      | Interno              | Mayor a cero            | Planeación            |
| `adult_guest_count`          | Entero          | Opcional                          | Cliente             | Personal             | Mayor o igual a cero    | Menú/capacidad        |
| `child_guest_count`          | Entero          | Opcional                          | Cliente             | Personal             | Mayor o igual a cero    | Menú/capacidad        |
| `infant_guest_count`         | Entero          | Opcional                          | Cliente             | Personal             | Mayor o igual a cero    | Menú/capacidad        |
| `total_guest_count`          | Entero          | Obligatorio para cotizar          | Cliente/calculado   | Personal             | Mayor o igual a uno     | Capacidad             |
| `guest_count_min`            | Entero          | Opcional                          | Cliente/IA          | Personal             | Mayor o igual a uno     | Rango                 |
| `guest_count_max`            | Entero          | Opcional                          | Cliente/IA          | Personal             | Mayor o igual al mínimo | Rango                 |
| `guest_count_status`         | Enum            | Automático                        | Sistema             | Interno              | Estimado/confirmado     | Calidad               |
| `children_age_ranges`        | Lista           | Opcional                          | Cliente             | Sensible operacional | Rangos válidos          | Menú                  |
| `preferred_space`            | Enum            | Opcional                          | Cliente             | Interno              | Espacio válido          | Propuesta             |
| `space_confirmed`            | Booleano        | Restringido                       | Asesor              | Interno              | Booleano                | Reserva               |
| `capacity_review_required`   | Booleano        | Calculado                         | Sistema             | Interno              | Booleano                | Escalamiento          |
| `pool_use_expected`          | Booleano        | Opcional                          | Cliente             | Interno              | Booleano                | Operación             |
| `pet_attendance`             | Booleano        | Opcional                          | Cliente             | Personal             | Booleano                | Preparación           |
| `pet_count`                  | Entero          | Opcional                          | Cliente             | Personal             | Mayor o igual a cero    | Preparación           |
| `accessibility_requirements` | Texto           | Opcional                          | Cliente             | Sensible operacional | Entrada voluntaria      | Atención              |
| `event_description`          | Texto           | Opcional                          | Cliente             | Personal             | Longitud limitada       | Contexto              |
| `special_requests`           | Texto           | Opcional                          | Cliente             | Personal             | Longitud limitada       | Personalización       |
| `event_status`               | Enum            | Automático/restringido            | Sistema/asesor      | Interno              | Estado permitido        | Seguimiento           |
| `created_at`                 | Fecha/hora      | Automático                        | Sistema             | Técnica              | No editable             | Auditoría             |
| `updated_at`                 | Fecha/hora      | Automático                        | Sistema             | Técnica              | No editable             | Auditoría             |

## 8.3 Tipos de evento

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

## 8.4 Tipos de fecha

```text
EXACT
APPROXIMATE
FLEXIBLE
UNKNOWN
```

## 8.5 Reglas

* Si se conoce únicamente el mes, `event_date` permanecerá vacío.
* Las fechas relativas deberán confirmarse con fecha absoluta.
* Los niños y bebés deberán considerarse en el aforo.
* Más de 60 invitados activará revisión.
* Un rango de invitados no se convertirá automáticamente en cifra confirmada.

---

# 9. Entidad EventServiceRequest

## 9.1 Propósito

Representar cada servicio solicitado o mencionado para un evento.

Se recomienda utilizar una colección relacionada en lugar de múltiples campos booleanos fijos, porque facilitará la incorporación de nuevos servicios.

## 9.2 Matriz de campos

| Campo                      | Tipo lógico | Clasificación          | Fuente         | Sensibilidad | Validación        | Uso               |
| -------------------------- | ----------- | ---------------------- | -------------- | ------------ | ----------------- | ----------------- |
| `event_service_request_id` | UUID        | Automático             | Sistema        | Técnica      | Único             | Identificación    |
| `event_id`                 | UUID        | Obligatorio            | Sistema        | Técnica      | Evento existente  | Relación          |
| `service_code`             | Enum/texto  | Obligatorio            | Cliente/asesor | Interno      | Catálogo vigente  | Servicio          |
| `service_category`         | Enum        | Automático             | Catálogo       | Interno      | Categoría válida  | Agrupación        |
| `status`                   | Enum        | Automático/restringido | Sistema/asesor | Interno      | Estado permitido  | Disponibilidad    |
| `requested_quantity`       | Decimal     | Opcional               | Cliente/asesor | Personal     | Mayor a cero      | Cálculo futuro    |
| `client_provided`          | Booleano    | Opcional               | Cliente        | Interno      | Booleano          | Proveedor externo |
| `supplier_dependency`      | Booleano    | Calculado              | Catálogo       | Interno      | Booleano          | Escalamiento      |
| `notes`                    | Texto       | Opcional               | Cliente/asesor | Personal     | Longitud limitada | Detalle           |
| `created_at`               | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable       | Auditoría         |
| `updated_at`               | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable       | Auditoría         |

## 9.3 Estados

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

## 9.4 Categorías iniciales

```text
VENUE
FOOD
BEVERAGE
DECORATION
FLORAL
STAFF
AUDIOVISUAL
ENTERTAINMENT
PHOTOGRAPHY
VIDEO
BEAUTY
CAKE
ACCOMMODATION
POOL
EXTERNAL_SUPPLIER
OTHER
```

## 9.5 Reglas

* `REQUESTED` no significa incluido.
* Los servicios de proveedor deberán iniciar como `PENDING_CONFIRMATION`.
* La disponibilidad final deberá confirmarla un asesor o servicio determinista.
* Los servicios retirados deberán conservar historial.

---

# 10. Datos alimentarios y de bebidas

Los requerimientos alimentarios deberán relacionarse con el evento.

| Campo                  | Tipo        | Clasificación | Sensibilidad         | Uso                     |
| ---------------------- | ----------- | ------------- | -------------------- | ----------------------- |
| `food_service_type`    | Enum        | Opcional      | Personal             | Cena, brunch, pasabocas |
| `menu_preferences`     | Texto/lista | Opcional      | Personal             | Propuesta               |
| `dietary_requirements` | Texto/lista | Opcional      | Sensible operacional | Seguridad alimentaria   |
| `external_food`        | Booleano    | Opcional      | Interno              | Coordinación            |
| `beverages_required`   | Booleano    | Opcional      | Interno              | Propuesta               |
| `external_beverages`   | Booleano    | Opcional      | Interno              | Coordinación            |
| `alcohol_expected`     | Booleano    | Opcional      | Interno              | Operación               |
| `cocktail_service`     | Booleano    | Opcional      | Interno              | Propuesta               |

## Reglas

* Solo se preguntarán alergias o necesidades relevantes.
* No se solicitará historia clínica.
* Los alimentos externos no deberán interpretarse como responsabilidad de La Ceiba.
* No existe cobro de descorche.

---

# 11. Entidad Conversation

## 11.1 Propósito

Controlar el estado del diálogo sin almacenar como única fuente los datos comerciales.

## 11.2 Matriz de campos

| Campo                        | Tipo lógico | Clasificación          | Fuente         | Sensibilidad | Validación           | Uso            |
| ---------------------------- | ----------- | ---------------------- | -------------- | ------------ | -------------------- | -------------- |
| `conversation_id`            | UUID        | Automático             | Sistema        | Técnica      | Único                | Identificación |
| `customer_id`                | UUID        | Obligatorio            | Sistema        | Técnica      | Cliente existente    | Relación       |
| `lead_id`                    | UUID        | Opcional               | Sistema        | Técnica      | Lead existente       | Contexto       |
| `channel`                    | Enum        | Automático             | Canal          | Interno      | Canal permitido      | Origen         |
| `channel_account_id`         | Texto       | Automático             | Canal          | Técnica      | Valor válido         | Cuenta         |
| `external_conversation_id`   | Texto       | Automático             | Canal          | Técnica      | Único por canal      | Trazabilidad   |
| `conversation_status`        | Enum        | Automático/restringido | Sistema/asesor | Interno      | Estado permitido     | Flujo          |
| `bot_enabled`                | Booleano    | Restringido            | Sistema/asesor | Interno      | Booleano             | Automatización |
| `current_intent`             | Enum        | Automático             | IA validada    | Interno      | Catálogo permitido   | Interpretación |
| `previous_intent`            | Enum        | Automático             | Sistema        | Interno      | Catálogo permitido   | Retorno        |
| `pending_action`             | Enum        | Automático             | Orquestador    | Interno      | Acción válida        | Continuidad    |
| `pending_fields`             | Lista       | Calculado              | Sistema        | Interno      | Campos conocidos     | Captura        |
| `last_question_code`         | Texto/enum  | Automático             | Sistema        | Interno      | Código válido        | Contexto       |
| `failed_understanding_count` | Entero      | Calculado              | Sistema        | Interno      | Mayor o igual a cero | Fallback       |
| `confidence_score`           | Decimal     | Automático             | IA             | Técnica      | Entre cero y uno     | Validación     |
| `conversation_summary`       | Texto       | Automático/restringido | IA/sistema     | Personal     | Longitud limitada    | Handoff        |
| `assigned_agent_id`          | UUID        | Restringido            | Sistema/asesor | Interno      | Usuario activo       | Atención       |
| `human_takeover_at`          | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable          | Auditoría      |
| `returned_to_bot_at`         | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable          | Auditoría      |
| `last_message_at`            | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable          | Sesión         |
| `created_at`                 | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable          | Auditoría      |
| `resolved_at`                | Fecha/hora  | Automático             | Sistema        | Técnica      | Estado válido        | Cierre         |
| `closed_at`                  | Fecha/hora  | Automático             | Sistema        | Técnica      | Estado válido        | Cierre         |

## 11.3 Estados

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

## 11.4 Reglas

* `HUMAN_ACTIVE` implica `bot_enabled = false`.
* Una conversación puede cambiar de intención sin cambiar de lead.
* El resumen no reemplaza los mensajes.
* El contador de fallos deberá reiniciarse después de una interpretación exitosa.

---

# 12. Entidad Message

## 12.1 Propósito

Conservar cada mensaje entrante, saliente o interno de manera inmutable.

## 12.2 Matriz de campos

| Campo                 | Tipo lógico | Clasificación | Fuente  | Sensibilidad     | Validación             | Uso            |
| --------------------- | ----------- | ------------- | ------- | ---------------- | ---------------------- | -------------- |
| `message_id`          | UUID        | Automático    | Sistema | Técnica          | Único                  | Identificación |
| `conversation_id`     | UUID        | Obligatorio   | Sistema | Técnica          | Conversación existente | Relación       |
| `external_message_id` | Texto       | Automático    | Canal   | Técnica          | Único                  | Idempotencia   |
| `direction`           | Enum        | Automático    | Sistema | Interno          | INBOUND/OUTBOUND       | Dirección      |
| `sender_type`         | Enum        | Automático    | Sistema | Interno          | Tipo permitido         | Autor          |
| `message_type`        | Enum        | Automático    | Canal   | Interno          | Tipo permitido         | Tratamiento    |
| `raw_payload`         | JSON/texto  | Automático    | Canal   | Técnica/personal | Acceso restringido     | Evidencia      |
| `normalized_text`     | Texto       | Automático    | Sistema | Personal         | Longitud controlada    | IA             |
| `reply_to_message_id` | UUID/texto  | Opcional      | Canal   | Técnica          | Referencia válida      | Contexto       |
| `delivery_status`     | Enum        | Automático    | Canal   | Técnica          | Estado permitido       | Seguimiento    |
| `has_attachment`      | Booleano    | Automático    | Sistema | Técnica          | Booleano               | Archivo        |
| `received_at`         | Fecha/hora  | Automático    | Canal   | Técnica          | No editable            | Auditoría      |
| `processed_at`        | Fecha/hora  | Automático    | Sistema | Técnica          | No editable            | Métricas       |
| `sent_at`             | Fecha/hora  | Automático    | Sistema | Técnica          | No editable            | Auditoría      |
| `error_code`          | Texto       | Automático    | Sistema | Técnica          | Catálogo               | Diagnóstico    |
| `metadata`            | JSON        | Automático    | Sistema | Técnica          | Esquema controlado     | Integración    |

## 12.3 Direcciones

```text
INBOUND
OUTBOUND
INTERNAL
```

## 12.4 Tipos de remitente

```text
CUSTOMER
BOT
AGENT
SYSTEM
INTEGRATION
```

## 12.5 Tipos de mensaje

```text
TEXT
IMAGE
AUDIO
VIDEO
DOCUMENT
INTERACTIVE
LOCATION
SYSTEM_EVENT
OTHER
```

## 12.6 Regla crítica

```text
external_message_id = UNIQUE
```

El mensaje no deberá sobrescribirse ni procesarse dos veces.

---

# 13. Entidad Attachment

## 13.1 Propósito

Registrar archivos, imágenes, documentos, audios o comprobantes.

## 13.2 Campos

| Campo                 | Tipo       | Clasificación          | Sensibilidad         | Uso                   |
| --------------------- | ---------- | ---------------------- | -------------------- | --------------------- |
| `attachment_id`       | UUID       | Automático             | Técnica              | Identificación        |
| `message_id`          | UUID       | Obligatorio            | Técnica              | Relación              |
| `file_name`           | Texto      | Automático             | Personal             | Referencia            |
| `mime_type`           | Texto      | Automático             | Técnica              | Validación            |
| `file_size`           | Entero     | Automático             | Técnica              | Límites               |
| `storage_reference`   | Texto      | Automático             | Sensible operacional | Acceso                |
| `file_hash`           | Texto      | Automático             | Técnica              | Duplicados/integridad |
| `attachment_category` | Enum       | Automático/restringido | Interno              | Clasificación         |
| `security_status`     | Enum       | Automático             | Técnica              | Escaneo               |
| `created_at`          | Fecha/hora | Automático             | Técnica              | Auditoría             |

## 13.3 Categorías

```text
PAYMENT_PROOF
INSPIRATION_IMAGE
QUOTE_DOCUMENT
CONTRACT_DOCUMENT
GENERAL_DOCUMENT
AUDIO_MESSAGE
VIDEO_REFERENCE
OTHER
```

## 13.4 Reglas

* Los archivos no deberán exponerse mediante enlaces públicos permanentes.
* Los comprobantes tendrán acceso restringido.
* Los archivos deberán validarse por tipo y tamaño.
* No se procesarán automáticamente contratos durante el MVP.

---

# 14. Entidad QuoteRequest

## 14.1 Propósito

Representar una solicitud estructurada para que un asesor prepare una cotización.

## 14.2 Matriz de campos

| Campo                   | Tipo lógico | Clasificación          | Fuente         | Sensibilidad | Validación         | Uso            |
| ----------------------- | ----------- | ---------------------- | -------------- | ------------ | ------------------ | -------------- |
| `quote_request_id`      | UUID        | Automático             | Sistema        | Técnica      | Único              | Identificación |
| `lead_id`               | UUID        | Obligatorio            | Sistema        | Técnica      | Lead existente     | Relación       |
| `event_id`              | UUID        | Obligatorio            | Sistema        | Técnica      | Evento existente   | Relación       |
| `request_status`        | Enum        | Automático/restringido | Sistema/asesor | Interno      | Estado válido      | Seguimiento    |
| `minimum_data_complete` | Booleano    | Calculado              | Sistema        | Interno      | Booleano           | Preparación    |
| `missing_fields`        | Lista       | Calculado              | Sistema        | Interno      | Campos válidos     | Captura        |
| `requested_at`          | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable        | SLA            |
| `assigned_agent_id`     | UUID        | Restringido            | Sistema/asesor | Interno      | Usuario activo     | Responsable    |
| `assigned_at`           | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable        | SLA            |
| `due_at`                | Fecha/hora  | Calculado              | Sistema        | Interno      | Regla hábil        | Vencimiento    |
| `customer_notes`        | Texto       | Opcional               | Cliente        | Personal     | Longitud limitada  | Contexto       |
| `internal_notes`        | Texto       | Restringido            | Asesor         | Interno      | Longitud limitada  | Preparación    |
| `summary_snapshot`      | JSON/texto  | Automático             | Sistema        | Personal     | Esquema controlado | Evidencia      |
| `completed_at`          | Fecha/hora  | Automático             | Sistema        | Técnica      | Estado válido      | Métricas       |
| `created_at`            | Fecha/hora  | Automático             | Sistema        | Técnica      | No editable        | Auditoría      |

## 14.3 Estados

```text
DRAFT
READY
ASSIGNED
IN_PROGRESS
COMPLETED
CANCELLED
EXPIRED
```

## 14.4 Datos mínimos

Para pasar a `READY`:

```text
full_name
phone_number
event_type
event_date OR event_month
total_guest_count OR guest_count_range
```

## 14.5 Reglas

* El presupuesto no bloquea la solicitud.
* `due_at` se calculará con máximo tres días hábiles.
* El resumen deberá ser una fotografía del momento, no una referencia dinámica.
* La solicitud no contendrá precios calculados por IA.

---

# 15. Entidad Quote

## 15.1 Propósito

Registrar cotizaciones elaboradas por asesores y preparar la evolución hacia el motor automático.

## 15.2 Matriz de campos

| Campo                    | Tipo lógico | Clasificación         | Fuente              | Sensibilidad         | Validación           | Uso            |
| ------------------------ | ----------- | --------------------- | ------------------- | -------------------- | -------------------- | -------------- |
| `quote_id`               | UUID        | Automático            | Sistema             | Técnica              | Único                | Identificación |
| `quote_request_id`       | UUID        | Obligatorio           | Sistema             | Técnica              | Solicitud existente  | Relación       |
| `lead_id`                | UUID        | Obligatorio           | Sistema             | Técnica              | Lead existente       | Relación       |
| `version_number`         | Entero      | Automático            | Sistema             | Interno              | Mayor a cero         | Versionado     |
| `quote_status`           | Enum        | Restringido           | Asesor/sistema      | Interno              | Estado válido        | Seguimiento    |
| `currency`               | Enum        | Restringido           | Sistema             | Interno              | COP inicialmente     | Valores        |
| `subtotal`               | Decimal     | Restringido/calculado | Asesor/motor futuro | Sensible operacional | Mayor o igual a cero | Valor          |
| `taxes`                  | Decimal     | Restringido/calculado | Asesor/motor futuro | Sensible operacional | Mayor o igual a cero | Valor          |
| `discount`               | Decimal     | Restringido           | Asesor autorizado   | Sensible operacional | Límites autorizados  | Valor          |
| `total`                  | Decimal     | Calculado             | Sistema             | Sensible operacional | Fórmula válida       | Valor          |
| `valid_from`             | Fecha       | Restringido           | Asesor              | Interno              | Fecha válida         | Vigencia       |
| `valid_until`            | Fecha       | Restringido           | Asesor              | Interno              | Posterior a inicio   | Vigencia       |
| `prepared_by`            | UUID        | Automático            | Sistema             | Interno              | Usuario válido       | Responsable    |
| `approved_by`            | UUID        | Opcional/restringido  | Manager/asesor      | Interno              | Usuario autorizado   | Control        |
| `document_attachment_id` | UUID        | Opcional              | Sistema/asesor      | Sensible operacional | Archivo existente    | Entrega        |
| `sent_at`                | Fecha/hora  | Automático            | Sistema             | Técnica              | Estado enviado       | Seguimiento    |
| `customer_response`      | Enum        | Opcional              | Cliente/asesor      | Interno              | Estado válido        | Resultado      |
| `terms_snapshot`         | JSON/texto  | Restringido           | Sistema             | Sensible operacional | Inmutable            | Condiciones    |
| `pricing_rules_snapshot` | JSON        | Futuro/calculado      | Motor               | Técnica              | Esquema válido       | Auditoría      |
| `created_at`             | Fecha/hora  | Automático            | Sistema             | Técnica              | No editable          | Auditoría      |

## 15.3 Estados

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

## 15.4 Reglas

* Una cotización enviada no se modifica.
* Cada nueva versión incrementa `version_number`.
* El total deberá derivarse de conceptos.
* Los descuentos requieren autorización.
* Las reglas futuras se conservarán mediante snapshot.

---

# 16. Entidad QuoteItem

## 16.1 Propósito

Representar cada concepto incluido dentro de una cotización.

## 16.2 Campos

| Campo                     | Tipo     | Clasificación         | Fuente          | Validación           |
| ------------------------- | -------- | --------------------- | --------------- | -------------------- |
| `quote_item_id`           | UUID     | Automático            | Sistema         | Único                |
| `quote_id`                | UUID     | Obligatorio           | Sistema         | Cotización existente |
| `item_type`               | Enum     | Restringido           | Asesor/catálogo | Tipo válido          |
| `description`             | Texto    | Restringido           | Asesor/catálogo | Longitud válida      |
| `quantity`                | Decimal  | Restringido/calculado | Asesor/motor    | Mayor a cero         |
| `unit_price`              | Decimal  | Restringido/calculado | Asesor/motor    | Mayor o igual a cero |
| `subtotal`                | Decimal  | Calculado             | Sistema         | Fórmula válida       |
| `tax_rate`                | Decimal  | Restringido/calculado | Asesor/motor    | Rango válido         |
| `total`                   | Decimal  | Calculado             | Sistema         | Fórmula válida       |
| `included`                | Booleano | Restringido           | Asesor/motor    | Booleano             |
| `subject_to_confirmation` | Booleano | Restringido           | Asesor/motor    | Booleano             |
| `supplier_dependency`     | Booleano | Restringido           | Catálogo        | Booleano             |
| `notes`                   | Texto    | Opcional              | Asesor          | Longitud limitada    |

## 16.3 Tipos de concepto

```text
VENUE
FOOD
BEVERAGE
DECORATION
STAFF
AUDIOVISUAL
ENTERTAINMENT
PHOTOGRAPHY
VIDEO
BEAUTY
CAKE
ACCOMMODATION
ADDITIONAL_SERVICE
DISCOUNT
TAX
OTHER
```

---

# 17. Entidad Appointment

## 17.1 Propósito

Representar una visita comercial a La Ceiba.

## 17.2 Matriz de campos

| Campo                   | Tipo lógico | Clasificación          | Fuente          | Sensibilidad | Validación           | Uso            |
| ----------------------- | ----------- | ---------------------- | --------------- | ------------ | -------------------- | -------------- |
| `appointment_id`        | UUID        | Automático             | Sistema         | Técnica      | Único                | Identificación |
| `customer_id`           | UUID        | Obligatorio            | Sistema         | Técnica      | Cliente existente    | Relación       |
| `lead_id`               | UUID        | Opcional               | Sistema         | Técnica      | Lead existente       | Contexto       |
| `appointment_type`      | Enum        | Automático             | Sistema         | Interno      | `VISIT`              | Tipo           |
| `appointment_date`      | Fecha       | Obligatorio            | Cliente         | Personal     | Día permitido        | Agenda         |
| `start_time`            | Hora        | Obligatorio            | Cliente         | Personal     | 08, 09, 10 u 11      | Agenda         |
| `end_time`              | Hora        | Calculado              | Sistema         | Interno      | Inicio + 45 minutos  | Agenda         |
| `timezone`              | Texto       | Automático             | Sistema         | Técnica      | America/Bogota       | Interpretación |
| `attendee_count`        | Entero      | Obligatorio            | Cliente         | Personal     | Entre 1 y 3          | Capacidad      |
| `visitor_names`         | Lista       | Opcional               | Cliente         | Personal     | Nombres válidos      | Recepción      |
| `visit_reason`          | Enum/texto  | Obligatorio            | Cliente/lead    | Personal     | Valor válido         | Contexto       |
| `appointment_status`    | Enum        | Automático/restringido | Sistema/asesor  | Interno      | Estado válido        | Flujo          |
| `assigned_manager_id`   | UUID        | Restringido            | Sistema/asesor  | Interno      | Usuario activo       | Responsable    |
| `external_calendar_id`  | Texto       | Automático             | Calendario      | Técnica      | Único externo        | Sincronización |
| `reminder_scheduled_at` | Fecha/hora  | Calculado              | Sistema         | Técnica      | Un día antes         | Notificación   |
| `reminder_sent_at`      | Fecha/hora  | Automático             | Sistema         | Técnica      | No editable          | Auditoría      |
| `reschedule_count`      | Entero      | Calculado              | Sistema         | Interno      | Mayor o igual a cero | Reincidencia   |
| `cancellation_reason`   | Texto       | Opcional               | Cliente/asesor  | Personal     | Longitud limitada    | Análisis       |
| `cancelled_at`          | Fecha/hora  | Automático             | Sistema         | Técnica      | Estado cancelado     | Auditoría      |
| `no_show_recorded_at`   | Fecha/hora  | Restringido            | Manager/sistema | Técnica      | Estado no show       | Auditoría      |
| `internal_notes`        | Texto       | Restringido            | Asesor/manager  | Interno      | Longitud limitada    | Operación      |
| `created_at`            | Fecha/hora  | Automático             | Sistema         | Técnica      | No editable          | Auditoría      |
| `updated_at`            | Fecha/hora  | Automático             | Sistema         | Técnica      | No editable          | Auditoría      |

## 17.3 Estados

```text
PENDING_CONFIRMATION
CONFIRMED
RESCHEDULED
CANCELLED
LATE_CANCEL
COMPLETED
NO_SHOW
```

## 17.4 Validaciones

* Martes a sábado.
* No festivo colombiano.
* Mínimo tres días de anticipación.
* Máximo cuatro visitas por día.
* Máximo tres asistentes.
* Horarios fijos.
* No puede existir otra cita activa en el mismo horario.
* La disponibilidad debe validarse antes de crear.

---

# 18. Entidad AppointmentChange

## 18.1 Propósito

Conservar el historial de cada reprogramación.

| Campo                   | Tipo       | Clasificación |
| ----------------------- | ---------- | ------------- |
| `appointment_change_id` | UUID       | Automático    |
| `appointment_id`        | UUID       | Obligatorio   |
| `previous_date`         | Fecha      | Automático    |
| `previous_start_time`   | Hora       | Automático    |
| `new_date`              | Fecha      | Automático    |
| `new_start_time`        | Hora       | Automático    |
| `change_reason`         | Texto      | Opcional      |
| `changed_by_type`       | Enum       | Automático    |
| `changed_by_id`         | UUID/texto | Automático    |
| `changed_at`            | Fecha/hora | Automático    |

## Reglas

* Los registros no deberán editarse.
* Una reprogramación fallida no debe crear un cambio definitivo.
* El nuevo horario debe validarse antes de confirmar.

---

# 19. Entidad Reservation

## 19.1 Propósito

Representar la separación oficial de la fecha de un evento.

## 19.2 Campos

| Campo                         | Tipo lógico | Clasificación          | Fuente         | Sensibilidad         | Validación           |
| ----------------------------- | ----------- | ---------------------- | -------------- | -------------------- | -------------------- |
| `reservation_id`              | UUID        | Automático             | Sistema        | Técnica              | Único                |
| `event_id`                    | UUID        | Obligatorio            | Sistema        | Técnica              | Evento existente     |
| `quote_id`                    | UUID        | Obligatorio            | Sistema        | Técnica              | Cotización válida    |
| `reservation_status`          | Enum        | Restringido            | Sistema/asesor | Sensible operacional | Estado válido        |
| `reservation_percentage`      | Decimal     | Configurable           | Sistema        | Sensible operacional | Inicialmente 50      |
| `reservation_amount`          | Decimal     | Calculado              | Sistema        | Sensible operacional | Según cotización     |
| `payment_status`              | Enum        | Automático/restringido | Sistema/asesor | Sensible operacional | Estado válido        |
| `reserved_at`                 | Fecha/hora  | Restringido            | Sistema        | Técnica              | Pago confirmado      |
| `confirmed_by`                | UUID        | Restringido            | Asesor         | Interno              | Usuario autorizado   |
| `terms_accepted_at`           | Fecha/hora  | Restringido            | Sistema/asesor | Técnica              | Evidencia            |
| `terms_snapshot`              | Texto/JSON  | Restringido            | Sistema        | Sensible operacional | Inmutable            |
| `cancellation_requested_at`   | Fecha/hora  | Automático             | Sistema        | Técnica              | Solicitud existente  |
| `cancelled_at`                | Fecha/hora  | Restringido            | Asesor         | Técnica              | Estado cancelado     |
| `cancellation_policy_applied` | Texto/enum  | Restringido            | Asesor         | Sensible operacional | Política válida      |
| `refund_decision`             | Enum        | Restringido            | Asesor/manager | Sensible operacional | Estado válido        |
| `refund_amount`               | Decimal     | Restringido            | Asesor/manager | Sensible operacional | Mayor o igual a cero |
| `created_at`                  | Fecha/hora  | Automático             | Sistema        | Técnica              | No editable          |

## 19.3 Estados

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

## 19.4 Regla crítica

```text
reservation_status = RESERVED
solo si
payment_status = PAYMENT_CONFIRMED
```

---

# 20. Entidad Payment

## 20.1 Propósito

Registrar pagos informados y su proceso de validación humana.

## 20.2 Campos

| Campo                 | Tipo lógico | Clasificación            | Fuente         | Sensibilidad         | Validación              |
| --------------------- | ----------- | ------------------------ | -------------- | -------------------- | ----------------------- |
| `payment_id`          | UUID        | Automático               | Sistema        | Técnica              | Único                   |
| `reservation_id`      | UUID        | Opcional al recibir      | Sistema/asesor | Técnica              | Reserva existente       |
| `quote_id`            | UUID        | Opcional                 | Sistema/asesor | Técnica              | Cotización existente    |
| `payment_method`      | Enum        | Obligatorio para validar | Cliente/asesor | Sensible operacional | Método permitido        |
| `reported_amount`     | Decimal     | Preferible               | Cliente/asesor | Sensible operacional | Mayor a cero            |
| `expected_amount`     | Decimal     | Calculado                | Sistema        | Sensible operacional | Mayor a cero            |
| `payment_reference`   | Texto       | Opcional                 | Cliente/asesor | Sensible operacional | Longitud limitada       |
| `proof_attachment_id` | UUID        | Opcional                 | Canal          | Sensible operacional | Archivo existente       |
| `reported_at`         | Fecha/hora  | Automático               | Sistema        | Técnica              | No editable             |
| `payment_status`      | Enum        | Restringido              | Sistema/asesor | Sensible operacional | Estado válido           |
| `review_due_at`       | Fecha/hora  | Calculado                | Sistema        | Técnica              | Máximo un día           |
| `reviewed_at`         | Fecha/hora  | Restringido              | Asesor         | Técnica              | Estado revisado         |
| `reviewed_by`         | UUID        | Restringido              | Asesor         | Interno              | Usuario autorizado      |
| `rejection_reason`    | Texto       | Restringido              | Asesor         | Interno              | Obligatorio al rechazar |
| `internal_notes`      | Texto       | Restringido              | Asesor         | Interno              | Longitud limitada       |
| `created_at`          | Fecha/hora  | Automático               | Sistema        | Técnica              | No editable             |

## 20.3 Métodos

```text
BANK_TRANSFER
CASH
CARD
NEQUI
DAVIPLATA
PAYMENT_LINK
OTHER_AUTHORIZED
```

## 20.4 Estados

```text
PAYMENT_PENDING
PAYMENT_REVIEW
PAYMENT_CONFIRMED
PAYMENT_REJECTED
PAYMENT_CANCELLED
```

## 20.5 Datos financieros prohibidos

No deberán almacenarse:

* CVV;
* PIN;
* clave bancaria;
* OTP;
* contraseña;
* número completo de tarjeta.

---

# 21. Entidad Handoff

## 21.1 Propósito

Gestionar la transferencia desde el bot hacia un asesor.

## 21.2 Campos

| Campo                   | Tipo       | Clasificación          | Fuente         | Sensibilidad | Uso            |
| ----------------------- | ---------- | ---------------------- | -------------- | ------------ | -------------- |
| `handoff_id`            | UUID       | Automático             | Sistema        | Técnica      | Identificación |
| `conversation_id`       | UUID       | Obligatorio            | Sistema        | Técnica      | Relación       |
| `lead_id`               | UUID       | Opcional               | Sistema        | Técnica      | Contexto       |
| `handoff_reason`        | Enum       | Automático/restringido | Sistema/asesor | Interno      | Motivo         |
| `priority`              | Enum       | Automático/restringido | Sistema/asesor | Interno      | Orden          |
| `requested_at`          | Fecha/hora | Automático             | Sistema        | Técnica      | SLA            |
| `assigned_agent_id`     | UUID       | Restringido            | Asesor/sistema | Interno      | Responsable    |
| `assigned_at`           | Fecha/hora | Automático             | Sistema        | Técnica      | SLA            |
| `accepted_at`           | Fecha/hora | Automático             | Sistema        | Técnica      | SLA            |
| `resolved_at`           | Fecha/hora | Automático             | Sistema        | Técnica      | Cierre         |
| `summary`               | Texto      | Automático             | Sistema/IA     | Personal     | Contexto       |
| `customer_last_message` | Texto      | Automático             | Sistema        | Personal     | Contexto       |
| `pending_questions`     | Lista      | Automático             | Sistema        | Interno      | Continuidad    |
| `actions_completed`     | Lista      | Automático             | Sistema        | Interno      | Trazabilidad   |
| `resolution_notes`      | Texto      | Restringido            | Asesor         | Interno      | Cierre         |
| `returned_to_bot`       | Booleano   | Restringido            | Asesor         | Interno      | Control        |

## 21.3 Motivos

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

## 21.4 Prioridades

```text
NORMAL
HIGH
URGENT
CRITICAL
```

## 21.5 Reglas

* Solo un asesor puede quedar asignado.
* El bot deberá quedar pausado cuando el asesor tome la conversación.
* La resolución deberá conservarse antes de devolver al bot.

---

# 22. Entidad KnowledgeEntry

## 22.1 Propósito

Almacenar preguntas frecuentes y respuestas autorizadas.

## 22.2 Campos

| Campo                | Tipo       | Clasificación        | Fuente             | Sensibilidad | Uso            |
| -------------------- | ---------- | -------------------- | ------------------ | ------------ | -------------- |
| `knowledge_entry_id` | UUID       | Automático           | Sistema            | Técnica      | Identificación |
| `category`           | Enum       | Restringido          | Operador           | Interno      | Clasificación  |
| `question_variants`  | Lista      | Restringido          | Operador           | Interno      | Recuperación   |
| `approved_answer`    | Texto      | Restringido          | Operador/aprobador | Público      | Respuesta      |
| `short_answer`       | Texto      | Restringido          | Operador/aprobador | Público      | WhatsApp       |
| `status`             | Enum       | Restringido          | Operador/aprobador | Interno      | Activación     |
| `version`            | Entero     | Automático           | Sistema            | Técnica      | Historial      |
| `valid_from`         | Fecha      | Restringido          | Aprobador          | Interno      | Vigencia       |
| `valid_until`        | Fecha      | Opcional/restringido | Aprobador          | Interno      | Vigencia       |
| `approved_by`        | UUID       | Restringido          | Aprobador          | Interno      | Control        |
| `created_at`         | Fecha/hora | Automático           | Sistema            | Técnica      | Auditoría      |
| `updated_at`         | Fecha/hora | Automático           | Sistema            | Técnica      | Auditoría      |

## 22.3 Estados

```text
DRAFT
REVIEW
APPROVED
INACTIVE
EXPIRED
```

## 22.4 Regla

Solo una respuesta `APPROVED` y vigente podrá enviarse automáticamente.

---

# 23. Entidad AIExecution

## 23.1 Propósito

Registrar cada ejecución de inteligencia artificial para diagnóstico, coste y auditoría técnica.

## 23.2 Campos

| Campo               | Tipo            | Clasificación | Sensibilidad     | Uso             |
| ------------------- | --------------- | ------------- | ---------------- | --------------- |
| `ai_execution_id`   | UUID            | Automático    | Técnica          | Identificación  |
| `conversation_id`   | UUID            | Obligatorio   | Técnica          | Contexto        |
| `message_id`        | UUID            | Obligatorio   | Técnica          | Entrada         |
| `purpose`           | Enum            | Automático    | Técnica          | Tipo de llamada |
| `model_provider`    | Texto           | Automático    | Técnica          | Proveedor       |
| `model_name`        | Texto           | Automático    | Técnica          | Modelo          |
| `prompt_version`    | Texto           | Automático    | Técnica          | Trazabilidad    |
| `input_reference`   | JSON/referencia | Automático    | Personal/técnica | Diagnóstico     |
| `structured_output` | JSON            | Automático    | Personal/técnica | Resultado       |
| `confidence`        | Decimal         | Automático    | Técnica          | Validación      |
| `validation_status` | Enum            | Automático    | Técnica          | Seguridad       |
| `tokens_input`      | Entero          | Automático    | Técnica          | Coste           |
| `tokens_output`     | Entero          | Automático    | Técnica          | Coste           |
| `estimated_cost`    | Decimal         | Automático    | Técnica          | Métrica         |
| `latency_ms`        | Entero          | Automático    | Técnica          | Rendimiento     |
| `error_code`        | Texto           | Automático    | Técnica          | Diagnóstico     |
| `created_at`        | Fecha/hora      | Automático    | Técnica          | Auditoría       |

## 23.3 Propósitos

```text
INTENT_CLASSIFICATION
ENTITY_EXTRACTION
RESPONSE_DRAFTING
CONVERSATION_SUMMARY
CONFIDENCE_EVALUATION
```

## 23.4 Reglas

* Evitar copiar información personal innecesaria en logs.
* No almacenar secretos en prompts.
* Las salidas deberán validarse antes de utilizarse.
* Una ejecución de IA no puede modificar directamente pagos o reservas.

---

# 24. Entidad AuditEvent

## 24.1 Propósito

Conservar la trazabilidad de todas las operaciones relevantes.

## 24.2 Campos

| Campo            | Tipo            | Clasificación | Sensibilidad         | Uso            |
| ---------------- | --------------- | ------------- | -------------------- | -------------- |
| `audit_event_id` | UUID            | Automático    | Técnica              | Identificación |
| `actor_type`     | Enum            | Automático    | Interno              | Tipo de actor  |
| `actor_id`       | UUID/texto      | Automático    | Interno              | Responsable    |
| `action`         | Enum/texto      | Automático    | Interno              | Acción         |
| `entity_type`    | Enum            | Automático    | Técnica              | Entidad        |
| `entity_id`      | UUID            | Automático    | Técnica              | Registro       |
| `previous_value` | JSON            | Automático    | Sensible operacional | Historial      |
| `new_value`      | JSON            | Automático    | Sensible operacional | Historial      |
| `reason`         | Texto           | Opcional      | Interno              | Justificación  |
| `request_id`     | Texto           | Automático    | Técnica              | Correlación    |
| `created_at`     | Fecha/hora      | Automático    | Técnica              | Momento        |
| `ip_reference`   | Texto protegido | Opcional      | Técnica              | Seguridad      |

## 24.3 Actores

```text
CUSTOMER
BOT
AGENT
MANAGER
ADMIN
SYSTEM
INTEGRATION
```

## 24.4 Cambios que siempre requieren auditoría

* fecha del evento;
* cantidad de invitados;
* presupuesto;
* asesor asignado;
* cotización;
* descuento;
* cita;
* reprogramación;
* cancelación;
* inasistencia;
* pago;
* reserva;
* devolución;
* pausa o reactivación del bot;
* reglas;
* respuestas aprobadas.

---

# 25. Entidad Configuration

## 25.1 Propósito

Permitir modificar parámetros operativos sin cambiar código.

## 25.2 Parámetros iniciales

| Clave                              | Valor inicial             | Tipo    |
| ---------------------------------- | ------------------------- | ------- |
| `business.timezone`                | `America/Bogota`          | Texto   |
| `quote.reference_budget_cop`       | `4000000`                 | Decimal |
| `quote.delivery_business_days`     | `3`                       | Entero  |
| `reservation.deposit_percentage`   | `50`                      | Decimal |
| `payment.review_hours`             | `24`                      | Entero  |
| `visit.allowed_weekdays`           | `TUE,WED,THU,FRI,SAT`     | Lista   |
| `visit.start_times`                | `08:00,09:00,10:00,11:00` | Lista   |
| `visit.duration_minutes`           | `45`                      | Entero  |
| `visit.buffer_minutes`             | `15`                      | Entero  |
| `visit.minimum_notice_days`        | `3`                       | Entero  |
| `visit.maximum_daily_count`        | `4`                       | Entero  |
| `visit.maximum_attendees`          | `3`                       | Entero  |
| `visit.reminder_hours_before`      | `24`                      | Entero  |
| `human_service.start_time`         | `08:00`                   | Hora    |
| `human_service.end_time`           | `16:00`                   | Hora    |
| `event.comfortable_capacity`       | `50`                      | Entero  |
| `event.maximum_reference_capacity` | `60`                      | Entero  |
| `event.standard_end_time`          | `22:00`                   | Hora    |

## 25.3 Reglas

* Los cambios deberán versionarse.
* Los cambios no afectarán retroactivamente cotizaciones o reservas.
* Solo administradores o managers autorizados podrán modificarlos.

---

# 26. Matriz de obligatoriedad por flujo

| Dato                  |        FAQ |  Crear lead |     Solicitar cotización |       Agendar visita |     Reserva |
| --------------------- | ---------: | ----------: | -----------------------: | -------------------: | ----------: |
| Número telefónico     | Automático | Obligatorio |              Obligatorio |          Obligatorio | Obligatorio |
| Nombre                |         No |  Preferible |              Obligatorio |          Obligatorio | Obligatorio |
| Tipo de evento        |         No |  Preferible |              Obligatorio |           Preferible | Obligatorio |
| Fecha del evento      |         No |    Opcional | Obligatorio o aproximado |            No aplica | Obligatorio |
| Invitados             |         No |    Opcional |      Obligatorio o rango | Asistentes de visita | Obligatorio |
| Presupuesto           |         No |    Opcional |               Preferible |                   No |    Opcional |
| Servicios             |         No |    Opcional |               Preferible |                   No | Confirmados |
| Fecha de visita       |         No |          No |                       No |          Obligatorio |          No |
| Hora de visita        |         No |          No |                       No |          Obligatorio |          No |
| Asistentes a visita   |         No |          No |                       No |          Obligatorio |          No |
| Motivo de visita      |         No |          No |                       No |          Obligatorio |          No |
| Correo electrónico    |         No |    Opcional |                 Opcional |             Opcional |  Preferible |
| Método de pago        |         No |          No |                       No |                   No | Obligatorio |
| Pago confirmado       |         No |          No |                       No |                   No | Obligatorio |
| Condiciones aceptadas |         No |          No |                       No |                   No | Obligatorio |

---

# 27. Matriz de permisos por rol

## 27.1 Roles

```text
ADMIN
MANAGER
ADVISOR
BUSINESS_MANAGER
CONTENT_OPERATOR
READ_ONLY
BOT
SYSTEM
```

## 27.2 Permisos funcionales

| Dato o acción                 |            Bot |        Asesor | Business Manager |     Manager | Admin |
| ----------------------------- | -------------: | ------------: | ---------------: | ----------: | ----: |
| Crear cliente                 |             Sí |            Sí |               Sí |          Sí |    Sí |
| Actualizar nombre             |             Sí |            Sí |               Sí |          Sí |    Sí |
| Crear lead                    |             Sí |            Sí |               No |          Sí |    Sí |
| Actualizar evento             | Sí, no crítico |            Sí |         Limitado |          Sí |    Sí |
| Registrar presupuesto         |             Sí |            Sí |               No |          Sí |    Sí |
| Crear solicitud de cotización |             Sí |            Sí |               No |          Sí |    Sí |
| Crear cotización              |             No |            Sí |               No |          Sí |    Sí |
| Aplicar descuento             |             No |   Restringido |               No |          Sí |    Sí |
| Crear visita                  |       Solicita |            Sí |               Sí |          Sí |    Sí |
| Marcar visita completada      |             No |            Sí |               Sí |          Sí |    Sí |
| Marcar inasistencia           |             No |            Sí |               Sí |          Sí |    Sí |
| Registrar comprobante         |             Sí |            Sí |               No |          Sí |    Sí |
| Confirmar pago                |             No | Sí autorizado |               No |          Sí |    Sí |
| Confirmar reserva             |             No | Sí autorizado |               No |          Sí |    Sí |
| Aprobar devolución            |             No |   Restringido |               No |          Sí |    Sí |
| Editar base de conocimiento   |             No |            No |               No |          Sí |    Sí |
| Aprobar conocimiento          |             No |            No |               No |          Sí |    Sí |
| Modificar configuración       |             No |            No |               No | Restringido |    Sí |

---

# 28. Datos que la IA puede inferir

La IA podrá inferir:

* tipo de evento;
* fecha relativa;
* rango de invitados;
* intención de cotizar;
* intención de visitar;
* solicitud de cancelación;
* servicios mencionados;
* presupuesto aproximado;
* queja;
* urgencia.

## Regla

Los datos inferidos deberán marcarse como `INFERRED` y confirmarse cuando afecten:

* citas;
* cotizaciones;
* pagos;
* reservas;
* cancelaciones;
* capacidad.

---

# 29. Datos que solo puede confirmar una persona

* precio;
* descuento;
* vigencia;
* disponibilidad de proveedor;
* extensión de horario;
* servicio especial;
* pago recibido;
* reserva;
* devolución;
* excepción comercial;
* capacidad superior a 60;
* cambio de fecha de un evento reservado;
* condiciones contractuales.

---

# 30. Datos que el bot no debe solicitar

El bot no deberá solicitar:

* contraseñas;
* PIN;
* CVV;
* códigos OTP;
* claves bancarias;
* acceso a cuentas;
* número completo de tarjeta;
* historia clínica;
* diagnóstico médico completo;
* orientación política;
* religión;
* origen étnico;
* información sexual o íntima;
* antecedentes judiciales;
* documento de identidad sin finalidad aprobada;
* dirección residencial sin necesidad;
* información escolar de menores;
* imágenes de documentos sin necesidad contractual.

---

# 31. Datos sensibles permitidos por necesidad

## 31.1 Alergias y alimentación

Pregunta permitida:

> ¿Alguno de los invitados tiene alergias o requerimientos alimentarios que debamos considerar?

No debe pedirse diagnóstico médico.

## 31.2 Accesibilidad

Pregunta permitida:

> ¿Hay alguna necesidad de accesibilidad que debamos tener en cuenta para recibirlos adecuadamente?

## 31.3 Menores

Solo se recopilarán:

* cantidad;
* edades aproximadas;
* necesidad de menú;
* necesidad de silla;
* uso de piscina;
* necesidad operativa especial.

---

# 32. Política inicial de retención

## 32.1 Conversaciones informativas

Periodo inicial recomendado:

```text
12 meses
```

## 32.2 Leads y cotizaciones

Periodo inicial recomendado:

```text
5 años
```

Sujeto a revisión jurídica, contractual y contable.

## 32.3 Reservas y pagos

Se conservarán durante el plazo requerido por:

* obligaciones contractuales;
* obligaciones contables;
* obligaciones tributarias;
* atención de reclamaciones.

## 32.4 Ejecuciones de IA

Se conservarán datos técnicos minimizados.

No deberán guardarse indefinidamente prompts completos con información personal innecesaria.

## 32.5 Archivos

Los comprobantes y documentos deberán conservarse según la finalidad y política correspondiente.

---

# 33. Eliminación, anonimización y exportación

El sistema deberá permitir:

* localizar datos por cliente;
* exportar información;
* anonimizar información cuando corresponda;
* eliminar datos cuando sea legalmente posible;
* conservar los datos que deban mantenerse por obligación;
* registrar la solicitud y su resultado.

La política definitiva deberá alinearse con la normativa colombiana de protección de datos.

---

# 34. Restricciones de integridad

## INT-001 — Mensajes

```text
external_message_id debe ser único
```

## INT-002 — Visitas

No puede existir más de una visita activa para:

```text
fecha + hora + recurso
```

## INT-003 — Cotizaciones

```text
lead_id + version_number debe ser único
```

## INT-004 — Reservas

No puede existir una reserva confirmada sin pago confirmado.

## INT-005 — Handoff

Una conversación solo puede tener un asesor activo.

## INT-006 — Conocimiento

Una respuesta utilizada automáticamente debe estar aprobada y vigente.

## INT-007 — Reprogramaciones

Todo cambio confirmado debe crear registro histórico.

## INT-008 — Valores monetarios

Los valores monetarios no pueden ser negativos.

---

# 35. Índices funcionales recomendados

Deberán existir índices o mecanismos equivalentes para:

* cliente por teléfono;
* cliente por correo;
* conversación por cliente y estado;
* mensaje por identificador externo;
* lead por cliente y estado;
* evento por fecha;
* cita por fecha, hora y estado;
* solicitud de cotización por estado y vencimiento;
* cotización por lead y versión;
* pago por estado y fecha límite;
* handoff por estado, prioridad y asignación;
* respuesta de conocimiento por categoría y estado;
* auditoría por entidad e identificador.

---

# 36. Datos para métricas

El modelo deberá permitir calcular:

## Atención

* mensajes recibidos;
* mensajes respondidos;
* tiempo de primera respuesta;
* latencia;
* conversaciones resueltas.

## Comercial

* leads creados;
* leads calificados;
* presupuestos informados;
* solicitudes de cotización;
* cotizaciones enviadas;
* reservas confirmadas.

## Agenda

* visitas solicitadas;
* visitas confirmadas;
* cancelaciones;
* reprogramaciones;
* inasistencias;
* ocupación por horario.

## Handoff

* conversaciones escaladas;
* motivo;
* prioridad;
* tiempo de asignación;
* tiempo de resolución.

## IA

* ejecuciones;
* tokens;
* coste;
* latencia;
* confianza;
* errores;
* fallbacks.

---

# 37. Casos de uso relacionados por entidad

| Entidad        | Casos de uso principales               |
| -------------- | -------------------------------------- |
| Customer       | UC-001, UC-003                         |
| Lead           | UC-004, UC-006, UC-009                 |
| Event          | UC-005, UC-006, UC-007                 |
| Conversation   | UC-001, UC-008, UC-019, UC-032         |
| Message        | UC-001, UC-002, UC-028                 |
| QuoteRequest   | UC-009, UC-010                         |
| Quote          | UC-011, UC-012                         |
| Appointment    | UC-013, UC-014, UC-015, UC-016, UC-018 |
| Reservation    | UC-025, UC-026                         |
| Payment        | UC-023, UC-024                         |
| Handoff        | UC-019, UC-020, UC-021, UC-022, UC-027 |
| KnowledgeEntry | UC-002, UC-031                         |
| AIExecution    | UC-005, UC-006, UC-029                 |
| AuditEvent     | Todos los cambios críticos             |

---

# 38. Criterios de aceptación

La matriz de datos se considerará correctamente implementada cuando:

1. Un cliente pueda tener varios leads.
2. Un lead pueda tener un evento independiente.
3. La conversación no sea la única fuente de verdad.
4. Los mensajes sean inmutables.
5. Los mensajes duplicados no se procesen dos veces.
6. Los datos inferidos se diferencien de los confirmados.
7. Las correcciones conserven el valor anterior.
8. Las cotizaciones tengan versiones.
9. Las citas conserven reprogramaciones.
10. Los pagos requieran validación humana.
11. Las reservas solo se confirmen con pago validado.
12. Los servicios solicitados no se marquen automáticamente como incluidos.
13. Los datos sensibles tengan acceso restringido.
14. Los asesores no puedan ejecutar acciones sin permisos.
15. Las respuestas de conocimiento tengan aprobación y vigencia.
16. Las ejecuciones de IA queden trazables.
17. Toda operación crítica genere auditoría.
18. Las métricas puedan calcularse sin analizar manualmente los mensajes.
19. Los parámetros operativos sean configurables.
20. La estructura permita incorporar Instagram y cotizaciones automáticas.

---

# 39. Definición de terminado

La implementación de la matriz estará terminada cuando:

* exista el modelo lógico aprobado;
* exista un diagrama entidad-relación;
* exista un diccionario técnico;
* existan migraciones;
* existan restricciones de integridad;
* existan enumeraciones;
* existan índices;
* existan permisos;
* existan validadores;
* existan pruebas de persistencia;
* exista auditoría;
* exista una política de retención;
* exista documentación para datos sensibles;
* los casos de uso puedan ejecutarse con la información definida.

---

# 40. Aprobación

Este documento queda listo como fuente funcional para diseñar:

* `/docs/architecture/data-model.md`
* migraciones;
* repositorios;
* DTO;
* contratos de API;
* esquemas JSON;
* validadores;
* pruebas de integridad;
* políticas de privacidad.

Su aprobación implica que:

* los dominios principales están definidos;
* la obligatoriedad está especificada;
* los permisos están delimitados;
* los datos sensibles están identificados;
* la opción B del MVP puede implementarse;
* la futura opción A puede añadirse sin reemplazar el modelo central.
