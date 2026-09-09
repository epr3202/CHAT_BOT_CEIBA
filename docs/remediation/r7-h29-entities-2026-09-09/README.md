# R7 — H29 / U04: contrato previo al RED

BASE cfdc09b1d2805da5743e3f6466cb88fcb3142905; árbol
60dd9d58c5c5d7de437e3b1207add375d0e42a83; run 34381466698.
1101 nodos históricos / 466 focales incluidos; Alembic 20260908_0026, 26 migraciones.
Rama exclusiva fix/r7-h29-entities-20260909. Producto BASE intacto durante RED.

## Fuentes y autoridad
AGENTS raíz y copia BASE idénticos; sin variantes anidadas. Scope MVP, business-rules
BR-GEN-005/BR-KB-005, entities ENT-GEN-001–005, §§6–13/35–37/42, estados/captura,
approved-responses y conversation-test-cases TC-NLU/captura/corrección.
Modelos customer/lead/event, event.validation, lead.budget, servicios y etiquetas
canónicas son contratos efectivos. Los índices R0–R6 y el informe local R6 distinguen
propuestas de auditoría, código publicado y resultados posteriores al CI.
Fase II dependency_review U04/deep_review y V0 actions/report_integrated/evidence_delta:
negativos e invertidos persistían; many/rango incompleto/fecha inválida/sin tipo/legacy
desconocido fallaban. Son antecedentes hasta el RED R7, no resultados atribuidos a R6.

La autorización específica permite commits RED pese a AGENTS; solo rutas seleccionadas.
No runtime local, nuevas dependencias, DDL, backfill, PR, merge ni activación.

## Contrato por entidad antes del arreglo

| Entidad | Representación válida / normalización | Rechazo / ambigüedad | Fuentes y salida |
|---|---|---|---|
| full_name | Texto 2–120, espacios normalizados, tildes y nombre propio conservados; propuesta inferida conserva U03 | None sin texto, estructura, numérico, solo números o símbolos; nunca str(objeto). No se infiere propiedad del nombre de terceros | ENT6.1; Customer String120; RESP-CUSTOMER-001, conservando nombre previo |
| event_type | Código o normalización/alias ya aprobados; no ampliar catálogo | Desconocido se descarta como actualmente, no OTHER; no usar estructura ni entidad INVALID como dato | ENT7.1/event_type.py; RESP-EVENT-DATA-013 si falta; control de descarte histórico |
| guest_count | Entero exacto positivo o texto entero decimal; representación float solo si finita y exactamente integral | bool, fracción, negativo/cero, no interpretable, objeto/lista; máximo 2147483647 por Integer, no aforo comercial | ENT10.1: >0; >60 revisión existente; RESP-EVENT-DATA-004 |
| guest_count_range | Objeto min/max, ambos enteros positivos dentro de Integer; min<=max; rango indivisible | Ausente un extremo, invertido, bool/fracción/desborde; no intercambiar ni completar | ENT10.2/10.3; RESP-EVENT-DATA-004 |
| event_date | ISO exacta o triplete EXACT/APPROXIMATE/FLEXIBLE/UNKNOWN coherente; mes YYYY-MM real; utilidades existentes y reloj explícito | Objeto/discriminante/llaves incoherentes, fecha imposible/pasada explícita, mes imposible. No inventar día/año límite. Sin año: reanclaje existente | ENT8.7/event.validation; RESP-EVENT-DATA-001; agenda elegible es otra frontera |
| estimated_budget | Decimal canónico positivo exacto; COP coloquial por parser vigente. Numeric(12,2): hasta 9999999999.99, <=2 decimales sin pérdida | bool/NaN/infinito/estructura/signo/desborde/precisión perdida; inválido no equivale a DECLINED ni evasión | ENT11/lead.budget/modelo Lead; RESP-BUDGET-001; cero rechazado conforme parser positivo, no mínimo comercial nuevo |
| budget_declined | Booleano true explícito; false no es negación | Texto/número/estructura no se vuelven truthy; conflicto con monto se aclara | Flujo actual de declinación; presupuesto opcional. Ausencia/false no crea evento DECLINED |
| requested_services | Lista de textos/códigos/alias del catálogo actual; conservar orden y descartar desconocidos conforme política vigente | Elementos estructurales no se stringifican; lista vacía/forma inválida no autoriza servicio. No promover AVAILABLE/INCLUDED | services_catalog y EventServiceRequest REQUESTED; RESP-EVENT-DATA-006 |
| special_requests | Texto comercial, sin límite inventado (columna Text); no sustituye campos estructurados | Estructuras/números/bool/null no se convierten en texto; NUL no representable en PostgreSQL se rechaza | ENT7.4/Event Text; aclaración RESP-FALLBACK-004, sin evento CAPTURED falso |

Representación flexible nueva en la frontera: validar antes de convertir, admitiendo solo
normalizaciones sin pérdida compatibles con datos actuales. Los límites Integer/Numeric
son técnicos; no implican aforo ni precio mínimo. Los parsers COP conservan sus expresiones
autorizadas; una extracción errónea no se repara con otra llamada IA.
La semántica de nombre exige letra identificable conservando nombres inusuales válidos;
no se certifica desambiguación de terceros ni privacidad global.

## Calidad, mezclas y resolución
PROVIDED/CORRECTED/confianza alta no evitan validación. INVALID se audita por código
controlado, sin copiar validation_errors arbitrarios. INFERRED/PENDING_CONFIRMATION no
promueven datos críticos a confirmados: nombre conserva U03, event_type inferido se
descarta como antes; incertidumbres de otros campos se aclaran antes del resumen.
Ausencia no equivale a UNKNOWN declarado; este último solo es fecha UNKNOWN coherente.
Corrección inválida conserva dato anterior pero pide el campo, sin presentar resumen como
si se hubiera aceptado la corrección. Se aplican datos independientes válidos del mismo
turno; rango/triplete/conflictos del mismo campo se rechazan juntos.
Tipado y legacy coherentes no duplican efectos; conflicto de la misma entidad se aclara.
Claves legacy desconocidas se descartan con diagnóstico técnico y aclaración, sin
ValidationError escapado. No se fabrica EntityName comercial para una clave desconocida.
Un «sí» de R6 vuelve a pasar entidades por la frontera sin cambiar vigencia de propuesta.

## Mapa de rutas BASE
| Productor/entrada | Normalización / consumidor | Riesgo a comprobar |
|---|---|---|
| Cliente IA parser → IntentClassification | normalized_entities → normalizador de event_type → routing | Any de los nueve valores no valida semántica |
| entities legacy | conversión a ExtractedEntity en normalized_entities | str/bool y EntityName/quality desconocidos pueden falsear o abortar |
| extracted_entities | apply_extracted_entities y apply_* | int/Decimal/triplete o str aplican datos sin contrato completo |
| R6 CLASSIFICATION_CONFIRMATION | resolve_pending_confirmation → mismos consumidores | confirmación no valida el contenido de Any |
| R6 nombre / captura directa visita | name_value, apply_full_name, maybe_apply_name_confirmation | forma R6 no demuestra semántica; no romper FAQ/corrección |
| Auxiliares de tipo/servicios del canal | clasificación reconstruida y consumidores del orquestador | misma frontera final, no prompts/proveedores nuevos |
| Capacidad, resumen y captura de presupuesto | guest_count/range, capture_progress, evasión | no resumir un rechazo ni convertirlo en negativa |
| R2 aplicación bajo propietario/fingerprint | dominio + auditoría + Outbox + COMPLETED | conservar transacción, rollback, cancelación y bloqueo |
| R4 / R5 | antes de aplicación comercial | no validar/aplicar/auditar rechazo bajo pausa ni antes de asesor explícito |

## Criterios RED y salida
Se probarán con DB migrada, cliente HTTP estricto real y mensaje realmente almacenado:
cantidad negativa/textual, rango incompleto/invertido, fecha imposible/sin discriminante,
legacy desconocido. Criterio: mensaje conservado, turno COMPLETED, valor previo válido
intacto, cero aceptación del inválido y pregunta del campo (legacy: RESP-FALLBACK-004).
Controles de cantidad/rango/fecha válidos, descarte event_type ya válido, nombre vigente
R6 y pausa. No todos estos casos tienen que fallar en BASE.
Los criterios RED y helpers se congelan tras verificar setup/call/teardown y Ruff.

## Alcance exacto
Producto previsto: app/conversation/entity_validation.py, app/orchestrator/service.py
y validación de nombre en app/conversation/pending_confirmation.py. Cualquier otra ruta
indispensable se justificará antes de editar/publicar. No schema público/prompts nuevos.
Pruebas nuevas tests/remediation/r7/{helpers,test_r7_red,test_r7_contract,test_r7_recovery}.py.
Adaptaciones históricas solo después de identificar nodo y contrato; no se presuponen.
Runner scripts/quality/r7/, workflow remediation-r7-entities.yml, este contrato e índices
architecture/decisions/changelog/pending_tasks. Allowlist exacta antes de publicar.

## Límites
H29 agregado no se cierra si queda lector sin cubrir. Sin SQL directo/admin global,
agenda/reconciliación, H17 residual, H05, U12c, pagos, H11, roles o reparación histórica.
La activación conserva los requisitos R1/R2. Finales locales posteriores a CI se
identificarán como tales. Las cachés pytest-cache-files-* ilegibles del host se excluyen
explícitamente de la afirmación de integridad; no se cambian permisos.
