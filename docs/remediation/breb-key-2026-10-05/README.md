# Bre-B en las instrucciones de pago — entrega para revisión

Rama feat/breb-key desde main f703533d37900fbae428c60a9e560545fb4c43e2,
merge sin squash del PR #42. La autorización de ese merge no alcanza este PR.
No hay migraciones, nuevos estados/pending_action, consultas de producción,
verificación automática ni cambios al flujo de comprobantes.

## M1–M2: mini-censo

[G1.md](G1.md) documenta configuración, plantilla, handler, presenters y
publicación por seed + sync con referencias de la base anterior al cambio.

- M1: cuatro campos BOOKING_*; RESP-BOOKING-PAYMENT-001, versión productiva v2
  documentada, cinco variables. El handler pasa Settings. El loader de deploy
  conserva código+versión y debe recibir v3 explícita para publicar este cambio.
  Sync también respeta ese mínimo; su prohibición de CLI en production continúa.
- M2: recordatorio_saldo_reserva (Meta, es) lleva datos bancarios literales
  propios y no se modifica. No se encontraron otros mensajes bancarios literales.

## R1–R4: implementación

| Requisito | Evidencia |
|---|---|
| R1 | app/config/settings.py:115, .env.example:55; app/config/readiness.py:26 valida BANK_BREB_KEY en producción si la última versión de PAYMENT está APPROVED y su texto usa breb_key; app/main.py:32 y app/channel/worker.py:647 lo ejecutan antes de atender. Ambos cierran el engine aun si falla. |
| R2 | docs/conversation/approved-responses.md:2890 prepara v3 con la única línea añadida «Llave Bre-B: {breb_key}» y seis variables. data/knowledge_seed.py:35 declara v3 solo para este código; scripts/sync_knowledge_versions.py:61 y :84 respetan el mínimo al crear/incrementar, con historial INACTIVE. |
| R3 | app/orchestrator/booking_flow.py:577 consulta la última versión; :589 extiende el guard bancario antes de crear la solicitud; :676 pasa breb_key desde Settings solo cuando la plantilla la usa. app/conversation/presentation.py:301 acepta únicamente Settings. Omisión en allowed_variables sigue produciendo KnowledgeRenderError / UNKNOWN_VARIABLE. |
| R4 | approved-responses.md:2890 y docs/decisions.md:296 documentan la decisión de Emerson del 2026-10-05, la línea propuesta, publicación y verificación por comprobante más humano. |

La copia anterior permanece íntegra al retirar la nueva línea y sus saltos.
La versión anterior sin breb_key no exige la llave ni recibe una variable extra.
La configuración vacía no crea una solicitud de pago: sigue el handoff bancario
existente. Los textos Meta, revisión humana y procesamiento de comprobantes
permanecen iguales.

## G2 rojo y G3 verde

La ejecución inicial se hizo antes de implementar, sobre main f703533:

```text
29 failed, 5 passed in 31.59s
```

Los 29 fallos son assertions. [G2-red-assertions.out](G2-red-assertions.out)
contiene los fallos y [G2-red.out.gz](G2-red.out.gz) conserva el stdout íntegro.
G2 se congeló en f0d3b58, con hashes en [G2.sha256](G2.sha256).

```text
G2: 34 passed in 26.30s
Knowledge/settings: 48 passed in 25.82s
Reserva/pago: 197 passed in 547.71s (0:09:07)
Alineación de plantillas: 19 passed in 5.41s
Fixtures y E2E existente: 3 passed in 8.18s
Ruff: All checks passed!
```

Son 264 casos distintos en los tres subsets finales; G2 y el E2E están incluidos
allí, por lo que no se suman otra vez. Las salidas completas están en
[G2-green.out](G2-green.out), [final-units-green.out](final-units-green.out),
[final-booking-green.out](final-booking-green.out),
[final-alignment-green.out](final-alignment-green.out),
[legacy-e2e-green.out](legacy-e2e-green.out) y [final-ruff.out](final-ruff.out).
[commands.txt](commands.txt) permite repetir los subsets con datos sintéticos.
No se ejecutó la suite completa en local; la ejecuta CI.

## Commits por área y desviaciones declaradas

- f0d3b58 test: suite G2 roja, conforme a la autorización de tests primero.
- 8eb2909 test: único arreglo de mecanismo de G2: importar app.models_registry
  para registrar relaciones antes de instanciar KnowledgeEntry en ejecución
  aislada. No cambia ninguna expectativa. El rojo conjunto original no tenía
  ese error; el fallo aislado se reprodujo con el test original de f0d3b58
  fuera del checkout, sobre R1: 9 failed, 6 passed in 2.69s, en
  R1-config-mechanism-reproduction.out.gz. [G2-mechanism-corrected.sha256](G2-mechanism-corrected.sha256)
  fija los hashes posteriores, verificados sin cambios después de G3.
- e0366cb feat: configuración y arranque con docs de la regla.
- 1b8da5b feat: plantilla v3, seed/sync y docs de publicación.
- 6946724 feat: handler, presenter y docs del contrato de render.
- 5067038 test: alinear solo el literal de PAYMENT y las fixtures sintéticas
  antiguas. Dos assertions rojas antes del ajuste (legacy-red.out); contratos y
  E2E verdes después. No debilita guards ni cambia G2.

La integración de R1 exige validar también los entrypoints de API/worker;
R3 exige registrar el presenter. Se informó ese alcance antes de implementarlo.
La adaptación de sync al mínimo explícito del seed evita publicar otra v2 o una
v1 al crear una base nueva. No cambian los valores de versión del resto del seed.

Diff incremental contra f703533: 35 files changed, 1134 insertions(+), 36 deletions(-).

## Gate de publicación

Se hace un único push de feat/breb-key y se abre PR draft hacia main. El run de
CI se enlaza en el PR y la entrega final después del push. No se hace merge.
Claude revisa el diff; Leandro debe aprobar «Llave Bre-B: {breb_key}». Claude
coordina con Emerson BANK_BREB_KEY en .env de producción y la publicación de
la nueva versión. La marca APPROVED del seed preparado para revisión no declara
que esa aprobación o publicación productiva ya ocurrió.
