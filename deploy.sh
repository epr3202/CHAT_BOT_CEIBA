#!/usr/bin/env bash
set -euo pipefail

git fetch origin main
git reset --hard origin/main

docker compose build app worker
docker compose run --rm app alembic upgrade head
docker compose up -d app worker

deadline=$((SECONDS + 30))
until curl -sf http://localhost:8000/health >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "Health check failed after 30 seconds" >&2
    exit 1
  fi
  sleep 2
done

deployed_sha="$(git rev-parse HEAD)"
deployed_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
echo "Deployed ${deployed_sha} at ${deployed_at}"
