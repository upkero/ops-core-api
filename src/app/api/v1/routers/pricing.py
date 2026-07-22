from typing import Annotated

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import PricingServiceDep
from src.app.schemas.pricing import PriceQuoteResponse, PricingItemResponse

router = APIRouter(prefix="/pricing", tags=["pricing"])

MAX_QUANTITY = 1000


@router.get("", response_model=PriceQuoteResponse)
async def quote_price(
    service_client: PricingServiceDep,
    service: Annotated[str, Query(min_length=1, max_length=200, description="Service name to price.")],
    quantity: Annotated[int, Query(ge=1, le=MAX_QUANTITY)] = 1,
) -> PriceQuoteResponse:
    # Discount rules are applied inside PricingService via its DiscountPolicy.
    return PriceQuoteResponse.from_contract(await service_client.quote(service, quantity))


@router.get("/services", response_model=list[PricingItemResponse])
async def list_services(service_client: PricingServiceDep) -> list[PricingItemResponse]:
    items = await service_client.list_services()
    return [PricingItemResponse.from_contract(item) for item in items]
