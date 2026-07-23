from uuid import UUID

from src.app.contracts.customer import CustomerDTO
from src.app.contracts.enums import CustomerStatus
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.exceptions.domain import EntityNotFoundError, InvalidInputError
from src.app.interfaces.repositories.customer_repository import CustomerRepository


class CustomerService:
    def __init__(self, repository: CustomerRepository) -> None:
        self._repository = repository

    async def get(self, customer_id: UUID) -> CustomerDTO:
        customer = await self._repository.get_by_id(customer_id)
        if customer is None:
            raise EntityNotFoundError(f"Customer '{customer_id}' was not found.")
        return customer

    async def create(
        self,
        name: str,
        status: CustomerStatus = CustomerStatus.LEAD,
        notes: str | None = None,
    ) -> CustomerDTO:
        """Register a caller who is not in the system yet.

        Deliberately does not deduplicate: names are not unique in reality, and
        guessing that two "Anna Petrova" rows are the same person would silently
        merge strangers. A caller that wants to avoid duplicates searches first.
        """
        cleaned = name.strip()
        if not cleaned:
            raise InvalidInputError("Customer name must not be blank.")
        return await self._repository.create(cleaned, status, notes)

    async def search(self, query: str | None, params: PaginationParams) -> PageDTO[CustomerDTO]:
        if query is None or not query.strip():
            return await self._repository.list_all(params)
        return await self._repository.search_by_name(query.strip(), params)
