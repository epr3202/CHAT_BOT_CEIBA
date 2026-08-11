# Visión del producto

## Asistente Conversacional de La Ceiba Club House

**Ruta del documento:** `/docs/product/vision.md`
**Versión:** 1.0
**Estado:** Consolidado para desarrollo
**Fecha:** 5 de agosto de 2026
**Propietario del producto:** Manager Leandro
**Marca:** La Ceiba Club House
**Canal inicial:** WhatsApp
**Canal futuro:** Instagram Direct
**Zona horaria oficial:** `America/Bogota`

---

# 1. Resumen ejecutivo

La Ceiba Club House implementará un asistente conversacional para automatizar la primera etapa de atención de clientes por WhatsApp.

El sistema responderá preguntas frecuentes, identificará las necesidades del cliente, recopilará información sobre su evento, registrará oportunidades comerciales, coordinará visitas y transferirá conversaciones a asesores humanos cuando sea necesario.

El primer lanzamiento no calculará cotizaciones personalizadas automáticamente. El bot recopilará la información requerida y generará una solicitud estructurada para que un asesor prepare la propuesta comercial.

Aunque el MVP comenzará con este alcance controlado, toda la solución será diseñada para evolucionar posteriormente hacia un sistema comercial completo capaz de generar cotizaciones preliminares mediante reglas deterministas.

La inteligencia artificial se utilizará para:

* comprender mensajes;
* identificar intenciones;
* extraer información;
* resumir conversaciones;
* redactar respuestas naturales.

La inteligencia artificial no tendrá autoridad para:

* inventar precios;
* confirmar pagos;
* reservar fechas;
* ofrecer descuentos;
* decidir devoluciones;
* confirmar disponibilidad sin consultar el sistema;
* modificar reglas comerciales.

Las operaciones críticas serán ejecutadas y validadas por el backend.

---

# 2. Contexto del negocio

La Ceiba Club House es una casa de eventos ubicada en:

**Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander.**

La marca ofrece espacios y servicios para celebraciones íntimas, entre ellas:

* bodas;
* matrimonios civiles;
* pedidas de mano;
* cumpleaños;
* grados;
* aniversarios;
* cenas románticas;
* eventos familiares;
* reuniones empresariales;
* bautizos;
* primeras comuniones;
* baby showers;
* talleres;
* celebraciones personalizadas.

La atención comercial se realiza principalmente por WhatsApp.

En la operación actual, los asesores deben responder manualmente preguntas repetitivas, solicitar datos, explicar servicios, coordinar visitas, revisar presupuestos y preparar cotizaciones.

Este proceso puede generar:

* demoras en la primera respuesta;
* pérdida de oportunidades fuera del horario laboral;
* repetición innecesaria de tareas;
* diferencias entre las respuestas de los asesores;
* información incompleta para cotizar;
* pérdida de contexto entre conversaciones;
* falta de trazabilidad;
* dificultad para medir la conversión comercial;
* dependencia excesiva de una persona.

El asistente conversacional deberá resolver estos problemas sin reemplazar el criterio comercial de los asesores.

---

# 3. Problema principal

Los clientes de La Ceiba esperan respuestas rápidas, claras y personalizadas cuando escriben por WhatsApp.

Sin embargo, una parte importante de las conversaciones iniciales corresponde a preguntas repetitivas como:

* ¿Dónde están ubicados?
* ¿Cuántas personas caben?
* ¿Tienen parqueadero?
* ¿Tienen piscina?
* ¿Puedo llevar alimentos o licor?
* ¿Puedo llevar fotógrafo o decorador?
* ¿Cuánto cuesta un evento?
* ¿Cómo separo una fecha?
* ¿Puedo conocer el lugar?
* ¿Qué servicios ofrecen?

Responder estas preguntas manualmente consume tiempo que los asesores podrían dedicar a:

* preparar propuestas;
* atender visitas;
* cerrar ventas;
* diseñar experiencias;
* hacer seguimiento;
* resolver casos especiales.

Además, cuando el cliente solicita una cotización, la información suele llegar de forma incompleta, desordenada o distribuida entre varios mensajes.

El sistema debe convertir estas conversaciones en información comercial organizada sin hacer sentir al cliente que está llenando un formulario.

---

# 4. Declaración de visión

> Crear una experiencia conversacional cercana, elegante y eficiente que permita a cualquier persona descubrir La Ceiba, explicar su celebración, solicitar una propuesta y agendar una visita de manera sencilla, manteniendo siempre el acompañamiento humano en las decisiones comerciales importantes.

El asistente deberá sentirse como una extensión digital del equipo de La Ceiba, no como un bot genérico.

---

# 5. Identidad del asistente

## 5.1 Presentación pública

El asistente se presentará como:

**Equipo de La Ceiba**

Ejemplo:

> ¡Hola! Somos el equipo de La Ceiba Club House. Nos encantará ayudarte a planear tu celebración. ¿Qué tienes en mente?

## 5.2 Identidad que debe evitarse

El asistente no deberá presentarse como:

* inteligencia artificial;
* robot;
* ChatGPT;
* OpenRouter;
* modelo de lenguaje;
* sistema automatizado;
* agente virtual técnico.

Tampoco deberá mencionar:

* prompts;
* herramientas internas;
* arquitectura;
* proveedores tecnológicos;
* nombres de modelos;
* procesos internos de clasificación.

## 5.3 Personalidad

La comunicación deberá ser:

* cercana;
* elegante;
* cálida;
* clara;
* respetuosa;
* natural;
* breve;
* comercial sin presión;
* coherente con una casa de eventos boutique.

## 5.4 Expresiones recomendadas

* “Nos encantará ayudarte”.
* “Cuéntame qué tienes en mente”.
* “Podemos revisar contigo”.
* “Nuestro equipo preparará una propuesta”.
* “Gracias por compartirnos esta información”.
* “Queremos que la experiencia corresponda a lo que imaginas”.

## 5.5 Expresiones prohibidas o no recomendadas

* “Aprovecha ya”.
* “Últimos cupos”, sin evidencia real.
* “Súper barato”.
* “La mejor oferta”.
* “Eso no se puede”.
* “Como ya te dije”.
* “Tu presupuesto es muy bajo”.
* “Nuestro mínimo es cuatro millones”.
* “Te garantizamos”.
* “No te lo puedes perder”.

---

# 6. Usuarios del producto

## 6.1 Cliente potencial

Persona que escribe para conocer La Ceiba, solicitar información, cotizar un evento o agendar una visita.

Sus necesidades principales son:

* obtener una respuesta rápida;
* conocer los espacios;
* entender el proceso;
* recibir orientación;
* solicitar una propuesta;
* visitar el lugar;
* hablar con una persona cuando lo necesite.

## 6.2 Cliente con evento en proceso

Persona que ya recibió una propuesta, realizó un pago, separó una fecha o se encuentra coordinando un evento.

Sus necesidades incluyen:

* confirmar información;
* enviar comprobantes;
* solicitar cambios;
* resolver dudas;
* informar problemas;
* solicitar cancelaciones;
* recibir acompañamiento humano.

## 6.3 Asesor comercial

Persona responsable de:

* revisar leads;
* preparar cotizaciones;
* tomar conversaciones;
* validar servicios;
* negociar;
* hacer seguimiento;
* confirmar pagos;
* aprobar reservas;
* resolver excepciones.

## 6.4 Business Manager

Persona responsable de atender visitas comerciales y apoyar la gestión de oportunidades.

## 6.5 Manager Leandro

Responsable general de:

* supervisar la operación;
* recibir casos especiales;
* atender escalaciones importantes;
* revisar quejas;
* aprobar excepciones;
* resolver negociaciones;
* intervenir en incidentes críticos.

## 6.6 Administrador

Usuario responsable de configurar:

* horarios;
* días no disponibles;
* preguntas frecuentes;
* respuestas aprobadas;
* asesores;
* servicios;
* paquetes futuros;
* permisos;
* reglas comerciales.

---

# 7. Alcance del primer MVP

El primer MVP corresponde a una versión de:

**Atención automatizada, captura comercial, agenda de visitas y escalamiento humano.**

## 7.1 Atención informativa

El sistema podrá responder información aprobada sobre:

* ubicación;
* enlace de Google Maps;
* parqueadero;
* tipos de eventos;
* capacidad;
* espacios;
* piscina;
* mascotas;
* proveedores externos;
* alimentos externos;
* bebidas y licor;
* alojamiento;
* horarios;
* visitas;
* separación de fechas;
* medios de pago;
* servicios disponibles.

## 7.2 Captura comercial

El sistema podrá recopilar:

* nombre;
* teléfono;
* tipo de evento;
* fecha exacta o aproximada;
* cantidad de invitados;
* presupuesto aproximado;
* espacio de interés;
* servicios deseados;
* alimentación;
* bebidas;
* decoración;
* observaciones especiales;
* correo electrónico, cuando sea necesario.

## 7.3 Registro de leads

Cada oportunidad comercial deberá quedar registrada con:

* cliente;
* canal;
* fecha de contacto;
* tipo de evento;
* estado comercial;
* datos recopilados;
* información pendiente;
* asesor asignado;
* siguiente acción.

## 7.4 Solicitud de cotización

El bot podrá:

* identificar que el cliente quiere cotizar;
* recopilar los datos mínimos;
* confirmar la información;
* generar una solicitud estructurada;
* enviarla a la bandeja comercial;
* informar el plazo estimado;
* conservar el seguimiento.

La cotización será preparada por un asesor.

## 7.5 Agenda de visitas

El sistema podrá:

* consultar disponibilidad;
* ofrecer horarios;
* agendar visitas;
* reprogramarlas;
* cancelarlas;
* enviar recordatorios;
* registrar inasistencias;
* evitar citas duplicadas.

## 7.6 Escalamiento humano

El bot podrá:

* detectar cuándo se necesita un asesor;
* generar un resumen;
* enviar la conversación a una bandeja compartida;
* asignar un asesor;
* pausar las respuestas automáticas;
* permitir que el asesor tome el control;
* devolver posteriormente la conversación al bot.

## 7.7 Historial y trazabilidad

El sistema conservará:

* mensajes;
* datos recopilados;
* correcciones;
* cambios de estado;
* citas;
* cotizaciones;
* asignaciones;
* escalaciones;
* errores;
* acciones realizadas.

---

# 8. Evolución prevista

La arquitectura deberá permitir evolucionar posteriormente hacia una atención comercial completa.

## 8.1 Cotización automática preliminar

En una fase posterior, el sistema podrá:

* consultar paquetes;
* seleccionar reglas;
* calcular conceptos;
* aplicar valores por cantidad de invitados;
* incorporar servicios adicionales;
* generar desgloses;
* crear versiones;
* definir vigencia;
* producir una cotización preliminar.

## 8.2 Principio para la evolución

La cotización automática deberá ser determinista.

Los valores provendrán de:

* paquetes;
* servicios;
* precios vigentes;
* cantidad de invitados;
* fecha;
* temporada;
* duración;
* reglas aprobadas;
* descuentos autorizados.

La IA podrá explicar la propuesta, pero no calcularla libremente.

## 8.3 Instagram

La lógica central deberá quedar preparada para integrar Instagram Direct sin reescribir:

* registro de clientes;
* gestión de leads;
* agenda;
* cotizaciones;
* escalamiento;
* reglas de negocio.

Cada canal deberá funcionar mediante un adaptador independiente.

---

# 9. Experiencia esperada del cliente

## 9.1 Primer contacto

El cliente escribe:

> Hola, estoy buscando un lugar para una boda.

El sistema:

1. Reconoce la intención.
2. Saluda.
3. Identifica el tipo de evento.
4. Solicita únicamente la información faltante.

## 9.2 Captura de datos

El cliente responde:

> Seríamos unas 45 personas y queremos hacerla en diciembre.

El sistema registra:

* boda;
* entre 40 y 50 invitados o 45 aproximados, según el mensaje;
* diciembre como mes estimado.

Luego pregunta:

> ¿Tienes un presupuesto aproximado destinado a la celebración?

## 9.3 Solicitud comercial

Cuando están completos:

* nombre;
* teléfono;
* tipo de evento;
* fecha o periodo;
* invitados;

el sistema muestra un resumen y solicita confirmación.

## 9.4 Entrega al asesor

Después de la confirmación:

* crea la solicitud;
* asigna o envía a la bandeja;
* calcula el plazo;
* informa al cliente que recibirá la propuesta en máximo tres días hábiles.

## 9.5 Visita

Si el cliente desea conocer el lugar:

* el sistema revisa días y horarios;
* ofrece disponibilidad;
* confirma datos;
* crea la cita;
* programa recordatorio.

## 9.6 Intervención humana

Cuando se solicita negociación, pago, cancelación, descuento o atención personal:

* el sistema genera un resumen;
* pausa el bot;
* traslada la conversación;
* registra el asesor responsable.

---

# 10. Reglas operativas principales

## 10.1 Ubicación

**Calle 71 #52-34, Lagos del Cacique, Bucaramanga, Santander.**

Mapa oficial:

`https://maps.app.goo.gl/hvxQH8UFN7upKMwU8?g_st=iw`

## 10.2 Parqueadero

La Ceiba cuenta con parqueadero.

El bot no deberá prometer una capacidad exacta mientras no esté confirmada.

## 10.3 Capacidad

La capacidad general comunicada será:

* hasta 50 personas cómodamente;
* máximo aproximado de 60, sujeto al montaje.

Eventos para más de 60 personas deberán pasar a revisión humana.

## 10.4 Espacios

### Terraza La Ceiba

* aproximadamente 50 personas cómodamente;
* máximo cercano a 60, sujeto al montaje.

### Salón Ceiba 1

* aproximadamente 15 personas.

### Salón Ceiba 2

* aproximadamente 15 personas.

### Salones combinados

* aproximadamente 30 personas, sujeto al montaje.

### Quiosco de la Piscina

* aproximadamente 20 personas.

La capacidad total no se obtendrá sumando automáticamente todos los espacios.

## 10.5 Horario habitual de eventos

El horario habitual se extenderá hasta:

**10:00 p. m.**

Las extensiones deberán ser revisadas por un asesor.

## 10.6 Cafetería

Horario inicial:

**Martes a sábado, de 8:00 a. m. a 12:00 m.**

La cafetería podrá atender visitantes con café, bebidas, desayunos o productos disponibles.

## 10.7 Piscina

La piscina estará incluida en los eventos.

Su uso estará sujeto a:

* horario contratado;
* seguridad;
* condiciones climáticas;
* supervisión de menores;
* instrucciones del equipo.

## 10.8 Mascotas

Las mascotas están permitidas bajo responsabilidad de sus acompañantes.

## 10.9 Proveedores externos

Se permiten proveedores externos sin cobro general por ingreso.

Su participación deberá coordinarse previamente.

## 10.10 Alimentos y bebidas externas

Se permite el ingreso de:

* alimentos;
* bebidas;
* licor.

No se cobrará descorche.

---

# 11. Reglas de agenda

## 11.1 Días disponibles

Las visitas se realizarán:

* martes;
* miércoles;
* jueves;
* viernes;
* sábado.

## 11.2 Horarios

Los horarios de inicio serán:

* 8:00 a. m.;
* 9:00 a. m.;
* 10:00 a. m.;
* 11:00 a. m.

## 11.3 Duración

Cada visita tendrá una duración de:

**45 minutos.**

Existirá un margen operativo de 15 minutos antes de la siguiente visita.

## 11.4 Anticipación

Las visitas deberán solicitarse con mínimo:

**3 días calendario de anticipación.**

No se permitirán visitas:

* el mismo día;
* para el día siguiente;
* con menos de tres días.

## 11.5 Máximo diario

Se podrán realizar máximo:

**4 visitas por día.**

## 11.6 Asistentes

Cada visita admitirá máximo:

**3 personas.**

## 11.7 Festivos

No se ofrecerán visitas durante festivos oficiales de Colombia.

## 11.8 Recordatorio

El sistema enviará un recordatorio un día antes.

## 11.9 Puntualidad

La visita termina en la hora programada, incluso si el cliente llega tarde.

Después de la visita, el cliente podrá permanecer en la cafetería.

## 11.10 Reprogramaciones

Las visitas podrán reprogramarse sin límite automático.

El sistema registrará el número y el historial de cambios.

## 11.11 Cancelaciones

La cancelación ordinaria deberá solicitarse con mínimo un día de anticipación.

Las cancelaciones posteriores se registrarán como tardías.

## 11.12 Inasistencias

Primera inasistencia:

* se registra;
* se permite reprogramar.

Segunda inasistencia:

* se registra;
* se notifica al equipo.

Tercera inasistencia:

* la siguiente solicitud se escala;
* no se bloquea automáticamente al cliente.

---

# 12. Reglas de cotización

## 12.1 Datos mínimos

Para solicitar una cotización se requiere:

* nombre;
* teléfono;
* tipo de evento;
* fecha, mes o periodo aproximado;
* cantidad estimada de invitados.

## 12.2 Datos preferibles

* presupuesto;
* horario;
* espacio;
* gastronomía;
* bebidas;
* decoración;
* servicios;
* observaciones;
* correo.

## 12.3 Presupuesto

Preguntar el presupuesto será preferible, pero no obligatorio.

La pregunta deberá formularse de manera respetuosa:

> Para recomendarte una experiencia acorde con lo que imaginas, ¿tienes un presupuesto aproximado destinado a la celebración?

## 12.4 Referente comercial

El presupuesto comercial de referencia será:

**$4.000.000 COP.**

Un presupuesto inferior no producirá rechazo automático.

## 12.5 Precios

Durante el MVP, el bot no presentará cotizaciones personalizadas.

Toda propuesta será preparada o aprobada por un asesor.

## 12.6 Plazo de entrega

El plazo comunicado será:

**Hasta tres días hábiles.**

---

# 13. Reglas de pagos y reservas

## 13.1 Separación de fecha

La fecha se separará con un abono equivalente al:

**50 % del valor acordado.**

## 13.2 Bloqueo de fecha

La fecha no se bloqueará antes del pago.

No constituyen reserva:

* una conversación;
* una visita;
* una cotización;
* una manifestación de interés;
* el envío de datos;
* un comprobante todavía no validado.

## 13.3 Confirmación

Solo un asesor podrá confirmar el pago.

## 13.4 Tiempo de validación

El asesor deberá validar la información del pago en máximo:

**1 día.**

## 13.5 Medios de pago

* transferencia;
* efectivo;
* tarjeta;
* Nequi;
* Daviplata;
* enlace de pago.

El bot no podrá inventar datos bancarios o enlaces.

## 13.6 Cancelación con un mes o más

La decisión sobre devolución o condición aplicable será tomada por un asesor.

## 13.7 Cancelación con menos de un mes

No habrá devolución.

Cualquier excepción dependerá de una decisión humana.

---

# 14. Condiciones de escalamiento

La conversación deberá transferirse cuando:

* el cliente solicite una persona;
* se solicite una cotización;
* exista negociación;
* se pida descuento;
* se informe un pago;
* se requiera confirmar una reserva;
* exista cancelación;
* haya una queja;
* el bot falle repetidamente;
* la confianza sea baja;
* el evento supere la capacidad;
* se solicite una excepción;
* un servicio dependa de proveedor;
* exista una situación urgente;
* ocurra un error del sistema.

## 14.1 Responsable general

**Manager Leandro**

## 14.2 Modelo de asignación

Las conversaciones entrarán a una bandeja compartida.

Un asesor podrá seleccionar:

**Tomar conversación**

Al hacerlo:

* queda asignado;
* el bot se pausa;
* los demás asesores no responden;
* se registra la hora y el responsable.

## 14.3 Horario humano

De martes a sábado:

**8:00 a. m. a 4:00 p. m.**

Fuera de este horario, el bot seguirá respondiendo preguntas generales y recopilando información.

---

# 15. Situaciones urgentes

Se consideran urgentes:

* evento dentro de las próximas 72 horas;
* problema con evento reservado;
* pago pendiente de verificación;
* cancelación de evento;
* cambio urgente de fecha;
* queja grave;
* cliente presente sin atención;
* problema de acceso;
* incidente de seguridad;
* emergencia médica;
* problema sanitario;
* pérdida o daño de pertenencias;
* problema de proveedor;
* cita duplicada;
* información comercial incorrecta;
* confirmación errónea de reserva;
* error relacionado con pago.

## 15.1 Casos críticos

* emergencia médica;
* incidente de seguridad;
* problema sanitario;
* doble reserva;
* cliente presente sin atención;
* confirmación incorrecta de pago;
* confirmación incorrecta de reserva.

---

# 16. Principios técnicos del producto

## 16.1 La IA interpreta; el backend decide

La IA podrá proponer:

* intención;
* datos extraídos;
* respuesta;
* resumen;
* nivel de confianza.

El backend deberá validar:

* acciones;
* fechas;
* disponibilidad;
* estados;
* permisos;
* pagos;
* reservas;
* precios.

## 16.2 Los canales estarán desacoplados

La lógica de negocio no dependerá directamente de WhatsApp.

Estructura conceptual:

```text
Canal
→ Adaptador
→ Orquestador conversacional
→ Servicios del dominio
→ Persistencia
→ Proveedores externos
```

## 16.3 Las operaciones serán idempotentes

Un mensaje repetido no deberá crear:

* dos mensajes;
* dos leads;
* dos citas;
* dos respuestas;
* dos reservas.

## 16.4 Toda acción crítica será auditable

Debe poder identificarse:

* quién realizó la acción;
* qué cambió;
* cuál era el valor anterior;
* cuál es el valor nuevo;
* cuándo ocurrió;
* por qué ocurrió.

## 16.5 La conversación no será la única fuente de verdad

Se conservarán por separado:

* historial de mensajes;
* datos del cliente;
* datos del evento;
* lead;
* citas;
* cotizaciones;
* pagos;
* reservas;
* auditoría.

---

# 17. Fuera del alcance del MVP

No se incluirán inicialmente:

* pagos automáticos dentro del chat;
* confirmación automática de pagos;
* reserva automática de eventos;
* firma electrónica;
* contratos automáticos;
* facturación electrónica;
* negociación autónoma;
* descuentos decididos por IA;
* campañas masivas;
* CRM empresarial completo;
* aplicación móvil;
* gestión integral posventa;
* inventario avanzado;
* reconocimiento completo de audios;
* análisis avanzado de videos;
* cotización completamente automática;
* atención activa por Instagram;
* automatización de proveedores.

Estos elementos podrán desarrollarse posteriormente, pero no deben bloquear el MVP.

---

# 18. Métricas de éxito

## 18.1 Atención

* porcentaje de mensajes procesados;
* tiempo de primera respuesta;
* preguntas frecuentes resueltas;
* tasa de errores;
* mensajes sin procesar.

## 18.2 Comercial

* leads creados;
* leads con datos mínimos completos;
* solicitudes de cotización;
* tiempo de asignación;
* cotizaciones entregadas;
* conversión a visita;
* conversión a reserva.

## 18.3 Agenda

* visitas solicitadas;
* visitas confirmadas;
* reprogramaciones;
* cancelaciones;
* inasistencias;
* conflictos evitados;
* recordatorios enviados.

## 18.4 Escalamiento

* conversaciones transferidas;
* motivo del escalamiento;
* tiempo hasta ser tomadas;
* casos sin asignar;
* quejas;
* errores críticos.

## 18.5 Inteligencia artificial

* intención correctamente clasificada;
* datos correctamente extraídos;
* fallos de salida estructurada;
* costo por conversación;
* latencia;
* uso de fallback.

---

# 19. Indicadores iniciales recomendados

Durante el piloto se recomienda medir:

* 100 % de mensajes registrados;
* 0 citas duplicadas;
* 0 pagos confirmados por la IA;
* 0 fechas reservadas sin pago validado;
* 100 % de casos críticos escalados;
* 100 % de conversaciones humanas con bot pausado;
* al menos 90 % de datos comerciales extraídos correctamente;
* al menos 80 % de preguntas frecuentes resueltas sin asesor;
* menos de 5 % de mensajes no comprendidos;
* 100 % de solicitudes de cotización con datos mínimos completos antes de enviarse.

Estos valores deberán revisarse después del piloto.

---

# 20. Restricciones

## 20.1 Comerciales

* La cotización será humana durante el MVP.
* El bot no ofrecerá descuentos.
* El bot no confirmará reservas.
* El bot no prometerá servicios sin disponibilidad confirmada.

## 20.2 Operativas

* Las visitas solo se ofrecen en horarios definidos.
* Los festivos deben bloquearse.
* El Business Manager tiene disponibilidad limitada.
* Los asesores responden de martes a sábado, de 8:00 a. m. a 4:00 p. m.

## 20.3 Técnicas

* El sistema depende inicialmente de WhatsApp.
* OpenRouter puede presentar errores o indisponibilidad.
* El proveedor de calendario puede fallar.
* Los webhooks pueden repetirse.
* Las respuestas de IA deben validarse.

## 20.4 De información

Todavía existen datos que deben mantenerse configurables:

* capacidad exacta del parqueadero;
* política tarifaria para niños;
* inventario actualizado;
* condiciones completas de alojamiento;
* costos por extensión;
* precios públicos autorizados;
* menú definitivo de cafetería.

Estos datos no bloquean el inicio del desarrollo.

---

# 21. Riesgos y mitigaciones

## Riesgo 1 — Respuestas comerciales incorrectas

**Mitigación:**

* respuestas aprobadas;
* base de conocimiento versionada;
* IA sin autoridad para inventar;
* validación del backend.

## Riesgo 2 — Doble cita

**Mitigación:**

* validación de disponibilidad antes de confirmar;
* transacciones;
* identificadores únicos;
* idempotencia.

## Riesgo 3 — Bot y asesor responden simultáneamente

**Mitigación:**

* estado `HUMAN_ACTIVE`;
* `bot_enabled = false`;
* exclusividad por asesor;
* auditoría.

## Riesgo 4 — Confirmación incorrecta de pagos

**Mitigación:**

* validación humana obligatoria;
* estado `PAYMENT_REVIEW`;
* prohibición de reserva automática.

## Riesgo 5 — Clientes frustrados por demasiadas preguntas

**Mitigación:**

* preguntar únicamente campos faltantes;
* extraer varios datos del mismo mensaje;
* una pregunta principal por respuesta;
* permitir saltar preguntas opcionales.

## Riesgo 6 — Dependencia excesiva de la IA

**Mitigación:**

* FAQ deterministas;
* máquina de estados;
* reglas de backend;
* fallback;
* escalamiento.

## Riesgo 7 — Cotización futura difícil de incorporar

**Mitigación:**

* registrar datos estructurados desde el MVP;
* separar solicitud, cotización y reglas;
* versionar propuestas;
* no guardar precios en prompts.

---

# 22. Supuestos

El proyecto parte de estos supuestos:

1. WhatsApp será el canal principal del MVP.
2. El número de teléfono permitirá identificar inicialmente al cliente.
3. Los asesores tendrán acceso a una bandeja compartida.
4. Existirá un calendario consultable por el sistema.
5. El Business Manager atenderá las visitas.
6. La información comercial será revisada y aprobada por La Ceiba.
7. Los precios futuros se almacenarán en catálogos y reglas.
8. Los asesores seguirán siendo responsables de las decisiones comerciales.
9. El sistema podrá conservar historial y estados.
10. Instagram se incorporará después del MVP.

---

# 23. Definición de éxito del producto

El MVP será exitoso cuando un cliente pueda:

1. Escribir por WhatsApp.
2. Recibir una respuesta inmediata.
3. Obtener información autorizada.
4. Explicar su celebración.
5. Entregar datos sin repetirlos.
6. Corregir información.
7. Generar una solicitud de cotización.
8. Recibir atención humana cuando corresponda.
9. Agendar una visita.
10. Reprogramarla.
11. Cancelarla.
12. Recibir un recordatorio.
13. Enviar información de pago.
14. Obtener confirmación humana.
15. Retomar la conversación posteriormente.

Desde la operación, el sistema deberá permitir:

1. Visualizar conversaciones.
2. Identificar leads.
3. Revisar datos del evento.
4. Tomar conversaciones.
5. Pausar el bot.
6. Registrar cotizaciones.
7. Consultar citas.
8. Confirmar pagos.
9. Confirmar reservas.
10. Auditar acciones.
11. Detectar errores.
12. Desactivar la automatización si es necesario.

---

# 24. Definición de terminado del MVP

El MVP estará terminado únicamente cuando:

* los mensajes reales de WhatsApp se reciban;
* los mensajes queden almacenados;
* los eventos duplicados sean rechazados;
* las FAQ funcionen;
* los datos comerciales se capturen;
* el contexto se conserve;
* se creen leads;
* se generen solicitudes de cotización;
* las visitas puedan agendarse;
* las visitas puedan reprogramarse;
* las visitas puedan cancelarse;
* se envíen recordatorios;
* los conflictos de agenda sean evitados;
* exista handoff humano;
* el bot se pause durante el handoff;
* los pagos no sean confirmados por IA;
* las reservas requieran validación humana;
* las acciones críticas sean auditables;
* existan pruebas automatizadas;
* existan logs y alertas;
* exista rollback;
* el equipo pueda continuar atendiendo si el bot se desactiva.

---

# 25. Gobernanza del producto

## Propietario del producto

**Manager Leandro**

## Responsabilidades del propietario

* aprobar alcance;
* aprobar reglas;
* priorizar backlog;
* validar respuestas;
* decidir excepciones;
* aprobar cambios comerciales;
* definir criterios de éxito.

## Responsabilidades del equipo técnico

* implementar reglas aprobadas;
* evitar lógica comercial dentro de prompts;
* proteger datos;
* documentar cambios;
* crear pruebas;
* mantener observabilidad;
* garantizar rollback.

## Responsabilidades de asesores

* revisar solicitudes;
* tomar conversaciones;
* preparar propuestas;
* validar pagos;
* confirmar reservas;
* registrar decisiones;
* devolver el control al bot cuando corresponda.

---

# 26. Control de cambios

Todo cambio en:

* alcance;
* precios;
* agenda;
* cancelaciones;
* devoluciones;
* pagos;
* reservas;
* capacidad;
* servicios;
* respuestas aprobadas;
* autoridad del bot;

deberá:

1. Ser aprobado por el propietario del producto.
2. Quedar documentado.
3. Tener una fecha de vigencia.
4. Actualizar las pruebas relacionadas.
5. Mantener historial de versiones.
6. Ser desplegado de manera controlada.

---

# 27. Decisiones de producto aprobadas

| Decisión                   | Resultado                              |
| -------------------------- | -------------------------------------- |
| Marca oficial              | La Ceiba Club House                    |
| Presentación               | Equipo de La Ceiba                     |
| Canal inicial              | WhatsApp                               |
| Canal futuro               | Instagram                              |
| Alcance inicial            | Atención, captura, agenda y handoff    |
| Cotización del MVP         | Preparada por asesor                   |
| Evolución                  | Cotización automática determinista     |
| IA                         | Interpreta y redacta                   |
| Backend                    | Valida y ejecuta                       |
| Presupuesto referente      | $4.000.000 COP                         |
| Plazo de propuesta         | Hasta 3 días hábiles                   |
| Separación de fecha        | 50 %                                   |
| Reserva antes del pago     | No                                     |
| Confirmación de pago       | Asesor                                 |
| Validación del pago        | Máximo 1 día                           |
| Horario humano             | Martes a sábado, 8:00 a. m.–4:00 p. m. |
| Visitas                    | Martes a sábado                        |
| Horarios de visita         | 8:00, 9:00, 10:00 y 11:00 a. m.        |
| Duración                   | 45 minutos                             |
| Anticipación               | 3 días                                 |
| Asistentes                 | Máximo 3                               |
| Recordatorio               | 1 día antes                            |
| Piscina                    | Incluida                               |
| Mascotas                   | Permitidas                             |
| Proveedores externos       | Permitidos                             |
| Alimentos y licor externos | Permitidos                             |
| Descorche                  | No                                     |
| Responsable general        | Manager Leandro                        |

---

# 28. Aprobación del documento

Este documento se considera aprobado para orientar la siguiente fase cuando:

* refleja correctamente la visión de La Ceiba;
* representa el alcance del MVP;
* diferencia claramente el lanzamiento B de la evolución A;
* establece la autoridad del bot;
* define los resultados esperados;
* no contiene reglas comerciales pendientes que bloqueen el desarrollo.

Una vez aprobado, cualquier modificación relevante deberá gestionarse mediante control de cambios.
