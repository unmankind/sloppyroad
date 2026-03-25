#!/usr/bin/env bash
set -e

# Run Alembic migrations when explicitly enabled (app server only).
# The worker skips this — it depends on the app being healthy first.
if [ "${AIWN_RUN_MIGRATIONS:-0}" = "1" ] && [ -f /app/alembic.ini ]; then
    echo "Running database migrations..."
    alembic upgrade head
    echo "Migrations complete."
fi

exec "$@"
