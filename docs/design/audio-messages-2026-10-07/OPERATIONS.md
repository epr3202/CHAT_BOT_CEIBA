# W2-c — Comandos para Emerson después del merge

Estos comandos quedan para ejecución humana. El agente no ejecutó seed, sync,
modificaciones de `.env`, migraciones ni recreación de servicios en producción.
La ruta `/home/deploy/bin/verify_release.sh` y su invocación sin argumentos se
comprobaron leyendo el script, sin ejecutarlo. La migración 0036 se aplica con el
código nuevo antes de arrancar app/worker. El primer arranque mantiene ASR apagado.

## Publicación con flag apagado

Ejecutar en la VPS, una vez integrado y actualizado el checkout por el proceso habitual:

```bash
set -euo pipefail
cd /home/deploy/chat_bot_ceiba
cp -p .env ".env.bak-audio-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - <<'PY'
from pathlib import Path
path = Path('.env')
values = {
    'OPENROUTER_MODEL_AUDIO': 'google/gemini-2.5-flash',
    'AUDIO_TRANSCRIPTION_ENABLED': 'false',
}
lines = path.read_text().splitlines()
lines = [line for line in lines if line.partition('=')[0].strip() not in values]
path.write_text('\n'.join(lines + [f'{key}={value}' for key, value in values.items()]) + '\n')
PY
docker compose build app worker
docker compose run --rm --no-deps app alembic upgrade head
docker compose up -d --no-deps --force-recreate app worker
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-connrefused http://127.0.0.1:8000/ready
/home/deploy/bin/verify_release.sh
```

No ejecutar el seed general ni sync como parte de estos pasos. Las dos plantillas
nuevas permanecen DRAFT; el arranque con `ENABLED=false` no exige publicarlas.
El downgrade 0036 falla deliberadamente si ya hay ejecuciones AUDIO_TRANSCRIPTION;
no borrar historia para forzarlo. Apagar el flag conserva transcripciones existentes.

## Canario, solamente después de la aprobación de Leandro

Publicar exclusivamente los dos textos aprobados mediante versiones nuevas. El seed
genérico siempre los propone DRAFT y añade `[REVISAR]`; este paso explícito retira
ese prefijo únicamente para la publicación humana aprobada. Si la última versión ya
es APPROVED y contiene el mismo texto, no crea otra. No publica otros códigos.

```bash
set -euo pipefail
cd /home/deploy/chat_bot_ceiba
docker compose exec -T app python - <<'PY'
import asyncio
from dataclasses import replace
import app.models_registry  # noqa: F401
from sqlalchemy import select
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries

async def main():
    settings = get_settings()
    engine = create_engine(settings.database_url)
    db = create_sessionmaker(engine)
    codes = {'RESP-AUDIO-TOO-LONG-001', 'RESP-AUDIO-WRITTEN-CONFIRM-001'}
    entries = [entry for entry in iter_seed_entries() if entry.code in codes]
    assert {entry.code for entry in entries} == codes
    approved = []
    try:
        async with db() as session:
            for entry in entries:
                body = entry.answer_template.removeprefix('[REVISAR] ')
                latest = await session.scalar(
                    select(KnowledgeEntry).where(KnowledgeEntry.code == entry.code)
                    .order_by(KnowledgeEntry.version.desc()).limit(1)
                )
                if latest and latest.status == 'APPROVED' and latest.answer_template == body:
                    continue
                approved.append(replace(
                    entry, status='APPROVED', answer_template=body,
                    version=latest.version + 1 if latest else 1,
                ))
        print('audio templates inserted:', await load_knowledge_entries(db, approved))
    finally:
        await engine.dispose()

asyncio.run(main())
PY
cp -p .env ".env.bak-audio-canary-$(date -u +%Y%m%dT%H%M%SZ)"
python3 - <<'PY'
from pathlib import Path
phone = '<NUMERO_DE_PRUEBAS_EMERSON_NORMALIZADO>'
assert '<' not in phone, 'Reemplaza el placeholder por el número de pruebas autorizado'
path = Path('.env')
values = {
    'AUDIO_TRANSCRIPTION_ENABLED': 'true',
    'AUDIO_TRANSCRIPTION_ALLOWED_PHONES': phone,
    'AUDIO_TRANSCRIPTION_ALLOW_ALL': 'false',
}
lines = [line for line in path.read_text().splitlines()
         if line.partition('=')[0].strip() not in values]
path.write_text('\n'.join(lines + [f'{key}={value}' for key, value in values.items()]) + '\n')
PY
docker compose up -d --no-deps --force-recreate app worker
curl --fail --silent --show-error --retry 10 --retry-delay 2 --retry-connrefused http://127.0.0.1:8000/ready
/home/deploy/bin/verify_release.sh
```

Readiness de app y worker bloquea `ENABLED=true` si falta la última versión APPROVED
de cualquiera de las dos plantillas. Mantener `ALLOW_ALL=false` durante el canario.
El E2E debe medir voz real, acento colombiano y ruido real; S0 usó TTS sintético.

## Forense read-only del E2E

Reemplazar ambos placeholders. El número se usa solo como filtro y nunca se proyecta.
La fecha delimita únicamente el E2E. No seleccionar `transcript`, `raw_output`,
`Message.content`, URLs ni referencias de media.

```bash
docker compose exec -T \
  -e PGOPTIONS="-c default_transaction_read_only=on -c statement_timeout=15000" \
  db psql -X -v ON_ERROR_STOP=1 -P pager=off -U ceiba -d ceiba \
  -v test_phone='<NUMERO_DE_PRUEBAS_EMERSON_NORMALIZADO>' \
  -v e2e_since='<INICIO_E2E_UTC>' <<'SQL'
BEGIN READ ONLY;
WITH e2e AS (
  SELECT m.id FROM message m JOIN customer c ON c.id=m.customer_id
  WHERE c.phone_number=:'test_phone' AND m.created_at>=:'e2e_since'::timestamptz
)
SELECT t.status, count(*) AS transcriptions,
       min(t.duration_ms) AS min_duration_ms, max(t.duration_ms) AS max_duration_ms,
       min(t.size_bytes) AS min_bytes, max(t.size_bytes) AS max_bytes,
       min(length(t.transcript)) AS min_chars, max(length(t.transcript)) AS max_chars,
       count(t.ai_execution_id) AS linked_ai_executions
FROM message_transcription t JOIN e2e ON e2e.id=t.message_id GROUP BY t.status;

WITH e2e AS (
  SELECT m.id FROM message m JOIN customer c ON c.id=m.customer_id
  WHERE c.phone_number=:'test_phone' AND m.created_at>=:'e2e_since'::timestamptz
)
SELECT a.task, a.model, a.prompt_version, a.success, a.validation_status, a.error_reason,
       count(*) AS executions, min(a.latency_ms) AS min_ms, max(a.latency_ms) AS max_ms,
       sum(coalesce((a.input_payload->'tokens'->>'total_tokens')::int,0)) AS total_tokens,
       count(*) FILTER (WHERE a.raw_output IS NOT NULL) AS unexpected_raw_outputs,
       count(*) FILTER (WHERE a.input_character_count<>0) AS unexpected_input_chars
FROM ai_execution a JOIN e2e ON e2e.id::text=a.input_payload->>'message_id'
WHERE a.task='AUDIO_TRANSCRIPTION'
GROUP BY a.task,a.model,a.prompt_version,a.success,a.validation_status,a.error_reason;

WITH e2e AS (
  SELECT m.id FROM message m JOIN customer c ON c.id=m.customer_id
  WHERE c.phone_number=:'test_phone' AND m.created_at>=:'e2e_since'::timestamptz
)
SELECT a.action, count(*) AS events
FROM audit_event a JOIN e2e ON e2e.id::text=a.new_value->>'message_id'
WHERE a.action LIKE 'AUDIO_%' GROUP BY a.action ORDER BY a.action;
ROLLBACK;
SQL
```
