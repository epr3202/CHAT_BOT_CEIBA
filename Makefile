TEST_ENV = DATABASE_URL=postgresql+asyncpg://ceiba:ceiba@localhost:5432/ceiba DB_POOL_SIZE=5 DB_MAX_OVERFLOW=5 META_APP_SECRET=test META_VERIFY_TOKEN=test META_ACCESS_TOKEN=test META_PHONE_NUMBER_ID=test META_GRAPH_API_VERSION=v20.0 WEBHOOK_MAX_BODY_BYTES=1048576 OUTBOX_POLL_INTERVAL_SECONDS=0.01 OUTBOX_BATCH_SIZE=10 OUTBOX_SENDING_TIMEOUT_SECONDS=120 OUTBOX_MAX_ATTEMPTS=5 OUTBOX_MAX_BACKOFF_SECONDS=300 OPENROUTER_API_KEY=test OPENROUTER_BASE_URL=https://openrouter.ai/api/v1 OPENROUTER_TIMEOUT_SECONDS=15 OPENROUTER_MAX_RETRIES=1 AI_CONFIDENCE_SAFE=0.85 AI_CONFIDENCE_PROBABLE=0.70 AI_CONFIDENCE_UNCERTAIN=0.50 ENVIRONMENT=testing LOG_LEVEL=INFO
PYTHON ?= .venv/bin/python

.PHONY: migrate downgrade migrate-cycle test lint audit-conns

migrate:
	$(TEST_ENV) $(PYTHON) -m alembic upgrade head

downgrade:
	$(TEST_ENV) $(PYTHON) -m alembic downgrade base

migrate-cycle:
	$(MAKE) migrate
	$(MAKE) downgrade
	$(MAKE) migrate

test:
	.venv/bin/pytest -q

lint:
	.venv/bin/ruff check .

audit-conns:
	docker compose exec -T db psql -U ceiba -d ceiba -c "select pid, state, wait_event_type, wait_event, left(query, 120) as query from pg_stat_activity where datname = 'ceiba' order by pid;"
