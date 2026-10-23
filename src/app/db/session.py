import sqlalchemy.ext.asyncio as sa_asyncio
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.app.core.settings.app import get_app_settings


def build_engine(database_url: str) -> AsyncEngine:
    settings = get_app_settings()
    # Spans for every statement, with the request's span as parent, and the pool gauges.
    # The instrumentor patches `create_async_engine` on its module, so the engine is built
    # through the module: a name imported earlier would still be the unpatched function.
    instrumentor = SQLAlchemyInstrumentor()
    if not instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.instrument()
    return sa_asyncio.create_async_engine(
        database_url,
        pool_pre_ping=True,
        # Without these a stuck statement, or a lock held by a request that died, holds a pooled
        # connection for as long as it likes, and "slow ops-core" has no upper bound.
        connect_args={
            "server_settings": {
                "statement_timeout": str(settings.db_statement_timeout_ms),
                "lock_timeout": str(settings.db_lock_timeout_ms),
            }
        },
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
