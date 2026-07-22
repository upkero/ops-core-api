#!/bin/sh
# Container entrypoint: bring the schema up to date, load demo data, serve.
set -eu

echo "Applying database migrations..."
alembic upgrade head

# Idempotent: a no-op once the database already holds data, so restarting the
# stack does not duplicate or reset anything.
echo "Seeding demo data..."
python -m src.app.cli.seed

echo "Starting API..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
