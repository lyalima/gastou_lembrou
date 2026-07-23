#!/usr/bin/env sh
set -eu

exec celery -A config worker -l info
