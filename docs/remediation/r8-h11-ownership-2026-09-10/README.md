# R8 — H11.propiedad_mutaciones_humanas / U12b: contrato previo al RED

Fecha: 2026-09-10. BASE `9af02027672049c1d73f998e9be1fe8c070e791f`, árbol
`474d790b324d554827ec4814b310eab3b27d0576`, run 34404995326/1 SUCCESS.
1257 nodeids históricos; focal 622 incluido. 26 migraciones; head 20260908_0026.
Rama autorizada `fix/r8-h11-ownership-20260910`, inexistente en consulta inicial.

## Autoridad y límites

AGENTS raíz y BASE; docs/product/business-rules.md BR-HAND-004–008 y BR-AUTH-001–005,
scope §15, conversation/states §15.4–15.9, pruebas de handoff/toma/sesiones y decisiones
R1–R7. La auditoría H11 (report.md §H11) y fase-2 dependency_review U12b son antecedentes
y propuestas, no permisos implementados. No se ejecuta una auditoría nueva.

BR-HAND-005 exige exclusividad. BR-AUTH-005 permite tomar/responder/devolver a ADMIN y
AGENT usando ID real. Ninguna regla concede responder/devolver un caso ajeno sin toma
o reasignación explícita. Scope §15 y states §15.8 prevén reasignación, pero BASE no
implementa ese endpoint. Se deja esa política/capacidad pendiente; no se crea bypass.
La autorización específica permite RED publicado con fallo, pero prohíbe PR y activación.

## Matriz de permisos

| Actor autenticado | Recurso/asignación actual | Estado | Acción | Resultado |
|---|---|---|---|---|
| AGENT A o ADMIN propietario | Conversation y único handoff activo asignados al mismo ID A | HUMAN_ACTIVE, TAKEN, bot pausado | Responder/devolver | 200; efectos transaccionales vigentes |
| AGENT B o ADMIN no propietario | IDs coherentes de A | HUMAN_ACTIVE/TAKEN | Responder/devolver por IDs conocidos | 403 genérico, cero cambios comerciales |
| Sesión ausente/inválida/expirada/revocada | Cualquier caso | Cualquiera | Mutar | 401 vigente |
| Agente inactivo con sesión | Cualquier caso | Cualquiera | Mutar | 403 vigente |
| Sesión válida | Caso inexistente | — | Mutar | 404 vigente; lectura compartida no exige ocultar existencia |
| Cualquier actor | Sin ID propietario, IDs divergentes, múltiples handoffs abiertos, asociación no acreditada | Cualquiera | Responder/devolver | 409 genérico; no reparar ni elegir último |
| Propietario | Estado no elegible o bot habilitado pese a caso activo | Incoherente | Responder/devolver | 409; sin efectos |
| AGENT/ADMIN | Sin asignación; único handoff PENDING, sin atribución legacy | WAITING_FOR_HUMAN | Tomar handoff | 200; asignación única por ID |
| AGENT/ADMIN | Sin asignación ni handoff abierto | Estado elegible para toma directa | Tomar conversación | 200; MANUAL_TAKEOVER en mismo commit |
| AGENT/ADMIN | Caso ya humano o asignación/abiertos inconsistentes | Cualquiera | Tomar | 409; no arrebatar ni reparar |
| Sesión válida no propietaria | Bandeja, mensajes, historial compartidos | Cualquiera | Leer | Política previa conservada |

`assigned_to` es etiqueta histórica, nunca autoridad ni sustituto de IDs. Agent.name es
UNIQUE en BASE: no se altera esa constraint para fabricar nombres idénticos. Se probará
una etiqueta histórica igual al nombre de B tras renombrar A, con IDs distintos; B sigue
sin propiedad. Etiquetas ausentes/distintas con IDs propietarios coherentes no transfieren
autoridad. Un handoff PENDING con atribución legacy residual no se repara durante la toma.

Rechazo: comparar antes/después desde otra sesión; sin cambios en Outbox, Message,
AuditEvent comercial, resumen, Conversation, Handoff, lead, evento ni PaymentEvidence.
Autenticación/preparación se registran antes del snapshot. No se guardan tokens/PIN/hashes
de credenciales en snapshots. HTTP 403 no incluye datos del propietario.

## Inventario de accesos y diseño previsto (antes de editar producto)

Mutaciones encontradas: routes.py take_handoff, take_conversation, return_handoff,
create_agent_message. No hay ruta alternativa de retorno/respuesta humana ni endpoint
de reasignación; la salida humana se identifica por payload.agent y usa Outbox.
Listados y filtros son lectura compartida. Desactivación/credenciales y revisión de pagos
tienen autorización propia; no se corrigen incidentalmente.

Cambios indispensables autorizados: `app/admin/routes.py` en esas cuatro rutas y
`app/admin/ownership.py` como helper pequeño. Toma requiere comprobar que no haya
asignaciones/otros casos abiertos incoherentes. No se modifica autenticación global,
modelos, migraciones, R1 settlement, R2 ledger/locks ni guards R4/R5/R6/R7.

BASE toma/devuelve con Handoff→Conversation; respuesta/toma directa empiezan por
Conversation. R2 bloquea Customer→Conversation→InboxJob y R5 después Handoff NOWAIT.
R8 usará Conversation→Handoff en orden de ID. El lookup inicial de handoff_id obtiene
solo su conversation_id para localizar; no autoriza. Tras bloquear Conversation se
recarga la asociación y todos los PENDING/TAKEN; se exige único caso coherente.
`populate_existing` evita reutilizar datos ORM previos. No se elige un último caso
arbitrario ni se bloquea otra conversación para arreglar una asociación cambiada.

Estas rutas leen Customer pero no lo bloquean/escriben; Outbox referencia Conversation
y Message, no Customer. No adquieren Customer después de Conversation. Desactivación
bloquea Agent y cuenta conversaciones con lectura MVCC; no toma lock Conversation.
Se conservan los controles de sesión al inicio; no se afirma revocación concurrente
perfecta. La identidad usada tras rollback se copia a int/string antes del rollback;
nunca se accede al Agent expirado para iniciar efectos.

Sin HTTP proveedor mientras se mantienen locks. Una respuesta que confirma antes del
retorno es válida; si retorno/nueva asignación confirma primero, la petición que espera
debe recargar/rechazar. Salidas ya encoladas y deduplicación/doble clic pertenecen a U12c.

## RED y cobertura posterior

RED mínimo sobre rutas ASGI reales y PostgreSQL: login A/B, A toma un handoff pendiente,
B responde y B devuelve en casos independientes; esperado 403 y snapshot intacto.
Controles: A responde/devuelve legítimamente; sesión inválida recibe 401. RED se congela
solo con login/toma/precondiciones y fases comprobadas, separando fallo de arnés de fallo
funcional. Helpers y tests RED permanecen idénticos después del congelado.

Después: ambas formas de toma; ADMIN propietario/ajeno; sesiones reales ausentes,
expiradas, revocadas e inactividad; labels iguales/IDs distintos; nulos/inconsistencias,
cruce de IDs, casos ausentes/cerrados, múltiples abiertos e historia no activa.
R4 origen real, R5 comprobante/resumen; lecturas y permisos ADMIN previos.
Barreras/asyncio.Event y observación de espera real en PostgreSQL, no sleeps como prueba:
dos tomas, respuesta/retorno en ambos órdenes, cambio sintético de propiedad mientras
se espera, contención R5, fallo de commit mediante trigger diferido real y cancelación
antes de commit. SQL sintético no se presenta como reasignación administrativa existente.

Conservar todos los 1257 nodeids. Cualquier fixture histórica sin propietario se
documentará por nodo antes de editarla. Sin xfail, eliminación ni rebaja de aserciones.
Runner/workflow independientes derivados de R7: suite+Ruff y focal Alembic R1–R8,
candidato exacto y gates de todas las fases/colección/aislamiento/cleanup.

## Fuera del cierre

H11 agregado, override/reasignación pendiente, otros recursos admin, U12c, H02.payment,
H05.agotamiento_fallback, H29/H17 residuales, seguridad/config/deploy y validación operativa.
Sin migraciones nuevas, roles, prompts, dependencias, estados, frontend ni instalaciones.
R7 se preserva sin reimplementarlo. Activación requiere R1/R2 y autorización separada.

## Implementación candidata y evidencia RED congelada

RED `dfad8fb7c1493f2dff23a42237b584d8885f54b4`, run 34492006457/1: suite
1263 (1261 PASS, 2 FAIL), focal 628 (626 PASS, 2 FAIL), Ruff PASS. Ambos fallos
son call con 200 frente a 403 esperado, tras login real y toma A comprobada.
Setup/teardown pasan. B cambia Outbox/resumen/auditoría al responder y
Conversation/Handoff/auditoría al devolver. Controles A=200 e inválida=401 pasan.
Los 1257 anteriores se conservan. Los ZIP originales y verificaciones completas
se entregan localmente después de CI; no se incluyen archivos masivos en Git.

`ownership.py` centraliza la carga bloqueada de Conversation y handoffs abiertos,
la exclusividad/coherencia y el permiso por ID. Las cuatro rutas existentes lo
usan; respuesta y retorno copian ID/nombre antes del rollback de autenticación.
Las escrituras, resumen y auditoría siguen en una única transacción. No hay
override ADMIN, transferencia implícita, migración ni cambio de autenticación.

Las pruebas posteriores añaden políticas/sesiones, inconsistencias, lectura,
R4/R5 y carreras. Observadores `after_cursor_execute` pausan después de SQL real;
`pg_blocking_pids` acredita la espera, los eventos liberan el orden. Un trigger
de restricción diferido produce fallo real al commit. Cancelación tras SQL y
antes de commit comprueba rollback desde otra sesión. El cambio de dueño o
relación mediante SQL es una condición sintética, no una función de reasignación.
No se atribuye RED retroactivo a esos controles ni cobertura universal de carreras.

No se adaptaron tests históricos. Los helpers y seis tests RED quedan congelados.
`new_nodes.json` enumera estáticamente los casos R8 y CI verifica colección/fases.
Ejecución autorizada: push solo a la rama R8 dispara el workflow independiente,
con `python scripts/quality/r8/run_ci.py suite` y `regressions` dentro del runner
GitHub autorizado. No ejecutar esos comandos en el PC ni contra otra base.

Este README describe el candidato antes de su CI y no certifica un resultado futuro.
El informe local post-CI identificará SHA, runs, hashes y estado final de U12b.
