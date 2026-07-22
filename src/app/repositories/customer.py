from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.customer import CustomerDTO
from src.app.interfaces.repositories.customer_repository import CustomerRepository
from src.app.models.customer import Customer


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

    async def search_by_name(self, query: str, limit: int) -> Sequence[CustomerDTO]:
        # ILIKE with an escaped pattern: a customer named "50% off" must not
        # turn into a wildcard search.
        pattern = f"%{query.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
        stmt = (
            select(Customer)
            .where(Customer.name.ilike(pattern, escape="!"))
            .order_by(Customer.name)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return [_to_dto(row) for row in result]

    async def list_all(self, limit: int) -> Sequence[CustomerDTO]:
        result = await self._session.scalars(select(Customer).order_by(Customer.name).limit(limit))
        return [_to_dto(row) for row in result]
