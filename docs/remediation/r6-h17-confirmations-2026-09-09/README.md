# R6 — H17.contrato_y_consumo_de_pendientes / U03

Contrato previo al RED. BASE exacta `d237ad773fe62ce8cfec2e9aa33931f2b9d1c434`,
árbol `eae1d154053a233dd5644e6bb97fcaf691eb71f3`, run 34364403706.
Rama nueva `fix/r6-h17-confirmations-20260909`, creada desde ese objeto.
1014 nodos previos, 379 focales incluidos; Alembic 20260908_0026, 26 migraciones.

## Fuentes y separación histórica

Se contrastaron scope, business-rules, entities, states §38, approved-responses,
conversation-test-cases (nombre inferido, solicitud, TC-B3), decisiones R1–R5,
deep_review de Fase II y evidence_delta/recorridos integrados V0.
V0 atribuye DENY→sí y retorno→sí al lector de classification; corrección de nombre
bajo QUOTE_REQUEST restaura el anterior. DENY→corrección→sí es control positivo.
Son antecedentes; R6 no los atribuye a BASE hasta ejecutar sus propios tests.
Los informes finales R5 y ZIP verificados son locales, fuera de su SHA; su README
publicado e índices todavía dicen «en validación». Eso no cambia el run verificado.

Discrepancia documental ya existente: scope enumera uplift como pendiente de PR-B.2,
mientras BR-AI y TC-B3 y el producto posterior lo implementan. R6 conserva uplift
y no restaura acciones anteriores, no normaliza afirmaciones adicionales ni inventa TTL.
AGENTS pide commit solo en verde; este encargo autoriza explícitamente RED y correcciones
para Actions. No se crea PR ni se ejecuta activación.

## Inventario de autoridad en BASE

| Productor / forma | Lector / contexto | Consumo o limpieza actual |
|---|---|---|
| Orquestador banda incierta: classification, original_intent, original_confidence, entities | resolve_pending_confirmation, previo al routing | sí valida classification y limpia CLASSIFY_MESSAGE; otro texto descarta JSON |
| apply_full_name: type=FULL_NAME_CONFIRMATION, full_name | resolver genérico omite; maybe_apply_name_confirmation durante captura | sí aplica; nombre corregido/negación no invalidan anterior |
| handle_quote_request_ready DENY: resolved_intent y diagnóstico de acción/pregunta | resolver genérico, tras vuelta a captura | no es propuesta pero BASE intenta leer classification |
| handle_quote_request_ready CONFIRM: mismo marcador diagnóstico | pausa, return_handoff, siguiente turno | retorno limpia acción y asignación; conserva JSON |
| Contexto Message/AI y fingerprint R2 | inbound.persisted_message_from_models, ai.client | lecturas sin autoridad de dominio; fingerprint completo conserva JSON |
| capture_progress | discrimina nombre por type | bloquea mínimos mientras haya pendiente de nombre |
| Catálogo dirigido y fallo de captura | resolve_catalog_event_type_capture / handle_failed_services_resolution | limpian al resolver/abandonar/degradar ese flujo |
| greeting, farewell, general_information (catálogo y FAQ), handoff | rutas respectivas del orquestador | limpian; FAQ debe distinguir interrupción válida de cambio de propósito |
| Acciones CONFIRM_* de solicitud/visita | confirmation.resolve_contextual_confirmation, inbound y orquestador | familia independiente definida por acción/pregunta/estado y draft; no depende del JSON de clasificación |
| scripts/reset_local_conversation.py | mantenimiento explícito existente | limpieza fuera de runtime; se protege, sin backfill |

Búsqueda completa `rg pending_confirmation app scripts tests`; ningún otro servicio de
dominio crea una propuesta de este campo. Conversation declara dict|None pero JSONB
puede contener legacy no-objeto. No se deduce validez del tipo Python anotado.

## Criterios antes del arreglo

- Resumen real→no→sí: turno procesable, DRAFT, sin aceptación/handoff; captura completa
  puede emitir un resumen nuevo RESP-QUOTE-002. Ese turno no registra READY.
- Resolución confirmada→handoff→take/return autenticado→sí: conservar READY anterior y
  único caso RETURNED, sin aceptación nueva; BOT_ACTIVE usa RESP-FALLBACK-001.
- Nombre propuesto→corrección explícita→sí: conservar corregido; si ya se emitió resumen
  actualizado, la confirmación legítima de ese resumen continúa por el matcher existente.
- Propuesta incierta→sí conserva AI_CONFIRMATION_ACCEPTED/CONFIRMATION_UPLIFT y confianza.
  Nombre vigente→sí y DENY→corrección→continuidad deben seguir funcionando.
- Sin propuesta, ausencia/inválido/resolución no autorizan cambios comerciales.
  Captura pide el dato faltante o muestra resumen nuevo; BOT_ACTIVE aclara; agenda
  conserva sus guards/contexto deterministas. No plantilla universal.
- Pausa y R4 se evalúan antes de cualquier saneamiento comercial; R5 conserva medios.
- Propuestas activas se distinguen explícitamente de resoluciones. Legacy solo se acepta
  con forma y contexto actuales suficientes; nunca se reconstruye desde diagnóstico.
  La validación cubre estructura de clasificación y nombre textual no vacío, sin H29 general.
- Negación/corrección retira autoridad; los formatos inválidos se descartan bajo R2 con
  motivo técnico, sin publicar JSON/nombre en nuevos logs. SQL/cancelación no se capturan
  como errores de formato. FAQ legítima conserva borrador/datos y propuesta compatible.
- Todo consumo/aplicación/auditoría/Outbox/COMPLETED pertenece a la transacción R2 existente.

## Alcance exacto previsto

Producto: `app/orchestrator/service.py` y helper puro
`app/conversation/pending_confirmation.py`. No se prevé tocar inbound, inbox ni admin:
los lectores deben volver inerte el marcador conservado al retornar.

Pruebas: `tests/remediation/r6/{helpers,test_r6_red,test_r6_contract,test_r6_recovery}.py`.
Posible adaptación justificada tras RED en `tests/unit/test_orchestrator.py`: fixture
legacy de clasificación sin acción/pregunta es ambigua; la decisión se documentará por nodo.
Sin cambios históricos hasta demostrar el candidato. Otros tests protegidos.

CI: `scripts/quality/r6/{run_ci,driver}.py`,
`{allowed_paths,baseline_manifest,source_manifest,r5_nodes,new_nodes}.json`;
`.github/workflows/remediation-r6-confirmations.yml`. Derivación mínima de R5.
Documentación: este README y cuatro índices architecture/decisions/changelog/pending_tasks.
La allowlist explícita se comprueba contra Git antes de cada publicación. Solo archivos
seleccionados; los informes locales anteriores y el árbol original quedan preservados.

## Ejecución y límites

Siete nodos iniciales: tres resúmenes, dos nombres, uplift y R4. Producto BASE intacto.
La colección R6 posterior surgirá de ramas/concurrencia/compatibilidad, sin cuota.
Suite y focal son jobs independientes Python3.12/PostgreSQL16, SHA exacto, red interna
y guard R0. Focal conserva Alembic; suite identifica fixtures históricos de metadata.
Ruff, fases, colección, aislamiento y limpieza siguen siendo gates reales.
`python scripts/quality/r6/run_ci.py suite` y `... regressions`, solo en Actions.

No migraciones, backfills, limpieza de ledger ni reparación de FAILED/REVIEW/EXTERNAL.
No cambia política de IA, negocio de pagos/agenda, permisos ni proveedores reales.
Abiertos U12c, H02.payment, H05.agotamiento_fallback, H29 general, H11, H16 y H06 completo.
Sin TTL ni identificación del referente de un sí tardío sin referencia del canal.
H17 agregado y last_question_code ante fallback de conocimiento no se certifican.
La activación futura requiere coordinación R1/R2 de API/BackgroundTasks/workers/CLI;
publicar la rama no la activa.

## Primer intento de arnés conservado

SHA d0b66ea95c8948a1379ec26af4d1a432d939b3af, run 34371745073.
Focal 386: 382 PASS y 4 FAIL, fases completas; Ruff falla por longitud/imports.
DENY y retorno guardan KeyError; nombre corregido vuelve al viejo. No se usa este
intento como RED final: el primer payload de nombre no coincidía con la frase reportada,
y el control uplift buscaba una acción independiente en vez de AI_CONFIDENCE_DECISION
con decision=CONFIRMATION_UPLIFT. Se corrigen solo estas precondiciones/observaciones y
lint; se repite producto BASE intacto. No se relaja el criterio de negocio.