from abc import ABC, abstractmethod

from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.contracts.pricing import PricingItemDTO


class PricingRepository(ABC):
    @abstractmethod
    async def get_by_service_name(self, service_name: str) -> PricingItemDTO | None: ...

    @abstractmethod
    async def list_all(self, params: PaginationParams) -> PageDTO[PricingItemDTO]: ...
