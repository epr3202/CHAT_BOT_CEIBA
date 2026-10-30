# B — Hotfix de duplicados confirmados, PR #49

Base: `origin/main d0b8736d368087f90cf65229b8feffac0e419bfc`.
Rama: `fix/duplicate-reserved-guard`. La auditoría A se terminó y se reportó
antes de empezar B: [A-audit-8945.md](A-audit-8945.md).

## Resultado implementado

| Requisito | Resultado / referencia |
|---|---|
| B1 | `block_confirmed_duplicate`, `app/orchestrator/booking_flow.py:343`: mismo cliente, mismo plan, RESERVED y solape `[inicio, fin)`; presenta la entrada existente, limpia fecha/hora/confirmación/checkout, conserva plan y pide otra franja sin handoff |
| Dos controles | Antes de agenda en continue_slots (`booking_flow.py:638`) y antes de crear al confirmar (`:945`); incluye pernoctación mediante booking_ends_at |
| Auditoría | BOOKING_DUPLICATE_BLOCKED con reservation_id existente, plan_code y starts_at UTC; actor SYSTEM y request_id del turno |
| B2 | RESP-BOOKING-DUPLICATE-001 APPROVED v1, texto exacto y variables plan_name/date/time; `data/knowledge_seed.py:45` y `docs/conversation/approved-responses.md:2911` |
| Aprobación | Emerson confirmó expresamente la aprobación de Leandro en esta conversación el 2026-10-30, antes del push |
| Respaldo | Si la nueva respuesta no está aprobada o no renderiza: handoff con RESP-BOOKING-PENDING-001; no crea reserva |
| Guards previos | PAYMENT_PENDING/PAYMENT_REVIEW conservan su comprobación global y precedencia; no se cambian D3 ni la coexistencia no exclusiva |
| B3 | Fuentes revalidadas en barrido PENDING/DEFERRED y después del claim, antes de HTTP; `app/notifications/worker.py:50`, `:117`, `:171` |
| Alerta obsoleta | EXPIRED + STAFF_NOTIFICATION_SUPERSEDED una vez; fuente ausente/incorrecta también se retira. Callbacks guardan su recibo, pero no reactivan EXPIRED (`app/notifications/statuses.py:90`) |
| Literal staff 10 | Test con id 10 y UUID d79893e0-105c-4211-8c1f-3cc1f138dc26 CANCELLED: cero envíos, EXPIRED y auditoría |
| B4 | Servicio compartido por script/panel limpia booking_draft y su snapshot, devuelve live_reservations y audita RESET_LEFT_LIVE_RESERVATIONS si hay no terminales; `app/admin/conversation_reset.py:118`, `:203` |
| Panel | Aviso visible y lista de id/estado/inicio, sin cancelar reservas; `frontend/app.js:2174` |

**Migraciones: ninguna.** EXPIRED ya es un estado terminal admitido por el CHECK;
la distinción de obsolescencia queda en la auditoría. No hace falta 0038 ni un
downgrade nuevo. Head continúa `20261028_0037`; el migrate-cycle existente pasó.

## G2 — evidencia roja y controles verdes

Los tests se escribieron antes de implementar. En la base d0b8736:
**24 fallos esperados, 6 verdes, cero errores de preparación**, en 30 casos Python.
El test del panel también falló por ausencia del aviso de reservas vivas.

| Contrato | Base | Candidato final |
|---|---|---|
| [R] …8100, Ritual 7-nov 15:00 RESERVED, reset, nueva conversación y misma petición | Rojo | Verde: DUPLICATE, sin reserva ni handoff nuevos |
| [R] Tres solapes, incluida hora solicitada distinta | Rojo | Verde: presenta hora existente |
| [R] Reserva confirmada después de ofrecer la propuesta | Rojo | Verde: control final |
| [V] Otra hora adyacente sin solape | Verde | Verde: crea PAYMENT_PENDING normal |
| [V] Otro cliente y mismo plan no exclusivo/franja | Verde | Verde |
| [V] Mismo cliente y otro plan no exclusivo | Verde | Verde |
| [V] Pendiente/revisión previos, dos estados | Verde | Verde: guard y handoff existentes |
| [R] Nueva respuesta no aprobada | Rojo | Verde: respaldo PENDING |
| [R] Seed literal APPROVED v1 | Rojo | Verde |
| [R] Reset por script y endpoint, dos casos | Rojo | Verde: draft limpio, lista/audit y reserva intacta |
| [R] Alerta obsoleta, cuatro estados de fuente × PENDING/DEFERRED/reactivada | 12 rojos | 12 verdes, sin HTTP |
| [R] Evidencia ya aceptada/rechazada | 2 rojos | 2 verdes |
| [V] Alerta de solicitud aún vigente | Verde | Verde: sí envía |
| [R] Callback tardío de alerta retirada | Rojo | Verde: permanece terminal |
| [R] Aviso de reservas vivas en panel | Rojo | Verde en Chromium |

Los 30 casos iniciales están incluidos en el bloque G3 y terminan verdes.
Los 12 casos adicionales de borde cubren reentrega, exclusividad propia,
previsualización sin mutación, cancelación después del claim, fuente inexistente,
padre cancelado, saldo vencido pagado, el literal staff 10 y el TEST manual.

La primera implementación dio **27 verdes y 3 fallos de controles V**: el nuevo
SELECT hacía autoflush del draft y exponía una mutación JSON en el mismo objeto,
perdiendo precio/duración. Se corrigió asignando un dict nuevo; no se cambiaron
las aserciones para aceptar el resultado incorrecto.

Después de RED solo se añadieron anotaciones/imports de tipos en el módulo G2
de staff; se verificó que su AST de aserciones era idéntico. Los casos G3 se
añadieron en módulos separados. [verification.json](verification.json) conserva
hashes iniciales/finales, resultados y huellas de los artefactos temporales.

## G3 — verificación local anterior al único push

| Grupo | Resultado |
|---|---:|
| booking_conversation | 315 passed |
| booking_backend | 91 passed |
| staff_notifications | 63 passed |
| payment_settlement | 103 passed |
| availability_lodging | 111 passed |
| Integración del reset | 9 passed |
| Unit del script de reset | 6 passed |
| **Bloque principal** | **698 passed, 0 fallos, 0 errores; 960,89 s** |
| Casos adicionales de borde | **12 passed** en ejecución separada |
| Panel: nuevo aviso | **1 passed**, Chromium |
| make migrate-cycle | **PASS**, upgrade → base → upgrade, head 0037 |
| ruff del candidato limpio | **PASS** |
| git diff --check y sintaxis Node | **PASS** |

Comando del bloque principal, con PostgreSQL 16 local aislado y TEST_DATABASE_URL
explícita apuntando a `ceiba_pr49_test`, puerto local 55439:

```sh
.venv/bin/pytest tests/booking_conversation tests/booking_backend \
  tests/staff_notifications tests/payment_settlement tests/availability_lodging \
  tests/integration/test_admin_conversation_reset.py \
  tests/unit/test_reset_local_conversation.py -q
```

Los casos adicionales usan `ceiba_pr49_edges_test`; migrate-cycle usa otra DB
`ceiba_pr49_migration_test`. Ninguno apunta a producción. Las llamadas Meta/IA
se reemplazan por dobles/respx. El test de panel usa respuestas HTTP simuladas
y el frontend real. El CI del PR ejecuta la suite completa y el frontend completo.

## Commits y límites

| Orden | SHA | Contenido |
|---|---|---|
| test: | `1dbc515837fc2f96fef0db038d95695694166515` | G2/G3 y fixtures de fuentes reales, sin migraciones |
| fix: | `f5d5e515a5aa13bf17aa7b6634c56e7d02c35b7a` | Guard, retirada de avisos, reset/panel y versión de seed |
| docs: | Identificable por git log y reporte final del chat | A, reglas/texto aprobados y esta evidencia |

Los commits se agruparon después de verificar el árbol completo verde,
conservando el orden test → fix → docs. No se creó un commit mientras había
fallos pendientes en el candidato. Los archivos ajenos sin seguimiento, incluido
el G1 anterior solicitado sin commit, se excluyen de los commits.

Decisiones/desviaciones explícitas:

- No se añade migración porque se reutiliza EXPIRED; es la alternativa permitida
  por B3 y mantiene libre el número 0038 para trabajo posterior.
- Se actualizaron los fixtures antiguos de entrega de staff que usaban una
  evidencia inexistente `123`: ahora incluyen un comprobante pendiente real y
  su reserva. Se conservan las aserciones de ventana, reintentos y cero HTTP en
  transacción. Los fixtures de interceptación siguen sin crear clientes.
- `ruff check .` en el workspace detecta **210 errores previos** en scripts
  ajenos no versionados de a13/a14. No se modificaron. El lint de app/tests/
  scripts/data/alembic y `ruff check .` sobre una copia limpia de todos los
  archivos versionados más los archivos nuevos del candidato pasan; corresponde
  al contenido que verá CI.
- La admisión staff libera transacciones antes de HTTP. No se promete cancelar
  una entrega si la fuente cambia concurrentemente después de esa última lectura.
- No se implementan parser, adicionales, cambios de precios ni otras partes del
  censo G1. No se modifica producción, no se envían avisos reales y no se hace merge.

El cierre operativo autorizado es un único push de esta rama y un PR draft,
con un máximo de dos rondas de CI. Los SHA completos, enlace y resultado de CI
quedan en el reporte final de la tarea; este archivo documenta la evidencia local
que precede al push.
