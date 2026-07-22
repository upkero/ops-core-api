from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.bootstrap.container import ApplicationContainer


def get_container(request: Request) -> ApplicationContainer:
    return request.app.state.container  # type: ignore[no-any-return]


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """One transaction per request.

    `session.begin()` commits on clean exit and rolls back on any exception, so
    repositories never call commit themselves and a service can mutate several
    aggregates atomically (booking insert + slot availability flip).
    """
    session_factory = request.app.state.container.session_factory
    async with session_factory() as session, session.begin():
        yield session


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
