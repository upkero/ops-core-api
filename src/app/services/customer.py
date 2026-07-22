from collections.abc import Sequence
from uuid import UUID

from src.app.contracts.customer import CustomerDTO
from src.app.exceptions.domain import EntityNotFoundError
from src.app.interfaces.repositories.customer_repository import CustomerRepository


class CustomerService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    async def get(self, customer_id: UUID) -> CustomerDTO:
        customer = await self._repository.get_by_id(customer_id)
        if customer is None:
            raise EntityNotFoundError(f"Customer '{customer_id}' was not found.")
        return customer

    async def search(self, query: str | None, limit: int) -> Sequence[CustomerDTO]:
        if query is None or not query.strip():
            return await self._repository.list_all(limit)
        return await self._repository.search_by_name(query.strip(), limit)
