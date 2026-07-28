import asyncio
from collections.abc import Sequence

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from src.app.core.settings.app import get_app_settings
from src.app.models import Base

target_metadata = Base.metadata


def _database_url() -> str:
    settings = get_app_settings()
    if settings.db_url is None:
        raise RuntimeError("DB_URL is not configured; cannot run migrations.")
    return str(settings.db_url)


def _include_object(obj: object, name: str | None, type_: str, reflected: bool, compare_to: object) -> bool:
    # pgvector installs its own tables/types in the same schema; never let
    # autogenerate propose dropping them.
    return not (type_ == "table" and name is not None and name.startswith("vector_"))


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_object=_include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())


__all__: Sequence[str] = ()
