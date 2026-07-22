from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from src.app.contracts.customer import CustomerDTO


class CustomerRepository(ABC):
    """Repository pattern: services reach customer data through this port only.

    Returns contracts, never ORM models, so nothing above this layer can
    accidentally depend on SQLAlchemy or trigger lazy loading.
    """

    @abstractmethod
    async def get_by_id(self, customer_id: UUID) -> CustomerDTO | None: ...

    @abstractmethod
    async def search_by_name(self, query: str, limit: int) -> Sequence[CustomerDTO]: ...

    @abstractmethod
    async def list_all(self, limit: int) -> Sequence[CustomerDTO]: ...
