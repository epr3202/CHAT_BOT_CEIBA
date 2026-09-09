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

## RED observado y adaptación histórica prevista antes de editar

RED inspeccionado: SHA 243e6516744d06b058e07956f36c5bc44cd0adcf, run 34356802721,
focal 210 = 203 históricos + siete nuevos. 207 PASS y tres FAIL en call: salida
automática sin caption, evidencia omitida con caption en imagen/documento, cada uno
con una clasificación IA indebida. Ruff PASS, fases completas y cero red inesperada.
El primer run 34355991796 conserva sus artefactos; no se atribuye resultado funcional
sin inspeccionar sus aserciones. La repetición añadió transporte de ZIP por logs del
conector autorizado porque el proxy del PC no conecta; producto y criterios idénticos.

Nodo histórico a adaptar: tests/test_w2b_payment_evidence_adversarial.py::
test_tc_pay_001_no_caption_in_payment_context_creates_evidence_and_raises_priority.
Su seed usa WAITING_FOR_HUMAN, flag verdadero, PAYMENT_REVIEW/PENDING; image sin caption.
Antes exige last_question_code=RESP-PAYMENT-002, incompatible con silencio R5.
Después exigirá last_question_code intacto (None), cero Outbox, caso PENDING y conversación
WAITING_FOR_HUMAN con flag verdadero conservados, un InboxJob COMPLETED silencioso.
Se conservan identidad, media_id, descarga/revisión pendientes, prioridad urgente,
auditoría y cero IA. Atomicidad se refuerza en test_real_commit_failure_then_recovery.
Versión anterior permanece en BASE y ambos RED; no se cambia estado ni payload.

El inventario R5 conserva siete nodeids RED fijos y registra todos los nodos nuevos
descubiertos en tests/remediation/r5, incluidos en suite/focal. El gate compara exactamente
los históricos más ese inventario; no suma el focal al total ni omite fallos de fases.

Segunda adaptación identificada antes de editar: mismo archivo histórico, nodo
test_tc_pay_006_audio_in_payment_context_is_not_evidence. El seed también deja
WAITING_FOR_HUMAN/PENDING y flag verdadero; audio/ogg sin caption. Exigía
last_question_code=RESP-FILE-003. R5 exige conservar None, cero Outbox y caso/pausa
intactos; se mantienen ausencia de evidencia y cero IA. BASE/RED preservan la versión.
La suite RED completa ya fue inspeccionada: 845 nodos, 842 PASS y los mismos tres
FAIL funcionales; los 838 históricos pasan con fases completas.
