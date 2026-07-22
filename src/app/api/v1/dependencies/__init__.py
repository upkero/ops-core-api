from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.bootstrap.container import ApplicationContainer
from src.app.repositories.booking import SqlAlchemyBookingRepository
from src.app.repositories.customer import SqlAlchemyCustomerRepository
from src.app.repositories.pricing import SqlAlchemyPricingRepository
from src.app.services.booking import BookingService
from src.app.services.customer import CustomerService
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


ContainerDep = Annotated[ApplicationContainer, Depends(get_container)]
DBSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


# Services are assembled per request because they wrap the request-scoped
# session. Only the session-free dependencies live on the container.
def get_customer_service(session: DBSessionDep) -> CustomerService:
    return CustomerService(SqlAlchemyCustomerRepository(session))


def get_booking_service(session: DBSessionDep) -> BookingService:
    return BookingService(SqlAlchemyBookingRepository(session), SqlAlchemyCustomerRepository(session))


def get_pricing_service(session: DBSessionDep, container: ContainerDep) -> PricingService:
    return PricingService(SqlAlchemyPricingRepository(session), container.discount_policy)


CustomerServiceDep = Annotated[CustomerService, Depends(get_customer_service)]
BookingServiceDep = Annotated[BookingService, Depends(get_booking_service)]
PricingServiceDep = Annotated[PricingService, Depends(get_pricing_service)]
