#!/usr/bin/env sh
set -eu

PORT="${PORT:-8000}"
WORKERS="${WEB_CONCURRENCY:-2}"

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WORKERS}" \
  --timeout 120 \
  --access-logfile -
