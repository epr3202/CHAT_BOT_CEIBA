# R3 - H04: degradacion de fallos de transporte de IA

Contrato definido antes del arreglo. Base exacta R2
`163272a60260641c3e7780105ee2841d9adfba3f`, run 34246368928, head 0026.
Rama `fix/r3-h04-ai-20260908`. Solo Actions; no PR, main, VPS ni despliegue.

## Taxonomia y presupuesto propuestos

| Excepcion/respuesta | Normalizacion | Retry del cliente | Consumidor y salida |
|---|---|---|---|
| ConnectError, ReadError, WriteError, CloseError durante el POST | AIUnavailable(HTTP_ERROR), detalle con tipo tecnico | Hasta MAX_RETRIES + 1 llamadas | Principal: fallback/clarificacion o handoff critico; extractor: conserva clasificacion principal; servicios: aclaracion existente |
| RemoteProtocolError, ProxyError del transporte | AIUnavailable(HTTP_ERROR), tipo tecnico | Mismo presupuesto acotado; no garantia de que el siguiente intento funcione | Misma ruta segun tarea y estado |
| ConnectTimeout, ReadTimeout, WriteTimeout, PoolTimeout | AIUnavailable(TIMEOUT), tipo tecnico | Presupuesto existente | Misma ruta, TIMEOUT distinguible |
| HTTPStatusError (4xx/5xx) | AIUnavailable(HTTP_ERROR) | Politica previa conservada, incluso retry de 4xx; R3 no declara todos transitorios | Fallback existente por tarea |
| JSON invalido | AIUnavailable(INVALID_JSON) | Sin retry adicional de parseo | Contrato previo |
| Esquema invalido | AIUnavailable(SCHEMA_VIOLATION) | Sin retry adicional de validacion | Contrato previo; H29 no cambia |
| LocalProtocolError, UnsupportedProtocol, InvalidURL | Se propagan como uso/configuracion | No nuevo retry | Manejo de error R2; no falsa indisponibilidad transitoria |
| CancelledError | Se propaga como cancelacion | No retry del cliente | R2 libera/revisa solo su propia adquisicion; no COMPLETED por cancelar |
| RuntimeError/AssertionError de programacion o guard | Se propagan | No nuevo retry | Fallo visible; no catch-all que devuelva fallback |

HTTP_ERROR ya representa llamada fallida en la telemetria existente; el subtipo
sanitizado en error/detail distingue transporte de estado HTTP sin nueva categoria
ni DDL. TIMEOUT permanece separado. No se altera INVALID_JSON/SCHEMA_VIOLATION ni
la validacion semantica. La captura se limita a las familias esperables durante la
peticion; no convierte todo HTTPError/TransportError en transitorio. Errores de uso
del cliente y cierre explicito fuera de la peticion no reciben una politica nueva.

La jerarquia se contrasta con HTTPX instalado en cada job (version y MRO en
artefacto) y la [documentacion oficial de HTTPX](https://www.python-httpx.org/exceptions/).
La [documentacion Python 3.12](https://docs.python.org/3.12/library/asyncio-exceptions.html)
explica la propagacion de CancelledError como BaseException.

OPENROUTER_MAX_RETRIES y OPENROUTER_TIMEOUT_SECONDS conservan defaults y significado.
Los contadores se separan por INTENT_CLASSIFICATION, EVENT_TYPE_EXTRACTION y
SERVICES_CLASSIFICATION; una tarea auxiliar no cuenta como retry del clasificador.
Los reintentos del cliente no son adquisiciones de InboxJob.

## Prueba y proteccion

Primero se publica un RED contra producto R2 intacto: ConnectError/ReadError del
cliente, flujo nuevo BOT_ACTIVE y dos auxiliares realmente alcanzados, con controles
validos. Se usan parser/orquestador/DB reales y dobles HTTP estrictos por tarea.
Los nuevos casos ampliaran la matriz sin modificar el criterio RED.

El workflow `remediation-r3-ai.yml` corre solo por push R3, con jobs independientes
suite y regressions. Deriva launcher/driver de R2, conserva el guard R0, protege
los 706 nodos y 71 focales y compara la lista explicita de casos R3. El focal usa
Alembic hasta 0026; no reemplaza su esquema con metadata. Ambos jobs usan el SHA
candidato exacto, imagen Python 3.12, PostgreSQL 16 nuevo, rol/destino/propietario/
system_identifier atestados y red externa bloqueada. No se pasa token GitHub a tests.
Ruff y setup/call/teardown deben pasar; subir artefactos siempre no cambia el gate.

Dentro de Actions: `python scripts/quality/r3/run_ci.py suite` y
`python scripts/quality/r3/run_ci.py regressions`, con variables de identidad del job.
No ejecutar producto/pruebas en el PC. La autorizacion especifica permite publicar
RED antes del verde; no se usa git add indiscriminado sobre el arbol del usuario.

## Limites

No cambia inbox, outbox, propiedad, EXTERNAL/REVIEW, backoff ni ledger. No se preve
migracion. Se conservan prompts, modelos, clasificacion historica de turnos humanos,
reglas comerciales, payment, agenda y dependencias. H05 sigue abierto: un fallback
de estado critico no demuestra solicitud explicita de asesor independiente de IA.
Tambien permanecen H03/H17/H29 y los otros hallazgos ajenos a H04.

La activacion futura hereda R1/R2: API, BackgroundTasks, workers y CLI coherentes,
sin consumidores antiguos concurrentes y con seleccion/reconciliacion de legacy
e incertidumbre externa. No se ejecuta. Un rollback no debe borrar ni bajar el
ledger para limpiar errores; se preservan datos y evidencia. No hay conclusion
sobre el VPS ni autorizacion de produccion.

Informe final, matriz y ZIP descargados pueden quedar solo locales despues del CI;
el cierre distinguira esos archivos de los publicados en el candidato.

## Implementacion candidata y reproduccion verificada

El intento 34250301495 solo detecto un fallo de preparacion del driver R3 (escritura
de jerarquia antes de crear /quality-output); sus artefactos se conservan y no
cuentan como reproduccion H04. Corregido solo ese orden, el RED
`7629d4bc38f8d9f2fa8e1a51342805d073bf2bf4`, run 34250711362, acredita en el focal
79 casos: 73 PASS y 6 FAIL, con 79 setup/call/teardown completos. Pasan los 71 R1/R2
y los dos controles validos; fallan dos contratos del cliente, dos flujos BOT_ACTIVE
y ambas tareas auxiliares. Las excepciones escaparon sin normalizar y los trabajos
quedaron PENDING; no son fallos de fixture, tabla ni dobles HTTP.

El cambio de producto se limita a client.py: captura explicita de NetworkError,
RemoteProtocolError y ProxyError en _post_with_retries; sanitizacion del detalle de
timeout/estado HTTP/transporte y del warning best-effort de persistencia. No cambia
AIUnavailable, enum, modelos, prompts, defaults, consumidores ni esquema. Una
escritura SQL fallida de AIExecution no reemplaza el resultado de la tarea.

65 casos R3 forman la matriz candidata: 8 criterios RED intactos, 37 contratos de
cliente y 20 controles de flujo/propiedad. Se exige 706 + 65 en suite y 71 + 65 en
focal, sin sumar el focal de nuevo. La cifra deriva de las familias comprobadas y
se valida por lista exacta de nodos. El control de varias salidas legitimas tambien
permanece en las regresiones R2 retenidas, sin imponer unicidad por entrada.

El primer candidato tuvo un fallo de expectativa en la prueba nueva del estado
critico: exigia bot_enabled=False, pero el handoff vigente pausa por el estado
WAITING_FOR_HUMAN y conserva ese flag. Se corrige esa expectativa explicitamente:
se exige conservar el flag y se comprueba silencio efectivo en un turno posterior
real, sin repetir Outbox/handoff. No se cambia producto ni se remedia H03.
