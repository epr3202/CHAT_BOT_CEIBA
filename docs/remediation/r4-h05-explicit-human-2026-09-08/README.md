# R4 — H05.solicitud_explicita

Contrato previo al RED. Base exacta `b696d333034e3631612fcb203d66d6953a8cbe08`,
run R3 aprobado 34253137097, 771 nodos únicos y focal acumulado 136 incluido en
ese total. Alembic 20260908_0026. Rama `fix/r4-h05-explicit-human-20260908`.

## Reconocimiento y aplicación previstos

Reconocedor puro pequeño en `app/conversation/explicit_human.py`, llamado al inicio
de `classify_message` en `app/channel/inbound.py`, solo si `message_type == text`.
Se devuelve ClassifiedTurn con procedencia DETERMINISTIC y HUMAN_REQUEST antes
de servicios, confirmaciones, clasificación o extracción. No existe llamada a IA
para resumir: create_handoff ya usa un resumen determinista.

IntentClassification se reutiliza como formato técnico: confidence=0 es un campo
estructural sin probabilidad de modelo, reasoning_code identifica explícitamente
la regla. El orquestador reconoce esa procedencia después de los guards humanos,
antes de resolver propuestas pendientes o umbrales de confianza de IA, y llama a
la ruta HUMAN_REQUEST existente. No se añade una ruta de escrituras paralela.

R2 conserva adquisición, fingerprint, orden y propiedad por claim_token. apply_turn
recarga el propietario/contexto y confirma caso, pausa, auditoría, Outbox y
COMPLETED en su transacción. WebhookEvent mantiene su proyección posterior.
La ruta existente limpia la confirmación y el borrador de visita al transferir;
no aplica nombre, fecha, cotización ni pago pendientes como si fueran aceptados.

## Catálogo estrecho

Se normalizan mayúsculas, espacios y tildes. Coincidencia completa de frases, no
substring. Se toleran signos de pregunta/exclamación, punto final y cortesía
«por favor» al inicio/final. Una repetición compuesta solo por peticiones positivas
se reconoce. Se mantienen las citas, condicionales y contenido adicional fuera del
catálogo; no se interpreta como negativo seguro lo que no se reconoce.

Positivos mínimos: «Quiero hablar con un asesor», «Necesito hablar con una asesora»,
«¿Me puedes comunicar con un asesor?», «Por favor, pásame con una persona del
equipo», «Quiero que me atienda una persona». También las equivalencias estrechas
«Quiero hablar con una persona/alguien», «Pásame un asesor» y «Necesito una persona».
«No quiero más información; quiero hablar con un asesor» tiene una primera cláusula
expresamente acotada que niega información, no la transferencia. No existe veto
global por encontrar la palabra «no».

Sin reconocimiento: «No quiero hablar con un asesor», «No necesito un asesor, solo
el catálogo», «Si necesito un asesor después, les aviso», «Mi pareja quiere hablar
con un asesor», «¿Qué hace un asesor?», «El mensaje dice: quiero hablar con un
asesor», «No, gracias», palabras con coincidencia parcial, citas, retirada o
contradicción posterior. Mezclas con quejas/emergencias/pagos u otros asuntos
quedan en la ruta previa, conservando sus prioridades. No se añade un clasificador
general ni una regla que detecte cualquier aparición de «asesor».

Entrada cubierta: texto. No se incorporan botones, títulos interactivos ni captions;
no se inventan IDs públicos y se conserva el router multimedia H03. Frases fuera
del catálogo, nombres de asesores y solicitudes implícitas siguen en el flujo previo.

## Estados y efectos

Se cubren BOT_ACTIVE, captura de datos, servicios y catálogo, y confirmaciones
pendientes en estados cuya transición humana admite la ruta existente. No se
amplían ALLOWED_TRANSITIONS. WAITING_FOR_HUMAN, HUMAN_ACTIVE y bot deshabilitado
conservan silencio, asignación y contexto; un positivo tampoco invoca IA en ellos.
El guard CLOSED y los restantes estados siguen bajo el contrato R2/orquestador.

Resultado activo: Message conservado, un Handoff PENDING con CUSTOMER_REQUEST y
prioridad NORMAL, resumen vigente con identidad/motivo/últimos mensajes disponibles,
HANDOFF_CREATED, estado WAITING_FOR_HUMAN y RESP-HANDOFF-001 dentro del horario o
RESP-HANDOFF-002 fuera. Se exige KnowledgeEntry aprobada en los escenarios.
La pausa se demuestra por estado y un turno posterior silencioso; no se exige
bot_enabled=False. Reentrega y otra petición con ID distinto no duplican el caso.
La consulta autenticada GET /admin/handoffs debe mostrar el caso; no acredita
notificación externa, recepción ni atención efectiva de una persona.

Fuentes: FL-015, HUMAN_REQUEST, BR-HAND-002/003/007/009/010, TC-HAND-001/002 y
estados humanos. H05 corresponde a PR-06b/U21 en la auditoría y backlog V0.
Discrepancias/límites previos: TC-HAND-003 menciona responder al cliente ya escalado;
el encargo R4 y los guards vigentes exigen silencio. El resumen actual contiene
identidad, motivo y últimos mensajes, no todos los campos estructurados enumerados
por FL-015/BR-HAND-002. Se conserva el servicio autorizado, sin certificar ese
catálogo completo ni implementar notificaciones nuevas. Los umbrales documentados
de confianza son para propuestas IA; esta regla tiene procedencia determinista.

## RED y conservación

Primer ensayo: dos pruebas funcionales, BOT_ACTIVE con ConnectError sintético y
COLLECT_SERVICES con principal válida más ReadError auxiliar. Cero llamadas IA es
el criterio esperado y se inspeccionan SQL y bandeja real antes de afirmar el
resultado. Otros cuatro controles ejercitan consulta válida, fallback R3, negación
y cita con proveedor simulado. No importan un reconocedor aún inexistente: un
fallo de importación/preparación no se declararía RED funcional.

Los criterios de test_r4_red.py se conservarán. Los 771 IDs históricos y los 136
focales se inventarían desde el artefacto aprobado; no se sumará dos veces el focal.
Adaptaciones históricas previstas y acotadas, solo después del RED:

- `test_tc_b1_005_human_request_interrupts_without_losing_capture_context` exige
  actualmente una llamada principal con la frase inequívoca. Cambiar esa expectativa
  a cero y reforzar pausa/caso conservando las aserciones del contexto.
- `test_slice1_direct_and_critical_handoffs_create_summary_audit_and_state` prepara
  una secuencia HUMAN_REQUEST seguida de EMERGENCY. La primera respuesta simulada
  dejará de consumirse; ajustar la preparación y comprobar cero llamadas hasta la
  primera transferencia, conservando las aserciones de emergencia.

Las versiones históricas y sus resultados permanecen en BASE/RED. Los tests R3
seguirán ejercitando transporte mediante sus textos sintéticos originales.

## CI, evidencias y límites

Solo Actions: workflow independiente por push R4, dos jobs, fail-fast desactivado,
checkout por SHA, Python 3.12 y PostgreSQL 16 efímero. Runner derivado de R3,
aislamiento R0 intacto; destinos, propietario, versión e instancia atestados;
red externa bloqueada, sin puertos ni token GitHub en los tests. El focal migra
realmente a 0026 y no recrea metadata. Ruff y colección/fases exactas mantienen
el gate fallido ante cualquier error; always() solo conserva evidencia.

Comandos dentro de Actions: `python scripts/quality/r4/run_ci.py suite` y
`python scripts/quality/r4/run_ci.py regressions`. No ejecutar producto local.
Se conservarán todos los intentos, ZIP, hashes, matriz, colección, pruebas adaptadas
y diff Git BASE→CANDIDATE comprobado en una copia limpia de BASE. Informes y notas
posteriores a CI se identificarán como locales y no pertenecientes al SHA probado.

Sin migraciones previstas, sin cambios de prompts/modelos/retries/dependencias.
H05.agotamiento_fallback queda abierto y separado; no se inventan umbrales ni menús.
Una petición detrás de trabajo FAILED/REVIEW/EXTERNAL no salta el orden de R2.
H03/H17/H29/H02.payment, orden de salida y autorizaciones no se remedian aquí.

Activación futura, no ejecutada: coordinación API/BackgroundTasks/workers/CLI
heredada de R1/R2; no consumidores antiguos concurrentes ni replay de historia
ambigua. Rollback preserva ledger e incertidumbre; no downgrade ni borrado para
limpiar errores. Sin PR, merge, tag, despliegue, SSH/VPS ni afirmación productiva.

## Candidato después del RED funcional

RED `75cb27901f6907099101d0515982e565ffbb7c63`, run 34267180516: el focal
demuestra dos fallos funcionales en call y 140 PASS, con 142 setup/call/teardown.
Los 136 históricos y cuatro controles nuevos pasan. El caso activo invocó una
clasificación; servicios invocó principal y auxiliar. La consulta administrativa
respondió 200: no fue un error de preparación, importación ni conexión no simulada.

Se añaden 67 nodos R4 en total: los seis criterios RED intactos, 34 frases y
27 escenarios de flujo. Colección esperada: 838 en suite y 203 en focal incluido.
Solo se modifican dos nodos históricos según lo documentado; sus IDs y las demás
aserciones permanecen. El resto de R1/R2/R3 y las 26 migraciones están protegidos.

El primer candidato `c13ce71e268d0575eb1db0c59026b4d1b4eefc25`, run 34268231895,
pasó las 203 pruebas del focal, pero el gate falló por I001 (separación de imports
en la prueba pura nueva). Se conserva el intento y se corrige solo ese formato;
no se cambia producto, criterio RED ni aserciones para la siguiente ejecución.
