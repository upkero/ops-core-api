from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.contracts.pricing import PricingItemDTO
from src.app.interfaces.repositories.pricing_repository import PricingRepository
from src.app.models.pricing import PricingItem
from src.app.repositories.pagination import paginate


def _to_dto(row: PricingItem) -> PricingItemDTO:
    return PricingItemDTO(
        id=row.id,
        service_name=row.service_name,
        unit_price=row.unit_price,
        description=row.description,
    )


class SqlAlchemyPricingRepository(PricingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_service_name(self, service_name: str) -> PricingItemDTO | None:
        stmt = select(PricingItem).where(PricingItem.service_name.ilike(service_name))
        row = await self._session.scalar(stmt)
        return _to_dto(row) if row is not None else None

    async def list_all(self, params: PaginationParams) -> PageDTO[PricingItemDTO]:
        stmt = select(PricingItem).order_by(PricingItem.service_name)
        return await paginate(self._session, stmt, params, _to_dto)
