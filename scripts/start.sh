#!/bin/sh
# Container entrypoint: bring the schema up to date, load demo data, serve.
set -eu

echo "Applying database migrations..."
if out=$(alembic upgrade head 2>&1); then
    echo "$out"
    # Idempotent: once the database holds data only the missing slots (the
    # rolling window ahead) are topped up, so restarting never duplicates or
    # resets anything.
    echo "Seeding demo data..."
    python -m src.app.cli.seed
else
    echo "$out" >&2
    case "$out" in
        *"Can't locate revision"*)
            # The database is ahead of this image: a deploy migrated it and was
            # rolled back. Migrations only add (expand/contract, see README), so
            # this code still works on the newer schema. Serve, and leave seeding
            # to the newer code, whose constraints the schema now has.
            echo "WARNING: database schema is newer than this image; starting without migrating or seeding." >&2
            ;;
        *)
            exit 1
            ;;
    esac
fi

echo "Starting API..."
exec uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 1 --no-access-log
