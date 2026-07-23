#!/usr/bin/env sh
set -eu

if [ "${WAIT_FOR_DB:-0}" = "1" ]; then
  DB_HOST="${DB_HOST:-db}"
  DB_PORT="${DB_PORT:-5432}"
  until nc -z "$DB_HOST" "$DB_PORT"; do
    echo "Aguardando banco em $DB_HOST:$DB_PORT..."
    sleep 1
  done
fi

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  python manage.py migrate --noinput
fi

if [ "${RUN_COLLECTSTATIC:-0}" = "1" ]; then
  python manage.py collectstatic --noinput
fi

exec "$@"
