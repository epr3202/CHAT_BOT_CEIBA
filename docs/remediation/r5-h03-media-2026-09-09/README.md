# R5 — H03.entrada_multimedia / U12a

Contrato previo al RED. BASE exacta 5d093f73f038f41ce683a5a1f2b4194a0426af1f,
run 34268630717: 838 nodos y 203 focales incluidos. Alembic 20260908_0026,
26 migraciones preservadas. Rama fix/r5-h03-media-20260909 desde BASE;
copia local aislada .r5-work, sin cambiar main ni publicar notas locales R0–R4.

La pausa WAITING_FOR_HUMAN (también flag verdadero), HUMAN_ACTIVE o bot deshabilitado
impide IA y nuevas salidas automáticas de medios. CLOSED conserva recepción sin reapertura
ni captura comercial. Image/document con metadata declarada suficiente y PAYMENT_REVIEW
PENDING/TAKEN de la conversación registra evidencia PENDING/PENDING_REVIEW sin caption
o con él; reutiliza prioridad/resumen/auditoría del servicio, deduplicado por Message.
Sin contexto o metadata no inventa comprobante. Audio/video no son evidencia de pago.

Puntos: claim.silent es solo decisión preliminar para evitar IA en entradas no textuales;
apply_turn vuelve a validar owned/token/fingerprint/estado. Activo a pausa descarta efectos
incompatibles; pausa a activo conserva CONTEXT_CHANGED_RECLASSIFY. Router aplica captura y
silencio en la misma transacción que COMPLETED, sin HTTP. Errores SQL/cancelación conservan
rollback y recuperación R2. No se alteran respuestas activas ni reconocedor textual R4.

Inspección: BR-HAND-007 prohíbe respuesta simultánea; BR-PAY-010 permite evidencia Nivel 1,
sin validación IA. TC-HAND-003 contiene expectativa de respuesta ya escalada discrepante
con el contrato explícito R5 y guards vigentes; se conserva documentación canónica.
Auditoría H03 distingue U12a de U12c, aunque el plan antiguo PR-08a los agrupaba.
Las rutas administrativas toman primero Handoff y después Conversation: el registro pasivo
debe evitar esperar un lock Handoff mientras mantiene Conversation. Se prevé adquisición
NOWAIT del caso seleccionado y rollback/reintento R2 ante contención, sin saltar casos.
No ampliar permisos ni reescribir administración para cambiar el orden de locks global.

Archivos de producto previstos: app/channel/inbound.py y app/channel/inbox.py.
No se prevé cambiar payment/service.py, orquestador, handoff ni DDL. Pruebas nuevas:
tests/remediation/r5/{helpers,test_r5_red,test_r5_flow,test_r5_recovery}.py.
CI: scripts/quality/r5/{run_ci,driver}.py y manifiestos JSON; workflow independiente
.github/workflows/remediation-r5-media.yml, push exclusivo R5, dos jobs aislados,
Python 3.12/Postgres 16 efímero, guard R0, sin credenciales GitHub dentro del runner.
Documentación: este directorio y actualización mínima de docs/{architecture,decisions,
pending_tasks,changelog}.md. Adaptaciones históricas solo después de RED y por nodo.

RED primero: medio sin caption HUMAN_ACTIVE debe guardar silencio; imagen y documento
con caption TAKEN deben capturar sin IA. Cuatro controles: medio activo sin contexto,
caption activo, petición textual R4 y texto R4 pausado. Los criterios y helpers RED quedan
congelados antes de producto. PostgreSQL real, parser real, respx solo frontera IA.

No cerrar H03 agregado. Pendientes: U12c/Outbox previo, H02.payment, H05.agotamiento_fallback,
H17/H29/H11 y demás hallazgos. Sin descarga/revisión certificada, atención humana efectiva,
silencio externo global, notificaciones, PR, merge, tags, despliegue ni activación.
Activación futura requiere coordinar API/BackgroundTasks/workers/CLI R1/R2.
