from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.bootstrap.container import ApplicationContainer
from src.app.contracts.pagination import DEFAULT_LIMIT, MAX_LIMIT, PaginationParams
from src.app.core.settings.app import get_app_settings
from src.app.repositories.booking import SqlAlchemyBookingRepository
from src.app.repositories.customer import SqlAlchemyCustomerRepository
from src.app.repositories.knowledge import SqlAlchemyKnowledgeRepository
from src.app.repositories.pricing import SqlAlchemyPricingRepository
from src.app.services.booking import BookingService
from src.app.services.customer import CustomerService
from src.app.services.knowledge import KnowledgeService
from src.app.services.pricing import PricingService


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


def get_pagination(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Rows per page.")] = DEFAULT_LIMIT,
    offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
) -> PaginationParams:
    """One definition of the paging query parameters, shared by every list endpoint."""
    return PaginationParams(limit=limit, offset=offset)


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]


# Services are assembled per request because they wrap the request-scoped
# session. Only the session-free dependencies live on the container.
def get_customer_service(session: DBSessionDep) -> CustomerService:
    return CustomerService(SqlAlchemyCustomerRepository(session))


def get_booking_service(session: DBSessionDep) -> BookingService:
    return BookingService(SqlAlchemyBookingRepository(session), business_tz=get_app_settings().business_tz)


def get_pricing_service(session: DBSessionDep, container: ContainerDep) -> PricingService:
    return PricingService(SqlAlchemyPricingRepository(session), container.discount_policy)


def get_knowledge_service(session: DBSessionDep, container: ContainerDep) -> KnowledgeService:
    return KnowledgeService(SqlAlchemyKnowledgeRepository(session), container.embedding_client)


CustomerServiceDep = Annotated[CustomerService, Depends(get_customer_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
PricingServiceDep = Annotated[PricingService, Depends(get_pricing_service)]
KnowledgeServiceDep = Annotated[KnowledgeService, Depends(get_knowledge_service)]
