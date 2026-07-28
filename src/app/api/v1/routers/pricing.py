from typing import Annotated

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import PaginationDep, PricingServiceDep
from src.app.schemas.pagination import Page
from src.app.schemas.pricing import PriceQuoteResponse, PricingItemResponse

router = APIRouter(prefix="/pricing", tags=["pricing"])

MAX_QUANTITY = 1000


@router.get("", response_model=PriceQuoteResponse)
async def quote_price(
    # Named for what it is, not for the name left over after avoiding a clash
    # with the `service` query parameter below.
    pricing_service: PricingServiceDep,
    service: Annotated[str, Query(min_length=1, max_length=200, description="Service name to price.")],
    quantity: Annotated[int, Query(ge=1, le=MAX_QUANTITY)] = 1,
) -> PriceQuoteResponse:
    # Discount rules are applied inside PricingService via its DiscountPolicy.
    return PriceQuoteResponse.from_contract(await pricing_service.quote(service, quantity))


@router.get("/services", response_model=Page[PricingItemResponse])
async def list_services(pricing_service: PricingServiceDep, pagination: PaginationDep) -> Page[PricingItemResponse]:
    page = await pricing_service.list_services(pagination)
    return Page.from_contract(page, PricingItemResponse.from_contract)
