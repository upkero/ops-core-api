from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.customer import CustomerDTO
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.interfaces.repositories.customer_repository import CustomerRepository
from src.app.models.customer import Customer
from src.app.repositories.pagination import paginate


def _to_dto(row: Customer) -> CustomerDTO:
    return CustomerDTO(
        id=row.id,
        name=row.name,
        status=row.status,
        last_contact_at=row.last_contact_at,
        notes=row.notes,
    )


class SqlAlchemyCustomerRepository(CustomerRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, customer_id: UUID) -> CustomerDTO | None:
        row = await self._session.get(Customer, customer_id)
        return _to_dto(row) if row is not None else None

    async def search_by_name(self, query: str, params: PaginationParams) -> PageDTO[CustomerDTO]:
        # ILIKE with an escaped pattern: a customer named "50% off" must not
        # turn into a wildcard search.
        pattern = f"%{query.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = select(Customer).where(Customer.name.ilike(pattern, escape="!")).order_by(Customer.name)
        return await paginate(self._session, stmt, params, _to_dto)

    async def list_all(self, params: PaginationParams) -> PageDTO[CustomerDTO]:
        return await paginate(self._session, select(Customer).order_by(Customer.name), params, _to_dto)
