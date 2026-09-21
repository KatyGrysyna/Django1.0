#!/bin/sh

set -e

echo "Waiting for PostgreSQL..."

while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 0.5
done

echo "PostgreSQL is up"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec python manage.py runserver 0.0.0.0:8000