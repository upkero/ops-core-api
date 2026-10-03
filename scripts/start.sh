#!/bin/sh
# Container entrypoint: bring the schema up to date, load demo data, serve.
set -eu

echo "Applying database migrations..."
alembic upgrade head

# Idempotent: once the database holds data only the missing slots (the rolling
# window ahead) are topped up, so restarting never duplicates or resets anything.
echo "Seeding demo data..."
python -m src.app.cli.seed

echo "Starting API..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
