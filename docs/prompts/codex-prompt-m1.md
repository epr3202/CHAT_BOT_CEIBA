# Prompt Codex — M1: mantenimiento menor (ciclo completo autorizado, sin gates intermedios)

**Branch:** `m1-maintenance` (desde `main` post-merge de PR #13). Alcance cerrado de tres
ítems chicos; por su tamaño se autoriza ciclo completo sin paradas: tests rojos donde aplique →
implementación → push → PR draft → reporte único final. Invariantes de `AGENTS.md` vigentes;
cualquier cosa que crezca más allá de lo descrito = DETENTE.

## Ítem 1 — `.gitignore`

Agregar patrón `review-*.txt` (artefactos de revisión de frontera del arquitecto, viven en la
raíz, jamás se commitean). Sin test.

## Ítem 2 — `scripts/reset_local_conversation.py`: flag de producción explícito

Hoy el guard `ENVIRONMENT=production` obliga a un bypass por variable de entorno para el uso
legítimo (reset del número de prueba del operador en producción). Reemplazar ese patrón:

- Nuevo flag `--allow-production-phone`. En producción, el script se niega salvo que el flag
  esté presente **y** `--phone` sea explícito (nunca reset masivo en producción, con o sin flag).
- El dry-run sigue siendo default; `--execute` sigue siendo requerido para aplicar.
- En el `audit_event` que el script ya escribe, incluir que se usó el flag de producción.
- Test: en `ENVIRONMENT=production`, sin flag → rechaza; con flag + phone + execute → procede;
  con flag sin phone → rechaza.

## Ítem 3 — Reset del contador de servicios al (re)instalar la captura

`services_failed_understanding_count` no se reinicia cuando `COLLECT_SERVICES` se instala como
`pending_action`, así que un contador residual de un ciclo abandonado (cliente falló una
repregunta y se fue) hace que, semanas después, la primera falla del ciclo nuevo salte directo a
`OTHER`+handoff sin repregunta.

- Fix: poner el contador en 0 en el punto donde `COLLECT_SERVICES` se instala (el sitio único
  donde se fija esa `pending_action`; si hay más de uno, cubrir todos y declararlo en el reporte).
- Test rojo primero: conversación con `services_failed_understanding_count=1` residual y captura
  reinstalada → primera falla de resolución → `RESP-SERVICES-RETRY-001` (no `OTHER`); segunda
  falla → `OTHER` (la cadena completa se conserva dentro del ciclo nuevo).

## Reporte final

Commits (uno por ítem, prefijos `chore:`/`fix:`/`test:` según corresponda), resultado del CI en el
PR draft, transición rojo→verde de los tests de ítems 2 y 3, desviaciones (esperadas: ninguna).
