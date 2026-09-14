#!/bin/sh
set -eu
# Image entrypoint owns the marker; an inherited false cannot bypass deployment guards.
export DEPLOYED_RUNTIME=true
case "${ENVIRONMENT:-}" in staging|production) ;; *) echo 'Explicit protected ENVIRONMENT required' >&2; exit 1;; esac
python -m app.config.readiness storage
exec "$@"
