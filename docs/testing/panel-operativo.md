# Cobertura del panel operativo

La integración parte de `1dcf000da37692f1b57395379cb8e856622f561c`. El censo abarca las 60 operaciones HTTP explícitas de FastAPI y los 12 destinos de navegación del panel, más el acceso. Los menús dependen del rol y del entorno. La tabla identifica contratos de código. Las pruebas ejecutables del panel se encuentran en `tests/frontend`, con los nuevos recorridos en `test_operator_workspace.spec.mjs`; la persistencia y los permisos administrativos tienen pruebas en `tests/integration/test_operator_panel.py`.

| Destino | Trabajo del usuario |
|---|---|
| Acceso | Autenticar con documento y PIN, recuperar la sesión o cerrarla. |
| Conversaciones | Buscar y paginar casos en Todas o Mis conversaciones. Al abrir el chat se muestran responsable, estado, motivo y última reserva activa vinculada o solicitud en curso. La ficha completa incluye datos comerciales e historial de asignación. El menú y la lista se pliegan por separado y conservan el borrador. Desde el hilo se consulta el historial, se toma el caso, se responde, se devuelve al bot o se reasigna según el rol. Mis conversaciones muestra los casos tomados por el usuario de la sesión que continúan en atención. |
| Comprobantes | Consultar evidencia y abrir el archivo. El monto COP propuesto se carga en el campo editable al abrir o completar la pre-revisión. El operador verifica el importe y confirma la decisión. El detalle de la reserva usa el mismo formulario. |
| Calendario | Recorrer el mes con títulos por día y abrir el detalle desde la agenda del día. Las reservas vinculadas muestran la fecha y el horario confirmado en Bogotá, incluso cuando la descripción anterior conserva valores provisionales. Revisar citas locales, bloqueos y festivos. |
| Catálogos | Consultar cobertura, cargar PDF, editar estado y gestionar asignaciones a tipos de evento. |
| Planes | Consultar y editar los planes existentes, con sus condiciones de reserva y pernoctación. |
| Reservas | Consultar, filtrar, ver detalle, preparar y crear una reserva manual, registrar abonos recibidos sin archivo, consultar quién los registró y el saldo total, reprogramar, cancelar o reintentar la sincronización cuando corresponda. |
| Crear reserva | Acceso del asesor a la operación de alta manual con consulta previa de disponibilidad. |
| Agentes | Alta, ficha, edición, activación, desactivación y credenciales. La baja lógica conserva referencias históricas. |
| Avisos a asesores | Administrar destinatarios y consultar entregas y pruebas de aviso. |
| Simulador | Simular y repetir un webhook en los entornos habilitados. |
| Cobertura | Consultar el resumen funcional del producto. |
| Herramientas | Verificar el teléfono con indicativo, revisar las reservas vigentes y confirmar el reinicio una vez. La auditoría registra el administrador y el motivo automático. |

## Hallazgos y cambios

| Prioridad | Evidencia anterior | Efecto y respuesta |
|---|---|---|
| Alta | La bandeja pedía las primeras 200 conversaciones y aplicaba la búsqueda sobre esa ventana en `frontend/app.js`. | Un contacto antiguo podía no aparecer. La API ahora busca antes de paginar y la lista continúa con **Cargar más**. |
| Alta | El panel ofrecía responder y devolver en casos tomados. La API comprobaba también el propietario. | El editor y las acciones responden a la asignación. Reasignar deja un evento que figura en el historial del caso. |
| Alta | Revisar el archivo exigía descargarlo en `createEvidenceCard`. | Un visor local permite leer el PDF o ampliar la imagen conservando las decisiones de conciliación independientes. |
| Media | El historial administrativo presentaba entregas y pendientes, sin persistencia de apertura personal. | El operador distingue mensajes recibidos abiertos por él, mensajes en cola y lectura confirmada por el contacto. |
| Media | El adaptador de calendario conservaba la descripción, pero faltaba acceso desde la navegación. | Un administrador puede leer la descripción por fecha. Un fallo de consulta se presenta como incidencia de la agenda. |
| Media | La ficha de agentes, la reasignación, las visitas por día y la gestión de bloqueos tenían contrato de API sin un acceso directo en el panel auditado. | Ahora se accede a ellos desde Agentes, Conversaciones y Calendario. |

## Operaciones HTTP

Las rutas bajo `/admin` se sirven al navegador mediante el proxy local `/api/admin`. La consulta individual de metadatos de comprobantes comparte campos con su listado y detalle de reserva. La carga de catálogos en el navegador usa `/catalogs/upload`; el alta por ruta de archivo es una alternativa de API para archivos existentes en el servidor. Las sondas de infraestructura y la verificación del webhook pertenecen a sus consumidores técnicos.

| Método | Ruta | Operación | Actor | Implementación |
|---|---|---|---|---|
| GET | `/admin/plans` | Listar planes y alimentar alta manual | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L512) |
| PATCH | `/admin/plans/{plan_id}` | Guardar condiciones y activar o desactivar plan | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L525) |
| GET | `/admin/reservations` | Buscar reservas por estado, fechas y saldo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L578) |
| GET | `/admin/reservations/availability` | Consultar disponibilidad por plan e inicio | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L663) |
| GET | `/admin/reservations/{reservation_id}` | Abrir detalle, saldos, comprobantes, calendario y recordatorios | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L708) |
| POST | `/admin/reservations` | Crear solicitud manual con plan, fecha, hora y cliente | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L850) |
| PATCH | `/admin/reservations/{reservation_id}/schedule` | Reprogramar una reserva y recalcular las condiciones aplicables | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L909) |
| POST | `/admin/reservations/{reservation_id}/sync-calendar` | Reintentar sincronización de reserva ya confirmada | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1005) |
| POST | `/admin/reservations/{reservation_id}/payments` | Registrar un abono manual identificado por UUID y consultar la cuenta actualizada | Administrador | [Controlador de reservas](../../app/admin/routes.py) |
| POST | `/admin/reservations/{reservation_id}/cancel` | Cancelar una reserva con motivo y confirmación | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1026) |
| GET | `/admin/payment-evidence` | Listar evidencias pendientes de revisión | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1071) |
| GET | `/admin/payment-evidence/{evidence_id}` | Leer una evidencia individual por ID | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1103) |
| POST | `/admin/payment-evidence/{evidence_id}/prereview` | Solicitar o reintentar pre-revisión del comprobante | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1131) |
| GET | `/admin/payment-evidence/{evidence_id}/download` | Descargar el archivo privado autenticado | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1160) |
| POST | `/admin/payment-evidence/{evidence_id}/accept` | Aceptar evidencia tras revisión humana e indicar monto | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1200) |
| POST | `/admin/payment-evidence/{evidence_id}/reject` | Rechazar evidencia con nota y motivo al cliente cuando aplica | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1214) |
| POST | `/admin/blocked-dates` | Bloquear fecha operativa con motivo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1448) |
| GET | `/admin/blocked-dates` | Listar bloqueos de fecha | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1483) |
| PATCH | `/admin/blocked-dates/{blocked_date_value}` | Actualizar el bloqueo de una fecha | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1493) |
| DELETE | `/admin/blocked-dates/{blocked_date_value}` | Retirar bloqueo de fecha | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1529) |
| POST | `/admin/holidays` | Registrar festivo manual para agenda | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1558) |
| GET | `/admin/calendar/events` | Leer eventos y descripciones de los calendarios visibles por intervalo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1596) |
| GET | `/admin/appointments` | Consultar visitas por fecha | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1640) |
| POST | `/admin/catalogs` | Registrar metadatos de PDF existente y asociaciones | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1657) |
| GET | `/admin/catalogs` | Listar activos PDF, estado y asignaciones | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1708) |
| POST | `/admin/catalogs/upload` | Subir PDF multipart y asignar categoría y modalidad | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1722) |
| GET | `/admin/catalogs/categories` | Consultar cobertura por categoría y faltantes | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1782) |
| PATCH | `/admin/catalogs/{catalog_asset_id}` | Editar nombre, ruta privada o activación de un activo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1820) |
| PUT | `/admin/catalogs/{catalog_asset_id}/event-types` | Añadir, retirar y reemplazar asignaciones y modo por categoría | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L1873) |
| POST | `/admin/login` | Iniciar sesión con documento y PIN | Operador con documento y PIN | [`app/admin/routes.py`](../../app/admin/routes.py#L1936) |
| POST | `/admin/logout` | Cerrar sesión y revocar token | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2027) |
| POST | `/admin/agents` | Crear agente con nombre y rol | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2055) |
| GET | `/admin/agents` | Listar asesores y administradores con estado | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2102) |
| GET | `/admin/agents/{agent_id}` | Consultar agente por identificador | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2135) |
| PATCH | `/admin/agents/{agent_id}` | Editar nombre y rol | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2148) |
| POST | `/admin/agents/{agent_id}/activate` | Reactivar agente | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2187) |
| POST | `/admin/agents/{agent_id}/credentials` | Asignar o rotar credenciales y revocar sesiones anteriores | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2216) |
| POST | `/admin/agents/{agent_id}/deactivate` | Desactivar agente y gestionar sus sesiones | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2248) |
| GET | `/admin/me` | Resolver identidad y rol de la sesión | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2298) |
| GET | `/admin/handoffs` | Listar casos pendientes, tomados o devueltos | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2307) |
| POST | `/admin/conversations/reset` | Previsualizar y ejecutar reinicio operativo por teléfono | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2324) |
| GET | `/admin/conversations` | Listar conversaciones con filtros, paginación y contexto | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2346) |
| POST | `/admin/handoffs/{handoff_id}/take` | Tomar caso pendiente y quedar como responsable | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2483) |
| POST | `/admin/conversations/{conversation_id}/take` | Tomar directamente una conversación atendida por bot | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2534) |
| POST | `/admin/conversations/{conversation_id}/reassign` | Reasignar un caso tomado a otro agente activo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L2690) |
| POST | `/admin/handoffs/{handoff_id}/return` | Devolver el caso asignado al bot con resolución | Operador propietario | [`app/admin/routes.py`](../../app/admin/routes.py#L2745) |
| POST | `/admin/conversations/{conversation_id}/messages` | Enviar texto desde el caso propio y encolarlo | Operador propietario | [`app/admin/routes.py`](../../app/admin/routes.py#L2802) |
| GET | `/admin/conversations/{conversation_id}/messages` | Leer mensajes y salidas pendientes o suprimidas | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2872) |
| POST | `/admin/conversations/{conversation_id}/messages/opened` | Registrar la apertura personal de mensajes recibidos | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2940) |
| GET | `/admin/conversations/{conversation_id}/history` | Ver historial de asignación del caso | Operador con sesión | [`app/admin/routes.py`](../../app/admin/routes.py#L2968) |
| GET | `/admin/notification-recipients` | Listar destinatarios, suscripciones, estado y ventana | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L3427) |
| POST | `/admin/notification-recipients` | Crear destinatario de avisos con suscripciones | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L3438) |
| PATCH | `/admin/notification-recipients/{recipient_id}` | Editar destinatario, teléfono, suscripciones y activación | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L3471) |
| POST | `/admin/notification-recipients/{recipient_id}/test` | Solicitar aviso de prueba al destinatario | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L3504) |
| GET | `/admin/staff-notifications` | Consultar últimos avisos del equipo | Administrador | [`app/admin/routes.py`](../../app/admin/routes.py#L3538) |
| GET | `/webhook` | Verificar el canal mediante desafío de suscripción | Proveedor de canal | [`app/channel/webhook.py`](../../app/channel/webhook.py#L24) |
| POST | `/webhook` | Recibir mensajes o acuses y programar su procesamiento | Proveedor de canal | [`app/channel/webhook.py`](../../app/channel/webhook.py#L37) |
| GET | `/live` | Consultar vitalidad del proceso | Sonda HTTP | [`app/main.py`](../../app/main.py#L45) |
| GET | `/ready` | Consultar disponibilidad del servicio | Sonda HTTP | [`app/main.py`](../../app/main.py#L50) |
| GET | `/health` | Consultar estado desde el panel | Sonda HTTP | [`app/main.py`](../../app/main.py#L59) |

## Verificación reproducible

Desde un entorno de desarrollo con las dependencias de `requirements-dev.lock` y una base PostgreSQL 16 desechable, exportar `TEST_DATABASE_URL` y `DATABASE_URL` apuntando a esa base. El protocolo de integración se ejecuta con `ruff check .`, `make migrate-cycle` y `pytest -q`. El ciclo borra y restaura el esquema de la base de prueba.

Para Playwright se usa otra base vacía con nombre de prueba. Con ambas variables apuntando a ella, ejecutar `alembic upgrade head`, `python -m tests.frontend.seed_admin`, `npm ci --prefix tests/frontend`, `(cd tests/frontend && npx playwright install chromium)` y `ENVIRONMENT=production npm --prefix tests/frontend test`. Las pruebas inician los servidores en loopback. El entorno completo está documentado en el job `frontend` de CI.

La comprobación en Chromium recorrió 12 destinos administrativos y 7 de asesor a 375, 768, 1024 y 1440 px con datos sembrados. Las 76 vistas se ajustaron al ancho del navegador. En la instancia local también se abrió el archivo de comprobante a través de la API autenticada y se leyó la descripción de la reserva desde el adaptador de calendario de pruebas. La cuenta de Google del negocio se verifica por separado al habilitar la integración en su entorno.

## Entrega comercial posterior

Por decisión de alcance quedan separados la asignación de solicitudes de cotización, el registro de propuestas humanas, su versionado y el registro de inasistencia a visitas. La asignación de un chat opera sobre la conversación. La automatización de recordatorios de visita permanece sujeta a verificación en su propio flujo.
