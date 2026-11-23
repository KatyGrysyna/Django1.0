#!/usr/bin/env bash
set -euo pipefail

cd /app

python manage.py migrate --noinput
python manage.py collectstatic --noinput

pids=()

cleanup() {
    trap - EXIT TERM INT
    if [ "${#pids[@]}" -gt 0 ]; then
        kill -TERM "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
}

trap cleanup EXIT
trap 'exit 0' TERM INT

gunicorn shop_project.wsgi:application \
    --bind "0.0.0.0:${PORT:-8000}" \
    --workers 1 \
    --access-logfile - \
    --error-logfile - &
pids+=("$!")

python -m celery -A shop_project worker \
    --loglevel=INFO \
    --concurrency=1 \
    --hostname=bookshop@%h &
pids+=("$!")

python -m celery -A shop_project beat \
    --loglevel=INFO \
    --schedule=/tmp/bookshop-celerybeat \
    --pidfile= &
pids+=("$!")

exit_status=0
wait -n "${pids[@]}" || exit_status=$?

echo "A bookshop process stopped with exit code ${exit_status}." >&2
if [ "$exit_status" -eq 0 ]; then
    exit_status=1
fi
exit "$exit_status"