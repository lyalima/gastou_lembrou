#!/usr/bin/env sh
set -eu

exec celery -A config beat -l info --schedule=/tmp/celerybeat-schedule
