from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import CustomerServiceDep
from src.app.schemas.customer import CustomerResponse

router = APIRouter(prefix="/customers", tags=["customers"])

MAX_SEARCH_RESULTS = 50


@router.get("", response_model=list[CustomerResponse])
async def search_customers(
    service: CustomerServiceDep,
    search: Annotated[str | None, Query(max_length=200, description="Case-insensitive name fragment.")] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_RESULTS)] = 20,
) -> list[CustomerResponse]:
    customers = await service.search(search, limit)
    return [CustomerResponse.from_contract(customer) for customer in customers]


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, service: CustomerServiceDep) -> CustomerResponse:
    return CustomerResponse.from_contract(await service.get(customer_id))
