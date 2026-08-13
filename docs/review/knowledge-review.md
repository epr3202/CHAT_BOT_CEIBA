# Revisión de base de conocimiento

Este documento lista la versión más reciente de cada respuesta aprobada o pendiente.

## REQUIEREN DECISIÓN

### RESP-FILE-002

- **Status:** DRAFT
- **Categoría:** Archivos y multimedia
- **Pregunta/resumen:** Comprobante
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Comprobante.

### RESP-DELIVERY-ERROR-001

- **Status:** DRAFT
- **Categoría:** Fallo de envío
- **Pregunta/resumen:** Uso interno
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Uso interno.

### RESP-AI-ERROR-004

- **Status:** DRAFT
- **Categoría:** Fallo de inteligencia artificial
- **Pregunta/resumen:** FAQ determinista
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: FAQ determinista.

### RESP-PAYMENT-004

- **Status:** DRAFT
- **Categoría:** Pago informado
- **Pregunta/resumen:** Pago confirmado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Tu pago fue confirmado y la fecha quedó oficialmente separada. Nuestro equipo continuará acompañándote con los siguientes pasos de tu evento.

### RESP-PAYMENT-005

- **Status:** DRAFT
- **Categoría:** Pago informado
- **Pregunta/resumen:** Pago rechazado
- **Variables requeridas:** rejection_reason_customer_safe
- **Respuesta aprobada:**

[REVISAR] No fue posible validar el pago con la información recibida. {rejection_reason_customer_safe} Nuestro equipo puede ayudarte a revisar el proceso.

### RESP-PRICE-005

- **Status:** DRAFT
- **Categoría:** Preguntas sobre precio
- **Pregunta/resumen:** Precio base publicado
- **Variables requeridas:** approved_price, package_name
- **Respuesta aprobada:**

[REVISAR] La experiencia {package_name} tiene un valor de referencia desde {approved_price}, bajo las condiciones indicadas. Para una propuesta personalizada debemos revisar la fecha, los invitados y los servicios.

### RESP-PRICE-006

- **Status:** DRAFT
- **Categoría:** Preguntas sobre precio
- **Pregunta/resumen:** Prohibiciones
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Prohibiciones.

### RESP-GEN-001

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Fuente autorizada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Fuente autorizada.

### RESP-GEN-002

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Adaptación permitida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Claro, Natalia. Las visitas se realizan de martes a sábado.
Claro que sí, Natalia. Podemos recibirte de martes a sábado.

### RESP-GEN-003

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Adaptación prohibida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Adaptación prohibida.

### RESP-GEN-004

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Respuesta breve
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Respuesta breve.

### RESP-GEN-005

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Variables
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Variables.

### RESP-GEN-006

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Valores faltantes
- **Variables requeridas:** visit_date, visit_time
- **Respuesta aprobada:**

[REVISAR] Te esperamos el {visit_date} a las {visit_time}.

### RESP-GEN-007

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** No exponer información interna
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: No exponer información interna.

### RESP-GEN-008

- **Status:** DRAFT
- **Categoría:** Principios de uso
- **Pregunta/resumen:** Mensajes sensibles
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Mensajes sensibles.

### RESP-COMPLAINT-006

- **Status:** DRAFT
- **Categoría:** Quejas
- **Pregunta/resumen:** Prohibiciones
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] Entrada sin texto aprobado enviable: Prohibiciones.

### RESP-RESERVATION-006

- **Status:** DRAFT
- **Categoría:** Reserva de fecha
- **Pregunta/resumen:** Estado reservado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] La fecha de tu evento se encuentra oficialmente reservada.

### RESP-FOLLOWUP-005

- **Status:** DRAFT
- **Categoría:** Seguimientos automáticos autorizados
- **Pregunta/resumen:** Prohibiciones
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

[REVISAR] sábado 8 de agosto de 2026
el sábado

### RESP-SERVICES-004

- **Status:** DRAFT
- **Categoría:** Servicios disponibles
- **Pregunta/resumen:** Servicio incluido en un paquete
- **Variables requeridas:** service_name
- **Respuesta aprobada:**

[REVISAR] Sí, {service_name} está incluido dentro de la propuesta seleccionada.

### RESP-SERVICES-005

- **Status:** DRAFT
- **Categoría:** Servicios disponibles
- **Pregunta/resumen:** Servicio no disponible
- **Variables requeridas:** service_name
- **Respuesta aprobada:**

[REVISAR] Para la fecha consultada, {service_name} no se encuentra disponible. Nuestro equipo puede ayudarte a revisar una alternativa.

### GAP

- **Entrada:** GAP: falta plantilla para confirmar intención tentativa (detectado en F4)
- **Status:** DRAFT
- **Decisión requerida:** crear una plantilla aprobada para pedir confirmación cuando la clasificación queda en banda tentativa.

## Accesibilidad

### RESP-ACCESSIBILITY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Hay alguna necesidad de accesibilidad que debamos tener en cuenta para recibirlos adecuadamente?

### RESP-ACCESSIBILITY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Requerimiento registrado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por contarnos. Registraremos esta necesidad para que el equipo pueda preparar la atención y confirmar las condiciones de acceso.

## Alergias y alimentación especial

### RESP-DIETARY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta autorizada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Alguno de los invitados tiene alergias o requerimientos alimentarios que debamos considerar?

### RESP-DIETARY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Alergia registrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por informarnos. Registraré este requerimiento para que el equipo lo tenga en cuenta al revisar el menú y las condiciones de preparación.

### RESP-DIETARY-003

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación humana
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestro equipo deberá confirmar las alternativas y condiciones disponibles para atender este requerimiento de manera adecuada.

## Alimentos externos

### RESP-FOOD-001

- **Status:** APPROVED
- **Pregunta/resumen:** Alimentos permitidos
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar alimentos externos. Su ingreso debe coordinarse previamente para organizar correctamente el servicio, almacenamiento y montaje.

### RESP-FOOD-002

- **Status:** APPROVED
- **Pregunta/resumen:** Catering externo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes trabajar con un servicio de catering externo. Necesitamos coordinar previamente sus horarios, necesidades técnicas y condiciones de ingreso.

### RESP-FOOD-003

- **Status:** APPROVED
- **Pregunta/resumen:** Responsabilidad
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Los alimentos suministrados por terceros deben cumplir las condiciones sanitarias y de manipulación correspondientes. La logística debe coordinarse previamente con nuestro equipo.

### RESP-FOOD-004

- **Status:** APPROVED
- **Pregunta/resumen:** Torta externa
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar la torta o productos de repostería externos. Recomendamos coordinar previamente el ingreso, almacenamiento y momento del servicio.

## Alojamiento

### RESP-ACCOMMODATION-001

- **Status:** APPROVED
- **Pregunta/resumen:** Información general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Contamos con opciones de alojamiento que pueden integrarse a algunas experiencias, incluida nuestra Suite Oasis. La disponibilidad y las condiciones deben confirmarse para la fecha del evento.

### RESP-ACCOMMODATION-002

- **Status:** APPROVED
- **Pregunta/resumen:** Disponibilidad pendiente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para confirmar el alojamiento necesitamos revisar la fecha, el número de huéspedes y la opción que deseas incluir.

### RESP-ACCOMMODATION-003

- **Status:** APPROVED
- **Pregunta/resumen:** No prometer inclusión
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El alojamiento no está incluido automáticamente en todos los eventos. Nuestro equipo podrá indicarte si puede integrarse a la propuesta.

## Archivos y multimedia

### RESP-FILE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Imagen de inspiración
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por compartir la referencia. La dejaré asociada a tu solicitud para que nuestro equipo pueda tenerla en cuenta al preparar la propuesta.

### RESP-FILE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Audio no soportado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por tu mensaje. En esta etapa podemos atenderte mejor mediante texto. También puedo compartir la conversación con un asesor.

### RESP-FILE-004

- **Status:** APPROVED
- **Pregunta/resumen:** Documento desconocido
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Recibimos el archivo. ¿Podrías contarnos brevemente qué información contiene o qué necesitas que revisemos?

### RESP-FILE-005

- **Status:** APPROVED
- **Pregunta/resumen:** Video
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por compartir el video. Lo dejaremos asociado a la conversación para que nuestro equipo pueda revisarlo.

### RESP-FILE-006

- **Status:** APPROVED
- **Pregunta/resumen:** Archivo inválido
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos procesar el archivo recibido. Puedes intentar enviarlo nuevamente o compartir la información por escrito.

## Asistentes y motivo de visita

### RESP-VISIT-DATA-001

- **Status:** APPROVED
- **Pregunta/resumen:** Cantidad de asistentes
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Cuántas personas asistirán a la visita? Podemos recibir hasta tres.

### RESP-VISIT-DATA-002

- **Status:** APPROVED
- **Pregunta/resumen:** Más de tres
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para las visitas podemos recibir hasta tres personas. ¿Podrían acompañarnos máximo tres asistentes o prefieres que el equipo revise una excepción?

### RESP-VISIT-DATA-003

- **Status:** APPROVED
- **Pregunta/resumen:** Motivo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿La visita es para conocer el lugar pensando en algún evento específico?

### RESP-VISIT-DATA-004

- **Status:** APPROVED
- **Pregunta/resumen:** Puntualidad
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La visita tiene una duración de 45 minutos. Te recomendamos llegar puntual para aprovecharla completamente, ya que debemos respetar los horarios de las siguientes citas.

## Atención humana

### RESP-HANDOFF-001

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud dentro del horario
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Claro. Voy a compartir tu conversación con nuestro equipo para que un asesor continúe contigo.

### RESP-HANDOFF-002

- **Status:** APPROVED
- **Pregunta/resumen:** Fuera del horario
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu solicitud quedó registrada. Un asesor continuará contigo dentro de nuestro horario de atención, de martes a sábado entre las 8:00 a. m. y las 4:00 p. m.

### RESP-HANDOFF-003

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de Leandro
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Voy a dejar tu solicitud registrada para Manager Leandro. El equipo revisará la conversación y continuará contigo según disponibilidad.

### RESP-HANDOFF-004

- **Status:** APPROVED
- **Pregunta/resumen:** Conversación ya escalada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu solicitud ya se encuentra registrada para atención humana. Nuestro equipo continuará contigo por este mismo medio.

### RESP-HANDOFF-005

- **Status:** APPROVED
- **Pregunta/resumen:** Asesor asignado
- **Variables requeridas:** advisor_name
- **Respuesta aprobada:**

{advisor_name} continuará contigo para revisar tu solicitud.

### RESP-HANDOFF-006

- **Status:** APPROVED
- **Pregunta/resumen:** Espera
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por tu paciencia. La conversación se encuentra pendiente de atención por parte de nuestro equipo.

## Baja confianza

### RESP-FALLBACK-001

- **Status:** APPROVED
- **Pregunta/resumen:** Primer fallo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Quiero asegurarme de entenderte bien. ¿Buscas información, solicitar una cotización, agendar una visita o hablar con un asesor?

### RESP-FALLBACK-002

- **Status:** APPROVED
- **Pregunta/resumen:** Segundo fallo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Aún no logro identificar exactamente lo que necesitas. Puedes contármelo nuevamente con tus palabras o pedir que te comuniquemos con un asesor.

### RESP-FALLBACK-003

- **Status:** APPROVED
- **Pregunta/resumen:** Tercer fallo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Voy a compartir tu conversación con nuestro equipo para que puedan ayudarte personalmente.

### RESP-FALLBACK-004

- **Status:** APPROVED
- **Pregunta/resumen:** Respuesta breve sin contexto
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Podrías contarme un poco más para entender a qué te refieres?

### RESP-FALLBACK-005

- **Status:** APPROVED
- **Pregunta/resumen:** Selección ambigua
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logro identificar cuál opción elegiste. ¿Podrías indicarme la hora o la opción exacta?

## Bebidas y licor

### RESP-BEVERAGES-001

- **Status:** APPROVED
- **Pregunta/resumen:** Bebidas externas
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar bebidas externas. Su ingreso debe coordinarse previamente con nuestro equipo.

### RESP-BEVERAGES-002

- **Status:** APPROVED
- **Pregunta/resumen:** Licor externo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar licor externo y no manejamos cobro de descorche. Solo necesitamos coordinar previamente el ingreso y el servicio.

### RESP-BEVERAGES-003

- **Status:** APPROVED
- **Pregunta/resumen:** Descorche
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No manejamos cobro de descorche. El ingreso de bebidas y licor debe coordinarse previamente con nuestro equipo.

### RESP-BEVERAGES-004

- **Status:** APPROVED
- **Pregunta/resumen:** Menores
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El servicio y consumo de bebidas alcohólicas deberá respetar las normas aplicables y no podrá incluir a menores de edad.

## Cafetería

### RESP-CAFE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Horario
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestra cafetería funciona inicialmente de martes a sábado, entre las 8:00 a. m. y las 12:00 m.

### RESP-CAFE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Permanencia después de la visita
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Al terminar la visita puedes permanecer en la cafetería para disfrutar un café o desayunar, según la disponibilidad del día.

### RESP-CAFE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Menú no confirmado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La oferta de la cafetería puede variar. Nuestro equipo puede confirmarte los productos disponibles para el día de tu visita.

## Cambio temporal de tema

### RESP-CONTEXT-001

- **Status:** APPROVED
- **Pregunta/resumen:** Retorno a cotización
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para continuar con la propuesta, ¿ya tienes una fecha definida?

### RESP-CONTEXT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Retorno a invitados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para seguir con la solicitud, ¿para cuántas personas aproximadamente estás planeando el evento?

### RESP-CONTEXT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Retorno a visita
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para continuar con la visita, ¿qué fecha te gustaría revisar?

### RESP-CONTEXT-004

- **Status:** APPROVED
- **Pregunta/resumen:** Retorno después de asesor
- **Variables requeridas:** pending_topic
- **Respuesta aprobada:**

Podemos continuar con la información que quedó pendiente. ¿Deseas seguir con {pending_topic}?

## Cancelación de evento

### RESP-CANCEL-EVENT-001

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación de intención
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Quiero asegurarme de entenderte correctamente. ¿Deseas solicitar la cancelación del evento reservado?

### RESP-CANCEL-EVENT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Un mes o más
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las solicitudes de cancelación realizadas con mínimo un mes de anticipación son revisadas directamente por nuestro equipo, de acuerdo con las condiciones de la reserva. Voy a trasladar tu solicitud a un asesor.

### RESP-CANCEL-EVENT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Menos de un mes
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

De acuerdo con nuestras condiciones, las cancelaciones realizadas con menos de un mes de anticipación no generan devolución. De todas formas, voy a compartir tu caso con nuestro equipo para que puedan orientarte.

### RESP-CANCEL-EVENT-004

- **Status:** APPROVED
- **Pregunta/resumen:** Emergencia o excepción
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Entendemos que pueden presentarse situaciones especiales. Nuestro equipo debe revisar directamente el caso y las condiciones de la reserva. Voy a trasladar tu solicitud.

### RESP-CANCEL-EVENT-005

- **Status:** APPROVED
- **Pregunta/resumen:** Cambio de fecha en lugar de cancelar
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Como el evento ya está asociado a una reserva, el cambio de fecha debe revisarlo directamente nuestro equipo. Voy a compartir tu solicitud con un asesor.

### RESP-CANCEL-EVENT-006

- **Status:** APPROVED
- **Pregunta/resumen:** Devolución solicitada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La decisión sobre una posible devolución debe ser revisada por un asesor autorizado, según la fecha y las condiciones de la reserva.

## Cancelación de visita

### RESP-CANCEL-VISIT-001

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación
- **Variables requeridas:** visit_date, visit_time
- **Respuesta aprobada:**

Tienes una visita programada para el {visit_date} a las {visit_time}. ¿Confirmas que deseas cancelarla?

### RESP-CANCEL-VISIT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Cancelación completada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu visita fue cancelada. Cuando lo desees, podemos ayudarte a revisar una nueva fecha.

### RESP-CANCEL-VISIT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente no confirma
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Perfecto, la visita continuará programada en la fecha y hora actuales.

### RESP-CANCEL-VISIT-004

- **Status:** APPROVED
- **Pregunta/resumen:** Error de cancelación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar la cancelación en este momento. Tu solicitud quedó registrada para revisión y te confirmaremos el resultado.

### RESP-CANCEL-VISIT-005

- **Status:** APPROVED
- **Pregunta/resumen:** Cita no encontrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logramos identificar una visita activa para cancelar. Voy a compartir tu solicitud con nuestro equipo.

## Capacidad

### RESP-CAPACITY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Capacidad general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La Ceiba es ideal para celebraciones íntimas de hasta aproximadamente 60 invitados. Para una experiencia más cómoda, recomendamos montajes de hasta 50 personas, dependiendo de la distribución y los servicios del evento.

### RESP-CAPACITY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Terraza
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestra Terraza La Ceiba puede recibir cómodamente alrededor de 50 invitados. Según el montaje, es posible evaluar una capacidad máxima aproximada de 60 personas.

### RESP-CAPACITY-003

- **Status:** APPROVED
- **Pregunta/resumen:** Salones
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Contamos con dos salones interiores, cada uno ideal para aproximadamente 15 personas. Dependiendo del montaje, pueden utilizarse en conjunto para grupos cercanos a 30 invitados.

### RESP-CAPACITY-004

- **Status:** APPROVED
- **Pregunta/resumen:** Quiosco
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El Quiosco de la Piscina es ideal para una experiencia más relajada de aproximadamente 20 personas, según el montaje.

### RESP-CAPACITY-005

- **Status:** APPROVED
- **Pregunta/resumen:** Más de 60 invitados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para esa cantidad de invitados necesitamos revisar cuidadosamente la distribución y el tipo de montaje. Voy a compartir la información con nuestro equipo para confirmar qué alternativa podemos ofrecerte.

### RESP-CAPACITY-006

- **Status:** APPROVED
- **Pregunta/resumen:** Uso combinado de espacios
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos combinar diferentes zonas de La Ceiba según la experiencia que estés planeando. La capacidad total debe revisarse con base en la distribución, la circulación y los servicios del evento.

## Confirmación de visita

### RESP-VISIT-CONFIRM-001

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen
- **Variables requeridas:** event_type, visit_attendee_count, visit_date, visit_time
- **Respuesta aprobada:**

Confirmemos tu visita: {visit_date} a las {visit_time}, para conocer el espacio pensando en {event_type}, con {visit_attendee_count} asistentes. ¿Deseas que la agendemos?

### RESP-VISIT-CONFIRM-002

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen sin evento
- **Variables requeridas:** visit_attendee_count, visit_date, visit_time
- **Respuesta aprobada:**

Confirmemos tu visita: {visit_date} a las {visit_time}, con {visit_attendee_count} asistentes. ¿Deseas que la agendemos?

### RESP-VISIT-CONFIRM-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cita confirmada
- **Variables requeridas:** visit_date, visit_time
- **Respuesta aprobada:**

¡Tu visita quedó confirmada! Te esperamos el {visit_date} a las {visit_time} en la Calle 71 #52-34, Lagos del Cacique. La visita dura 45 minutos y un día antes te enviaremos un recordatorio.

### RESP-VISIT-CONFIRM-004

- **Status:** APPROVED
- **Pregunta/resumen:** Con mapa
- **Variables requeridas:** map_url, visit_date, visit_time
- **Respuesta aprobada:**

¡Tu visita quedó confirmada! Te esperamos el {visit_date} a las {visit_time}. Puedes consultar la ubicación aquí: {map_url}. La visita dura 45 minutos y te recomendamos llegar puntual.

### RESP-VISIT-CONFIRM-005

- **Status:** APPROVED
- **Pregunta/resumen:** Conflicto al confirmar
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Ese horario acaba de dejar de estar disponible. Lo siento. Puedo ofrecerte las demás opciones disponibles para ese día.

### RESP-VISIT-CONFIRM-006

- **Status:** APPROVED
- **Pregunta/resumen:** Error de creación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar la confirmación de la visita en este momento. Tu solicitud quedó registrada y nuestro equipo continuará contigo.

## Cotización en manos de asesor

### RESP-ADVISOR-QUOTE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Datos recibidos
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Perfecto, ya tenemos la información principal de tu celebración. Nuestro equipo la revisará para preparar una propuesta acorde con lo que estás buscando.

### RESP-ADVISOR-QUOTE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Información pendiente
- **Variables requeridas:** missing_field
- **Respuesta aprobada:**

Para que el asesor pueda preparar correctamente la propuesta, todavía necesitamos conocer {missing_field}.

### RESP-ADVISOR-QUOTE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud especial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Esa solicitud requiere una revisión personalizada. Voy a dejarla registrada para que el asesor la tenga en cuenta al preparar la propuesta.

## Datos del evento

### RESP-EVENT-DATA-001

- **Status:** APPROVED
- **Pregunta/resumen:** Fecha
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Ya tienes una fecha definida o todavía es flexible?

### RESP-EVENT-DATA-002

- **Status:** APPROVED
- **Pregunta/resumen:** Mes aproximado
- **Variables requeridas:** event_month
- **Respuesta aprobada:**

Perfecto, podemos tomar {event_month} como referencia. ¿Para cuántas personas aproximadamente estás planeando el evento?

### RESP-EVENT-DATA-003

- **Status:** APPROVED
- **Pregunta/resumen:** Fecha relativa
- **Variables requeridas:** resolved_date
- **Respuesta aprobada:**

¿Te refieres al {resolved_date}?

### RESP-EVENT-DATA-004

- **Status:** APPROVED
- **Pregunta/resumen:** Invitados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Para cuántas personas aproximadamente estás planeando la celebración?

### RESP-EVENT-DATA-005

- **Status:** APPROVED
- **Pregunta/resumen:** Rango de invitados
- **Variables requeridas:** guest_count_range
- **Respuesta aprobada:**

Perfecto, registraré un estimado de {guest_count_range} invitados.

### RESP-EVENT-DATA-006

- **Status:** APPROVED
- **Pregunta/resumen:** Servicios
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Buscas principalmente el espacio o te gustaría una experiencia más completa con gastronomía, decoración, bebidas u otros servicios?

### RESP-EVENT-DATA-007

- **Status:** APPROVED
- **Pregunta/resumen:** Detalle especial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Hay algún detalle especial que quieras que nuestro equipo tenga en cuenta?

### RESP-EVENT-DATA-008

- **Status:** APPROVED
- **Pregunta/resumen:** Corrección de invitados
- **Variables requeridas:** guest_count
- **Respuesta aprobada:**

Perfecto, actualicé la cantidad estimada a {guest_count} invitados.

### RESP-EVENT-DATA-009

- **Status:** APPROVED
- **Pregunta/resumen:** Corrección de fecha
- **Variables requeridas:** event_date
- **Respuesta aprobada:**

Entendido, actualicé la fecha del evento para el {event_date}.

### RESP-EVENT-DATA-010

- **Status:** APPROVED
- **Pregunta/resumen:** Corrección de tipo
- **Variables requeridas:** event_type
- **Respuesta aprobada:**

Perfecto, actualicé el tipo de celebración a {event_type}.

### RESP-EVENT-DATA-011

- **Status:** APPROVED
- **Pregunta/resumen:** Servicio retirado
- **Variables requeridas:** service_name
- **Respuesta aprobada:**

Entendido, retiré {service_name} de los servicios solicitados.

### RESP-EVENT-DATA-012

- **Status:** APPROVED
- **Pregunta/resumen:** Datos contradictorios
- **Variables requeridas:** adult_guest_count, child_guest_count, total_guest_count
- **Respuesta aprobada:**

Gracias por aclararlo. Registraré {adult_guest_count} adultos y {child_guest_count} niños, para un total aproximado de {total_guest_count} invitados. ¿Está correcto?

## Descuentos y negociación

### RESP-NEGOTIATION-001

- **Status:** APPROVED
- **Pregunta/resumen:** Descuento
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestro equipo comercial revisa directamente las condiciones especiales y las posibles alternativas de cada propuesta. Voy a compartir tu solicitud con un asesor.

### RESP-NEGOTIATION-002

- **Status:** APPROVED
- **Pregunta/resumen:** Presupuesto menor
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por compartirnos tu presupuesto. Nuestro equipo revisará qué alternativa puede ajustarse mejor a lo que estás buscando.

### RESP-NEGOTIATION-003

- **Status:** APPROVED
- **Pregunta/resumen:** Pago por cuotas
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las condiciones de pago especiales deben revisarse directamente con un asesor. Voy a dejar tu solicitud registrada.

### RESP-NEGOTIATION-004

- **Status:** APPROVED
- **Pregunta/resumen:** Intercambio
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las propuestas de colaboración o intercambio son revisadas directamente por Manager Leandro. Voy a registrar la información para evaluación.

## Despedidas y cierre

### RESP-FAREWELL-001

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta resuelta
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Con mucho gusto. Cuando quieras planear una celebración o conocer La Ceiba, estaremos encantados de ayudarte.

### RESP-FAREWELL-002

- **Status:** APPROVED
- **Pregunta/resumen:** Pausa
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Claro. La información que ya compartiste quedará registrada para que podamos continuar cuando lo desees.

### RESP-FAREWELL-003

- **Status:** APPROVED
- **Pregunta/resumen:** Después de solicitud
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Con gusto. Tu solicitud quedó registrada y nuestro equipo continuará con el proceso correspondiente.

### RESP-FAREWELL-004

- **Status:** APPROVED
- **Pregunta/resumen:** Después de visita
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Será un gusto recibirte. Quedamos atentos si necesitas modificar o complementar la información de la visita.

## Emergencias

### RESP-EMERGENCY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Emergencia médica
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Contacta inmediatamente al personal presente en La Ceiba y a los servicios de emergencia. Voy a alertar al equipo responsable ahora mismo.

### RESP-EMERGENCY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Incidente de seguridad
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Comunícate inmediatamente con el personal presente y aléjate de cualquier situación de riesgo. Ya estamos alertando al equipo responsable.

### RESP-EMERGENCY-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente en la entrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la situación. Ya estamos alertando al equipo responsable para que puedan atenderte lo antes posible.

### RESP-EMERGENCY-004

- **Status:** APPROVED
- **Pregunta/resumen:** Problema sanitario
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Informa inmediatamente al personal presente y evita consumir o servir el producto relacionado. Ya estamos alertando al equipo responsable para revisar la situación.

### RESP-EMERGENCY-005

- **Status:** APPROVED
- **Pregunta/resumen:** Evento próximo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Entendemos la urgencia. Tu evento está programado dentro de las próximas 72 horas y ya estamos trasladando la solicitud con prioridad a nuestro equipo.

### RESP-EMERGENCY-006

- **Status:** APPROVED
- **Pregunta/resumen:** Posible doble reserva
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Vamos a revisar esta situación de manera inmediata. Tu caso ya fue marcado como prioritario y trasladado a Manager Leandro.

### RESP-EMERGENCY-007

- **Status:** APPROVED
- **Pregunta/resumen:** Error de pago o reserva
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Vamos a revisar la inconsistencia con prioridad. La conversación y los registros relacionados ya fueron trasladados al equipo responsable.

## Espacios

### RESP-SPACES-001

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen de espacios
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Contamos con la Terraza La Ceiba, dos salones interiores y el Quiosco de la Piscina. La mejor opción depende del tipo de evento, la cantidad de invitados y el montaje que quieras realizar.

### RESP-SPACES-002

- **Status:** APPROVED
- **Pregunta/resumen:** Recomendación condicionada
- **Variables requeridas:** event_type, guest_count
- **Respuesta aprobada:**

Para {event_type} de aproximadamente {guest_count} personas, nuestro equipo puede revisar cuál espacio se adapta mejor al montaje y a los servicios que deseas incluir.

### RESP-SPACES-003

- **Status:** APPROVED
- **Pregunta/resumen:** Espacio interior
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, contamos con espacios interiores que pueden utilizarse para reuniones y celebraciones íntimas, además de servir como alternativa según las condiciones del evento.

### RESP-SPACES-004

- **Status:** APPROVED
- **Pregunta/resumen:** Pista de baile o montaje especial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos revisar una distribución con pista de baile o zonas diferenciadas. La capacidad final dependerá del mobiliario, la decoración y los demás servicios del montaje.

## Estado de cotización

### RESP-QUOTE-STATUS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Borrador
- **Variables requeridas:** missing_field
- **Respuesta aprobada:**

Aún faltan algunos datos para completar la solicitud. Quedamos pendientes de {missing_field}.

### RESP-QUOTE-STATUS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Registrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu solicitud ya está registrada y se encuentra pendiente de revisión por nuestro equipo. El plazo informado es de hasta tres días hábiles.

### RESP-QUOTE-STATUS-003

- **Status:** APPROVED
- **Pregunta/resumen:** Asignada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu solicitud ya fue asignada a un asesor y se encuentra en proceso de preparación.

### RESP-QUOTE-STATUS-004

- **Status:** APPROVED
- **Pregunta/resumen:** En preparación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestro equipo se encuentra preparando tu propuesta. Te la compartiremos por este mismo medio.

### RESP-QUOTE-STATUS-005

- **Status:** APPROVED
- **Pregunta/resumen:** Enviada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La propuesta ya fue preparada y enviada. Podemos ayudarte a revisar cualquier duda o comunicarte con el asesor responsable.

### RESP-QUOTE-STATUS-006

- **Status:** APPROVED
- **Pregunta/resumen:** Vencida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la espera. Tu propuesta superó el tiempo previsto y vamos a revisar el caso con prioridad. Ya notificamos a nuestro equipo comercial.

### RESP-QUOTE-STATUS-007

- **Status:** APPROVED
- **Pregunta/resumen:** No encontrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logramos localizar una solicitud activa con la información disponible. Voy a compartir tu consulta con nuestro equipo para que puedan revisarla.

## Fallo de calendario

### RESP-CALENDAR-ERROR-001

- **Status:** APPROVED
- **Pregunta/resumen:** Consulta
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

En este momento no pudimos consultar la disponibilidad de visitas. Tu solicitud quedó registrada para que nuestro equipo pueda ayudarte.

### RESP-CALENDAR-ERROR-002

- **Status:** APPROVED
- **Pregunta/resumen:** Creación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar la confirmación de la visita en este momento. Tu solicitud quedó registrada y nuestro equipo continuará contigo.

### RESP-CALENDAR-ERROR-003

- **Status:** APPROVED
- **Pregunta/resumen:** Reprogramación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar el cambio de la visita. Tu cita actual se mantiene mientras nuestro equipo revisa la solicitud.

### RESP-CALENDAR-ERROR-004

- **Status:** APPROVED
- **Pregunta/resumen:** Cancelación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos confirmar la cancelación en este momento. Tu solicitud quedó registrada y te informaremos cuando el proceso sea verificado.

## Fallo de inteligencia artificial

### RESP-AI-ERROR-001

- **Status:** APPROVED
- **Pregunta/resumen:** Mensaje neutro
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

En este momento no logramos procesar completamente tu solicitud. Tu mensaje quedó registrado y nuestro equipo podrá continuar contigo.

### RESP-AI-ERROR-002

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de reformulación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logramos interpretar completamente el mensaje. ¿Podrías escribirlo nuevamente de otra forma?

### RESP-AI-ERROR-003

- **Status:** APPROVED
- **Pregunta/resumen:** Operación crítica
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar esta operación de forma segura. Tu solicitud quedó registrada para revisión por parte de nuestro equipo.

## Horario de eventos

### RESP-EVENT-HOURS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Horario habitual
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestro horario habitual de eventos se extiende hasta las 10:00 p. m.

### RESP-EVENT-HOURS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de extensión
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Si necesitas una duración diferente, nuestro equipo debe revisar la disponibilidad, el personal requerido y las condiciones especiales del evento.

### RESP-EVENT-HOURS-003

- **Status:** APPROVED
- **Pregunta/resumen:** No existen horarios ilimitados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El horario final se establece dentro de la propuesta y de las condiciones acordadas para el evento.

## Identificación de la necesidad

### RESP-DISCOVERY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta inicial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Qué tipo de celebración o experiencia estás planeando?

### RESP-DISCOVERY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Opciones generales
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Puedo ayudarte con información sobre nuestros espacios, solicitar una cotización, revisar una visita o comunicarte con un asesor. ¿Qué deseas hacer?

### RESP-DISCOVERY-003

- **Status:** APPROVED
- **Pregunta/resumen:** Evento e invitados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para orientarte mejor, cuéntame qué tipo de celebración estás planeando y para cuántas personas aproximadamente.

### RESP-DISCOVERY-004

- **Status:** APPROVED
- **Pregunta/resumen:** Evento desconocido
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nos encantará conocer mejor la idea. ¿Podrías contarme brevemente en qué consiste el evento y cuántas personas participarían?

## Identificación del cliente

### RESP-CUSTOMER-001

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de nombre
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Antes de continuar, ¿con quién tenemos el gusto?

### RESP-CUSTOMER-002

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación de nombre
- **Variables requeridas:** customer_name
- **Respuesta aprobada:**

Gracias, {customer_name}. Continuemos con los detalles de tu celebración.

### RESP-CUSTOMER-003

- **Status:** APPROVED
- **Pregunta/resumen:** Nombre ambiguo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Quiero asegurarme de registrar correctamente tus datos. ¿Cuál es tu nombre?

### RESP-CUSTOMER-004

- **Status:** APPROVED
- **Pregunta/resumen:** Correo electrónico
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿A qué correo electrónico deseas que enviemos la información?

### RESP-CUSTOMER-005

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación de correo
- **Variables requeridas:** email
- **Respuesta aprobada:**

Perfecto. Enviaremos la información a {email}. ¿Está correcto?

## Inasistencia

### RESP-NO-SHOW-001

- **Status:** APPROVED
- **Pregunta/resumen:** Primera inasistencia
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Hola, notamos que no pudiste acompañarnos en la visita programada. Esperamos que todo esté bien. Cuando lo desees, podemos ayudarte a revisar una nueva fecha.

### RESP-NO-SHOW-002

- **Status:** APPROVED
- **Pregunta/resumen:** Nueva solicitud después de reincidencia
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos ayudarte a revisar una nueva fecha. Antes de confirmarla, nuestro equipo verificará contigo la disponibilidad y las condiciones de la visita.

## Información general de visitas

### RESP-VISIT-001

- **Status:** APPROVED
- **Pregunta/resumen:** Horarios
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las visitas se realizan de martes a sábado a las 8:00, 9:00, 10:00 y 11:00 de la mañana.

### RESP-VISIT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Reglas completas
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las visitas se realizan de martes a sábado a las 8:00, 9:00, 10:00 y 11:00 de la mañana. Duran 45 minutos, admiten hasta tres personas y deben programarse con mínimo tres días de anticipación.

### RESP-VISIT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de fecha
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿Qué fecha te gustaría revisar?

### RESP-VISIT-004

- **Status:** APPROVED
- **Pregunta/resumen:** Mismo día
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para organizar adecuadamente la atención, las visitas deben programarse con mínimo tres días de anticipación. Puedo ayudarte a revisar una fecha posterior.

### RESP-VISIT-005

- **Status:** APPROVED
- **Pregunta/resumen:** Día siguiente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las visitas deben programarse con mínimo tres días de anticipación. Puedo ayudarte a revisar una fecha posterior disponible.

### RESP-VISIT-006

- **Status:** APPROVED
- **Pregunta/resumen:** Lunes o domingo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las visitas se realizan de martes a sábado. Puedo ayudarte a revisar el siguiente día disponible.

### RESP-VISIT-007

- **Status:** APPROVED
- **Pregunta/resumen:** Festivo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Ese día no tenemos visitas programadas por ser festivo. Puedo mostrarte otras fechas disponibles.

### RESP-VISIT-008

- **Status:** APPROVED
- **Pregunta/resumen:** Fecha bloqueada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Esa fecha no se encuentra habilitada para visitas. Puedo ayudarte a revisar otra opción cercana.

### RESP-VISIT-009

- **Status:** APPROVED
- **Pregunta/resumen:** Día completo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Ese día ya completó la disponibilidad de visitas. Puedo ayudarte a revisar otra fecha cercana.

### RESP-VISIT-010

- **Status:** APPROVED
- **Pregunta/resumen:** Calendario no disponible
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

En este momento no pudimos consultar la disponibilidad de visitas. Tu solicitud quedó registrada para que nuestro equipo pueda ayudarte.

## Mascotas

### RESP-PETS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Política general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, somos un espacio pet friendly. Las mascotas deben permanecer acompañadas y bajo el cuidado de sus responsables durante toda la visita o el evento.

### RESP-PETS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Varias mascotas
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos recibir mascotas, pero necesitamos conocer cuántas asistirán para revisar la logística y garantizar una experiencia cómoda para todos.

### RESP-PETS-003

- **Status:** APPROVED
- **Pregunta/resumen:** Condiciones
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las mascotas deben tener un comportamiento adecuado, permanecer supervisadas y no afectar la seguridad o comodidad de los demás invitados.

## Medios de pago

### RESP-PAYMENT-METHODS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Métodos aceptados
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Puedes realizar el pago mediante transferencia, efectivo, tarjeta, Nequi, Daviplata o enlace de pago. Nuestro equipo te compartirá los datos oficiales correspondientes.

### RESP-PAYMENT-METHODS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Datos de pago
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Los datos específicos de pago serán compartidos por un asesor o mediante un enlace oficial.

### RESP-PAYMENT-METHODS-003

- **Status:** APPROVED
- **Pregunta/resumen:** Seguridad
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Por seguridad, realiza el pago únicamente utilizando los datos o enlaces oficiales enviados por nuestro equipo.

## Modificación de cotización

### RESP-QUOTE-CHANGE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Cambio registrado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Perfecto, registré el cambio solicitado. Nuestro equipo revisará cómo afecta la propuesta y preparará una nueva versión cuando corresponda.

### RESP-QUOTE-CHANGE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Nueva versión requerida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Como la propuesta ya había sido enviada, este cambio requiere una nueva versión. Voy a compartir la solicitud con el asesor responsable.

### RESP-QUOTE-CHANGE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Descuento
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Nuestro equipo comercial revisa directamente las condiciones especiales y las posibles alternativas de cada propuesta. Voy a compartir tu solicitud con un asesor.

### RESP-QUOTE-CHANGE-004

- **Status:** APPROVED
- **Pregunta/resumen:** Negociación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos revisar contigo las alternativas de la propuesta. La negociación y cualquier ajuste de precio deben ser atendidos por un asesor autorizado.

### RESP-QUOTE-CHANGE-005

- **Status:** APPROVED
- **Pregunta/resumen:** Colaboración o intercambio
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las colaboraciones, intercambios y condiciones especiales son revisados directamente por Manager Leandro. Voy a dejar tu propuesta registrada para evaluación.

## Múltiples intenciones

### RESP-MULTI-001

- **Status:** APPROVED
- **Pregunta/resumen:** Cotización y visita
- **Variables requeridas:** event_type, guest_count
- **Respuesta aprobada:**

Claro, ya registré que estás planeando {event_type} para {guest_count} personas. Sobre la visita, necesitamos programarla con mínimo tres días de anticipación. ¿Qué fecha posterior te gustaría revisar?

### RESP-MULTI-002

- **Status:** APPROVED
- **Pregunta/resumen:** Ubicación y precio
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Estamos en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga. Sobre el valor, depende de la fecha, la cantidad de invitados y los servicios. ¿Para cuántas personas aproximadamente estás planeando el evento?

### RESP-MULTI-003

- **Status:** APPROVED
- **Pregunta/resumen:** Pago y queja
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la demora. Vamos a revisar la validación de tu pago con prioridad. Tu conversación ya fue trasladada al equipo responsable.

## Niños

### RESP-CHILDREN-001

- **Status:** APPROVED
- **Pregunta/resumen:** Tarifa
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El valor para los niños depende de su edad, del menú y de los servicios que requieran. Para incluirlos correctamente en la propuesta, cuéntanos cuántos niños asistirían y sus edades aproximadas.

### RESP-CHILDREN-002

- **Status:** APPROVED
- **Pregunta/resumen:** Capacidad
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Los niños también deben incluirse dentro de la cantidad total de asistentes para organizar correctamente el espacio.

### RESP-CHILDREN-003

- **Status:** APPROVED
- **Pregunta/resumen:** Menú infantil
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos revisar opciones para niños según sus edades y las características del menú. El asesor incluirá la alternativa correspondiente en la propuesta.

## Pago informado

### RESP-PAYMENT-001

- **Status:** APPROVED
- **Pregunta/resumen:** “Ya pagué”
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias. Para verificarlo, puedes compartirnos el comprobante o la referencia del pago. Nuestro equipo realizará la validación y te dará confirmación en un plazo máximo de un día.

### RESP-PAYMENT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Comprobante recibido
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias, recibimos la información de tu pago. Nuestro equipo realizará la validación y te dará confirmación en un plazo máximo de un día. La fecha quedará oficialmente separada cuando la verificación sea aprobada.

### RESP-PAYMENT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Pago en revisión
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La información del pago se encuentra en validación. La fecha quedará oficialmente reservada cuando nuestro equipo confirme la recepción del abono.

### RESP-PAYMENT-006

- **Status:** APPROVED
- **Pregunta/resumen:** Pago no localizado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Aún no hemos podido identificar el pago. Nuestro equipo continuará revisando la referencia y te informará cuando tenga una actualización.

### RESP-PAYMENT-007

- **Status:** APPROVED
- **Pregunta/resumen:** Pago duplicado o problema
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Vamos a revisar el inconveniente con prioridad. Tu caso ya fue trasladado al equipo responsable para validar los movimientos y continuar contigo.

### RESP-PAYMENT-008

- **Status:** APPROVED
- **Pregunta/resumen:** Datos sensibles
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Por seguridad, no compartas números completos de tarjeta, claves, PIN ni códigos de verificación por este chat. Nuestro equipo puede enviarte un medio de pago autorizado.

## Parqueadero

### RESP-PARKING-001

- **Status:** APPROVED
- **Pregunta/resumen:** Información general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, contamos con parqueadero para nuestros clientes e invitados. La disponibilidad depende de la cantidad de asistentes y del montaje del evento.

### RESP-PARKING-002

- **Status:** APPROVED
- **Pregunta/resumen:** Cantidad no confirmada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La capacidad del parqueadero puede variar según la operación y el montaje del evento. Para un grupo específico, nuestro equipo puede revisar las recomendaciones de acceso.

## Piscina

### RESP-POOL-001

- **Status:** APPROVED
- **Pregunta/resumen:** Piscina incluida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, la piscina hace parte de la experiencia de nuestros eventos y puede utilizarse dentro del horario contratado, siguiendo las condiciones de seguridad del lugar.

### RESP-POOL-002

- **Status:** APPROVED
- **Pregunta/resumen:** Uso por niños
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Los niños pueden utilizar la piscina bajo la supervisión permanente de sus responsables y siguiendo las indicaciones de seguridad de La Ceiba.

### RESP-POOL-003

- **Status:** APPROVED
- **Pregunta/resumen:** Clima u operación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

El uso efectivo de la piscina está sujeto a las condiciones climáticas, de seguridad y de operación del día.

### RESP-POOL-004

- **Status:** APPROVED
- **Pregunta/resumen:** Uso fuera del horario
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La piscina puede utilizarse dentro del horario contratado para el evento. Cualquier extensión debe revisarse previamente con nuestro equipo.

## Preguntas sobre precio

### RESP-PRICE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Precio general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Cada evento en La Ceiba se diseña de manera personalizada. El valor depende principalmente de la fecha, la cantidad de invitados y los servicios que quieras incluir. ¿Qué tipo de celebración estás planeando y para cuántas personas aproximadamente?

### RESP-PRICE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Precio por persona
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos estructurar algunas experiencias por persona, pero el valor depende del menú, las bebidas, el montaje y los servicios adicionales. ¿Para cuántos invitados y qué tipo de evento estás consultando?

### RESP-PRICE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente insiste
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Entiendo que quieras tener una referencia. En esta primera etapa, nuestras propuestas son preparadas por un asesor para que el valor corresponda realmente a tu celebración. Con la fecha, el tipo de evento y la cantidad de invitados podemos dejar la solicitud lista.

### RESP-PRICE-004

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente no entrega información
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Claro. Cuando tengas más detalles, estaremos encantados de ayudarte. También puedes solicitar hablar directamente con uno de nuestros asesores.

## Presupuesto

### RESP-BUDGET-001

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta de presupuesto
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para recomendarte una experiencia acorde con lo que imaginas, ¿tienes un presupuesto aproximado destinado a la celebración?

### RESP-BUDGET-002

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente no desea compartirlo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No hay problema. Podemos continuar con los demás detalles y nuestro equipo te orientará.

### RESP-BUDGET-003

- **Status:** APPROVED
- **Pregunta/resumen:** Presupuesto inferior al referente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Gracias por compartirnos tu presupuesto. Nuestro equipo revisará qué alternativa puede ajustarse mejor a lo que estás buscando.

### RESP-BUDGET-004

- **Status:** APPROVED
- **Pregunta/resumen:** Presupuesto igual o superior al referente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Perfecto, gracias por compartirnos ese rango. Esto ayudará a nuestro equipo a preparar una propuesta más alineada con lo que buscas.

### RESP-BUDGET-005

- **Status:** APPROVED
- **Pregunta/resumen:** Presupuesto ambiguo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para registrarlo correctamente, ¿ese valor corresponde al presupuesto total del evento o al valor por persona?

### RESP-BUDGET-006

- **Status:** APPROVED
- **Pregunta/resumen:** Moneda ambigua
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¿El presupuesto que mencionas está expresado en pesos colombianos?

## Proveedores externos

### RESP-SUPPLIERS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Proveedores permitidos
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes trabajar con proveedores externos y no cobramos un cargo general por su ingreso. Solo necesitamos coordinar previamente sus horarios y condiciones de acceso.

### RESP-SUPPLIERS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Fotógrafo externo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar tu propio fotógrafo. Solo necesitamos coordinar previamente su ingreso y el horario de trabajo.

### RESP-SUPPLIERS-003

- **Status:** APPROVED
- **Pregunta/resumen:** DJ o músico externo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes llevar tu propio DJ o músico. Antes del evento debemos revisar horarios, montaje, necesidades eléctricas y condiciones de sonido.

### RESP-SUPPLIERS-004

- **Status:** APPROVED
- **Pregunta/resumen:** Decorador externo
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Sí, puedes trabajar con un decorador externo. Su montaje y desmontaje deben coordinarse previamente con el equipo de La Ceiba.

### RESP-SUPPLIERS-005

- **Status:** APPROVED
- **Pregunta/resumen:** Información pendiente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Para confirmar las condiciones de ese proveedor necesitamos revisar los detalles del servicio y la fecha del evento. Voy a dejar la consulta registrada para nuestro equipo.

## Quejas

### RESP-COMPLAINT-001

- **Status:** APPROVED
- **Pregunta/resumen:** Queja general
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos que estés pasando por esta situación. Queremos revisar tu caso con la atención que merece. Voy a trasladar la conversación a nuestro equipo responsable.

### RESP-COMPLAINT-002

- **Status:** APPROVED
- **Pregunta/resumen:** Falta de respuesta
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la demora. Vamos a revisar tu solicitud con prioridad y ya estamos notificando al equipo responsable.

### RESP-COMPLAINT-003

- **Status:** APPROVED
- **Pregunta/resumen:** Pago sin confirmar
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la espera. Vamos a revisar la validación de tu pago con prioridad. Tu conversación ya fue trasladada al equipo responsable.

### RESP-COMPLAINT-004

- **Status:** APPROVED
- **Pregunta/resumen:** Error de cotización
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Lamentamos la inconsistencia. Nuestro equipo revisará la propuesta y los datos registrados para darte una respuesta correcta.

### RESP-COMPLAINT-005

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud de devolución
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Entendemos tu solicitud. La revisión de una devolución o compensación debe realizarla directamente el equipo responsable según las condiciones del caso.

## Recordatorio de visita

### RESP-REMINDER-001

- **Status:** APPROVED
- **Pregunta/resumen:** Recordatorio completo
- **Variables requeridas:** customer_name, map_url, visit_date, visit_time
- **Respuesta aprobada:**

Hola, {customer_name}. Te recordamos tu visita a La Ceiba mañana, {visit_date}, a las {visit_time}. Estamos en la Calle 71 #52-34, Lagos del Cacique. Puedes ver la ubicación aquí: {map_url}. La visita dura 45 minutos y te recomendamos llegar puntual. Si necesitas cancelar o reprogramar, puedes escribirnos por este medio.

### RESP-REMINDER-002

- **Status:** APPROVED
- **Pregunta/resumen:** Sin nombre
- **Variables requeridas:** visit_date, visit_time
- **Respuesta aprobada:**

Te recordamos tu visita a La Ceiba mañana, {visit_date}, a las {visit_time}. La visita dura 45 minutos y te recomendamos llegar puntual.

## Reprogramación de visita

### RESP-RESCHEDULE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Identificación de cita
- **Variables requeridas:** visit_date, visit_time
- **Respuesta aprobada:**

Actualmente tienes una visita programada para el {visit_date} a las {visit_time}. ¿Qué nueva fecha te gustaría revisar?

### RESP-RESCHEDULE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Varias citas
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Encontramos más de una visita asociada a tus datos. ¿Cuál de ellas deseas reprogramar?

### RESP-RESCHEDULE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Confirmación del cambio
- **Variables requeridas:** new_visit_date, new_visit_time
- **Respuesta aprobada:**

La visita quedará reprogramada para el {new_visit_date} a las {new_visit_time}. ¿Confirmas el cambio?

### RESP-RESCHEDULE-004

- **Status:** APPROVED
- **Pregunta/resumen:** Reprogramación exitosa
- **Variables requeridas:** new_visit_date, new_visit_time
- **Respuesta aprobada:**

Tu visita quedó reprogramada para el {new_visit_date} a las {new_visit_time}. Te enviaremos un recordatorio un día antes.

### RESP-RESCHEDULE-005

- **Status:** APPROVED
- **Pregunta/resumen:** Fallo de reprogramación
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No pudimos completar el cambio de la visita en este momento. Tu cita actual se mantiene y nuestro equipo revisará la solicitud.

### RESP-RESCHEDULE-006

- **Status:** APPROVED
- **Pregunta/resumen:** Cita no encontrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logramos identificar una visita activa con la información disponible. Voy a compartir tu solicitud con nuestro equipo para que puedan revisarla.

## Reserva de fecha

### RESP-RESERVATION-001

- **Status:** APPROVED
- **Pregunta/resumen:** Porcentaje
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La fecha se separa con un abono correspondiente al 50 % del valor acordado.

### RESP-RESERVATION-002

- **Status:** APPROVED
- **Pregunta/resumen:** Condición de reserva
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La fecha queda oficialmente reservada cuando nuestro equipo confirma la recepción del abono correspondiente.

### RESP-RESERVATION-003

- **Status:** APPROVED
- **Pregunta/resumen:** No bloqueo sin pago
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La disponibilidad puede cambiar mientras revisas la propuesta. La fecha solo queda bloqueada cuando se realiza y confirma el abono correspondiente.

### RESP-RESERVATION-004

- **Status:** APPROVED
- **Pregunta/resumen:** Cotización no reserva
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La cotización permite conocer la propuesta, pero no bloquea la fecha. La separación se confirma únicamente después de validar el pago.

### RESP-RESERVATION-005

- **Status:** APPROVED
- **Pregunta/resumen:** Comprobante no validado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Recibir el comprobante no confirma todavía la reserva. Nuestro equipo debe validar el pago antes de separar oficialmente la fecha.

### RESP-RESERVATION-007

- **Status:** APPROVED
- **Pregunta/resumen:** Estado no encontrado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No logramos confirmar el estado de la reserva con la información disponible. Voy a compartir tu consulta con nuestro equipo para que puedan revisarla.

## Saludos

### RESP-GREETING-001

- **Status:** APPROVED
- **Pregunta/resumen:** Saludo inicial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¡Hola! Somos el equipo de La Ceiba Club House. Nos encantará ayudarte. ¿Qué tipo de celebración o experiencia estás planeando?

### RESP-GREETING-002

- **Status:** APPROVED
- **Pregunta/resumen:** Saludo con nombre
- **Variables requeridas:** customer_name
- **Respuesta aprobada:**

¡Hola, {customer_name}! Somos el equipo de La Ceiba Club House. Nos encantará ayudarte. ¿Qué tienes en mente?

### RESP-GREETING-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente que regresa con un lead
- **Variables requeridas:** event_month, event_type, guest_count
- **Respuesta aprobada:**

¡Hola otra vez! La última vez estuvimos revisando {event_type} para aproximadamente {guest_count} personas en {event_month}. ¿Quieres continuar con esa celebración o deseas consultar algo diferente?

### RESP-GREETING-004

- **Status:** APPROVED
- **Pregunta/resumen:** Cliente con varios leads
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¡Hola otra vez! Tenemos registradas varias celebraciones contigo. ¿Con cuál de ellas deseas continuar?
¿Deseas continuar con la boda o con el cumpleaños que estuvimos revisando?

### RESP-GREETING-005

- **Status:** APPROVED
- **Pregunta/resumen:** Saludo fuera del horario humano
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

¡Hola! Somos el equipo de La Ceiba Club House. Nuestro asistente puede ayudarte con información, registrar los datos de tu evento o recibir una solicitud. Si necesitas atención de un asesor, nuestro equipo continuará contigo en el próximo horario disponible.

## Seguimientos automáticos autorizados

### RESP-FOLLOWUP-001

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud incompleta
- **Variables requeridas:** missing_field
- **Respuesta aprobada:**

Hola. Quedamos pendientes de {missing_field} para completar la solicitud. Cuando tengas la información, continuamos contigo.

### RESP-FOLLOWUP-002

- **Status:** APPROVED
- **Pregunta/resumen:** Fecha pendiente
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Hola. Quedamos pendientes de la fecha aproximada de tu celebración para completar la solicitud. Cuando la tengas, continuamos contigo.

### RESP-FOLLOWUP-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cotización pendiente de entrega
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Tu solicitud continúa en proceso. Nuestro equipo está revisando la propuesta y te la compartirá por este mismo medio.

### RESP-FOLLOWUP-004

- **Status:** APPROVED
- **Pregunta/resumen:** Pago pendiente de revisión
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

La información de tu pago continúa en validación. Nuestro equipo te confirmará el resultado cuando complete la revisión.

## Seguridad y privacidad

### RESP-SECURITY-001

- **Status:** APPROVED
- **Pregunta/resumen:** Tarjeta
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Por seguridad, no compartas números completos de tarjeta, CVV, PIN ni códigos de verificación por este chat.

### RESP-SECURITY-002

- **Status:** APPROVED
- **Pregunta/resumen:** Contraseña
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Por seguridad, no compartas contraseñas ni códigos de acceso por este medio. Esa información no es necesaria para atender tu solicitud.

### RESP-SECURITY-003

- **Status:** APPROVED
- **Pregunta/resumen:** Datos bancarios
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Utiliza únicamente los datos y enlaces oficiales enviados por nuestro equipo. No compartas claves bancarias ni códigos de autenticación.

### RESP-SECURITY-004

- **Status:** APPROVED
- **Pregunta/resumen:** Documento personal
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Antes de compartir un documento personal, nuestro equipo debe confirmar que sea necesario para el proceso correspondiente.

## Selección de horario

### RESP-VISIT-TIME-001

- **Status:** APPROVED
- **Pregunta/resumen:** Opciones
- **Variables requeridas:** appointment_options, visit_date
- **Respuesta aprobada:**

Para el {visit_date} tenemos disponibles {appointment_options}. ¿Cuál horario prefieres?

### RESP-VISIT-TIME-002

- **Status:** APPROVED
- **Pregunta/resumen:** Hora no permitida
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Las visitas se realizan en la mañana, a las 8:00, 9:00, 10:00 u 11:00. ¿Cuál de estos horarios te funciona mejor?

### RESP-VISIT-TIME-003

- **Status:** APPROVED
- **Pregunta/resumen:** Selección ambigua
- **Variables requeridas:** appointment_options
- **Respuesta aprobada:**

¿Te refieres a las {appointment_options}?

### RESP-VISIT-TIME-004

- **Status:** APPROVED
- **Pregunta/resumen:** Horario ocupado
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Ese horario ya no se encuentra disponible. Puedo mostrarte las demás opciones para ese día.

## Servicios disponibles

### RESP-SERVICES-001

- **Status:** APPROVED
- **Pregunta/resumen:** Servicios generales
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

En La Ceiba podemos acompañarte con el espacio, mobiliario, montaje, cristalería, atención de meseros, gastronomía, bebidas, piscina y apoyo audiovisual básico. Cada propuesta se personaliza según el tipo de evento y los servicios que quieras incluir.

### RESP-SERVICES-002

- **Status:** APPROVED
- **Pregunta/resumen:** Servicios especiales
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos integrar decoración personalizada, fotografía, video, música en vivo, DJ, torta, maquillaje, floristería y otros servicios especiales. Su disponibilidad y valor se confirman según la fecha y las características de la celebración.

### RESP-SERVICES-003

- **Status:** APPROVED
- **Pregunta/resumen:** Servicio solicitado no confirmado
- **Variables requeridas:** service_name
- **Respuesta aprobada:**

Podemos incluir {service_name} dentro de la solicitud. Nuestro equipo confirmará la disponibilidad, las condiciones y el valor para la fecha de tu evento.

## Solicitud de cotización

### RESP-QUOTE-001

- **Status:** APPROVED
- **Pregunta/resumen:** Datos mínimos pendientes
- **Variables requeridas:** missing_field
- **Respuesta aprobada:**

Para completar la solicitud, todavía necesitamos conocer {missing_field}.

### RESP-QUOTE-002

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen de confirmación
- **Variables requeridas:** event_date, event_type, guest_count, requested_services_summary
- **Respuesta aprobada:**

Para confirmar: estás planeando {event_type} para aproximadamente {guest_count} personas el {event_date}, con interés en {requested_services_summary}. ¿Está correcto?

### RESP-QUOTE-003

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen sin servicios
- **Variables requeridas:** event_date, event_type, guest_count
- **Respuesta aprobada:**

Para confirmar: estás planeando {event_type} para aproximadamente {guest_count} personas en {event_date}. ¿Está correcto?

### RESP-QUOTE-004

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud registrada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Perfecto, la información quedó registrada. Nuestro equipo preparará una propuesta personalizada y te la compartirá por este mismo medio en un plazo de hasta tres días hábiles.

### RESP-QUOTE-005

- **Status:** APPROVED
- **Pregunta/resumen:** Fecha aproximada
- **Variables requeridas:** event_month
- **Respuesta aprobada:**

La solicitud quedará registrada tomando {event_month} como fecha aproximada. El día exacto podrá confirmarse posteriormente.

### RESP-QUOTE-006

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud incompleta pausada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

No hay problema. La información que ya compartiste quedará registrada y podremos continuar cuando tengas los datos pendientes.

### RESP-QUOTE-007

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud duplicada
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Ya tenemos una solicitud activa para este evento. Continuaremos trabajando sobre la información registrada para evitar duplicados.

## Tipos de eventos

### RESP-EVENTS-001

- **Status:** APPROVED
- **Pregunta/resumen:** Eventos atendidos
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

En La Ceiba recibimos bodas, matrimonios civiles, pedidas de mano, cumpleaños, grados, aniversarios, cenas, reuniones familiares, eventos empresariales, bautizos, primeras comuniones, baby showers, talleres y celebraciones personalizadas.

### RESP-EVENTS-002

- **Status:** APPROVED
- **Pregunta/resumen:** Evento especial
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Podemos revisar experiencias especiales. Cuéntame en qué consiste la idea, la fecha estimada y la cantidad de asistentes para que nuestro equipo evalúe las condiciones necesarias.

### RESP-EVENTS-003

- **Status:** APPROVED
- **Pregunta/resumen:** Todo tipo de eventos
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Estamos abiertos a diferentes tipos de celebraciones y experiencias. Cada evento se revisa según su tamaño, logística, horario y servicios requeridos.

## Ubicación

### RESP-LOCATION-001

- **Status:** APPROVED
- **Pregunta/resumen:** Dirección
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Estamos ubicados en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander.

### RESP-LOCATION-002

- **Status:** APPROVED
- **Pregunta/resumen:** Dirección y mapa
- **Variables requeridas:** map_url
- **Respuesta aprobada:**

Estamos en la Calle 71 #52-34, Lagos del Cacique, Bucaramanga. Puedes encontrarnos aquí: {map_url}

### RESP-LOCATION-003

- **Status:** APPROVED
- **Pregunta/resumen:** Cómo llegar
- **Variables requeridas:** Ninguna
- **Respuesta aprobada:**

Estamos ubicados en Lagos del Cacique, en la Calle 71 #52-34. Puedo compartirte el enlace de Google Maps para que consultes la ruta desde tu ubicación.

---

# Pendientes de aprobación — Fase 0 captura de datos

## Verificación D5 — preguntas de slot filling

| `pending_action` | Plantilla verificada | Estado |
| ---------------- | -------------------- | ------ |
| `COLLECT_EVENT_TYPE` | `RESP-EVENT-DATA-013` | `APPROVED` |
| `COLLECT_GUEST_COUNT` | `RESP-EVENT-DATA-004` | `APPROVED` |
| `COLLECT_EVENT_DATE` | `RESP-EVENT-DATA-001` | `APPROVED` |
| `COLLECT_CUSTOMER_NAME` | `RESP-CUSTOMER-001` | `APPROVED` |
| `COLLECT_BUDGET` | `RESP-BUDGET-001` y fallback `RESP-BUDGET-002` | `APPROVED` |
| `COLLECT_SERVICES` | `RESP-EVENT-DATA-006` | `APPROVED` |

La base sembrada se deriva de `docs/conversation/approved-responses.md` mediante `data/knowledge_seed.py`; por tanto las plantillas aprobadas verificadas arriba quedan incluidas en seed. Las entradas `MISSING` o `DRAFT` no pertenecen al camino feliz hasta aprobación de Leandro.

## RESP-EVENT-DATA-013

- **Status:** APPROVED
- **Pregunta/resumen:** Pregunta de tipo de celebración
- **Variables requeridas:** Ninguna
- **Nota:** Movida a `docs/conversation/approved-responses.md` el 2026-08-13.
- **Respuesta aprobada:**

Para orientarte mejor, cuéntame qué tipo de celebración estás planeando y para cuántas personas aproximadamente.

## RESP-QUOTE-008

- **Status:** APPROVED
- **Pregunta/resumen:** Resumen de confirmación con fecha por definir
- **Variables requeridas:** event_type, guest_count
- **Nota:** Movida a `docs/conversation/approved-responses.md` el 2026-08-13.
- **Respuesta aprobada:**

Para confirmar: estás planeando {event_type} para aproximadamente {guest_count} personas, con la fecha aún por definir. ¿Está correcto?

## RESP-QUOTE-009

- **Status:** APPROVED
- **Pregunta/resumen:** Solicitud registrada con fecha por definir
- **Variables requeridas:** Ninguna
- **Nota:** Movida a `docs/conversation/approved-responses.md` el 2026-08-13.
- **Respuesta aprobada:**

Perfecto, la solicitud quedó registrada con la fecha por definir. Nuestro equipo preparará la propuesta y podremos ajustar la fecha cuando la tengas.
