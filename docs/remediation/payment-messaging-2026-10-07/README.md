# Evidencias de mensajería de pagos — 2026-10-07

Base: dc50b3962ae66e42b4c74d07f4978e211ac4faaf, merge de #43.
[G1](G1.md) documenta causas, hipótesis, consultas y alcance antes de implementar.
G1.sql se ejecutó únicamente con el wrapper READ ONLY; G1-db.out omite cuentas,
llaves, teléfonos, imágenes y OCR. No se ejecutaron resets ni E2E.

| Gate | Resultado | Salida |
|---|---|---|
| G2, antes de implementar | 12 AssertionError, 8 passed; 80,10 s | evidence/G2-red.out |
| G3, nuevas G2 | 20 passed; 80,42 s | evidence/G3-g2-green.out |
| G3, presentación | 63 passed; 0,88 s | evidence/G3-presentation.out |
| Primera regresión | 1 fallo de literal anterior, 66 passed; 208,04 s | evidence/G3-subsets.out |
| Regresión tras actualizar fixtures | 457 passed; 1309,03 s | evidence/G3-subsets-v2.out |
| Ruff, worktree aislado completo | All checks passed | evidence/G3-ruff.out |

La actualización del literal PARTIAL conserva una expectativa independiente y
la igualdad exacta. Los fixtures añaden datos bancarios sintéticos completos y
los importes COP tipados; G1 declara esos cambios y la corrección del UUID del
nuevo caso de correlación. No se debilitó una aserción.

Se usó la expansión exacta `$(TEST_ENV)` del Makefile, con
`TEST_DATABASE_URL` dirigido a `ceiba_plan_test`, base local sintética. `make test`
no expande TEST_ENV; por eso se añadió el target temporal por stdin:

```sh
make --silent --no-print-directory -f Makefile -f - payment-messaging-g3-subsets-v2 <<'MAKE'
payment-messaging-g3-subsets-v2:
	$(TEST_ENV) TEST_DATABASE_URL=postgresql+asyncpg://ceiba:ceiba@172.18.0.2:5432/ceiba_plan_test /media/emerson/Datos_HDD/Proyectos/desarollo/chat_bot_ceiba/.venv/bin/python -m pytest -x -q tests/booking_conversation/ tests/payment_settlement/ tests/unit/test_knowledge.py tests/unit/test_breb_key_knowledge_g2.py tests/remediation/r9/test_r9_contract.py tests/integration/test_b1a_plan_reservation_admin.py::test_r5_existing_review_without_reservation_is_unchanged tests/integration/test_b1a_plan_reservation_admin.py::test_r5_b2_review_returns_linked_reservation_to_pending
MAKE
```

G2 inicial usó el mismo mecanismo, solo el nuevo archivo G2 y sin `-x`;
su verificación verde usó ese archivo con `-x`. Presentación usó únicamente
`tests/unit/test_slot_presentation_boundary.py`. No se ejecutó suite completa
local. No hay migraciones de esquema. Seed/load/sync publica PARTIAL v3,
PAYMENT-004 v4 y PENDING v1; PAYMENT v3 conserva su texto enviable.
