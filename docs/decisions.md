# Decisiones y propuestas

## Propuestas de auditoría — 2026-09-07

**Estado: PROPUESTAS, no aceptadas ni implementadas.** Base HEAD 8935687. [Plan completo](audits/2026-09-07-8935687/remediation_plan.md).

- Ratificar alcance candidato y calendario de SLA (H18/H26).
- Separar identidad del mensaje y finalización durable, con claims verificables (H01/H02).
- Unificar pausa humana y autorización de acciones sobre casos (H03/H11).
- Definir operación durable y reconciliación de agenda (H07/H08).
- Promover artefacto/SHA probado y contenido versionado explícitamente (H13/H16).
- Acordar retención/minimización efectiva y evidencia de recuperación (H19/H20).

Las decisiones aceptadas anteriores continúan en sus documentos canónicos, especialmente D1 y otras decisiones de [observabilidad IA](product/ai-execution-observability.md). No se acepta una reducción del MVP, una nueva infraestructura ni excepciones a append-only por crear este índice. AGENTS.md permanece sin modificaciones.


## 2026-09-08 ? R1 H02.Outbox

Decision R1 limitada: UUID nullable por adquisicion, sin backfill de propietarios antiguos; liquidacion exige token obligatorio. Expiracion efectiva por reaper. No es segura la convivencia con workers antiguos que liquidan por ID. El procedimiento de activacion propuesto exige detenerlos; no se despliega.

[Diseno, pruebas y procedimiento](remediation/r1-h02-outbox-2026-09-08/README.md).


## 2026-09-08 - R2 H01 inbox

Decision R2 limitada: control durable por Message, orden local por conversacion, reintentos acotados, finalizacion silenciosa explicita y separacion de operaciones de agenda. No hay backfill de exito ni convivencia segura con API/worker/CLI antiguos. No completa H06/H07 ni modifica las reglas de negocio.

[Diseno, limites y validacion](remediation/r2-h01-inbox-2026-09-08/README.md).


## 2026-09-08 - R3 H04 transporte IA

R3 conserva AIUnavailable y HTTP_ERROR para llamada fallida con subtipo sanitizado, TIMEOUT separado. No captura indiscriminadamente TransportError/Exception; configuracion, cancelacion y programacion conservan propagacion. No se cambian prompts ni rutas comerciales.

[Contrato y evidencia R3](remediation/r3-h04-ai-2026-09-08/README.md).
