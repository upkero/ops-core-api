from functools import cached_property

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.app.core.settings.app import get_app_settings
from src.app.core.settings.embeddings import get_embedding_settings
from src.app.db.session import build_engine, build_session_factory
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.llm.embedding_factory import create_embedding_client


class ApplicationContainer:
    """Manual DI container. Holds only long-lived dependencies.

    Per-request objects (repositories, services) are built in api/v1/dependencies,
    because they need the request-scoped database session.
    """

    @cached_property
    def embedding_client(self) -> EmbeddingClient:
        return create_embedding_client(get_embedding_settings())

    @cached_property
    def _db_engine(self) -> AsyncEngine:
        settings = get_app_settings()
        if settings.db_url is None:
            raise RuntimeError("DB_URL is not configured.")
        return build_engine(str(settings.db_url))

    @cached_property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return build_session_factory(self._db_engine)

    async def close(self) -> None:
        for dependency in tuple(self.__dict__.values()):
            close = getattr(dependency, "close", None)
            if callable(close):
                await close()

        if "_db_engine" in self.__dict__:
            await self._db_engine.dispose()
