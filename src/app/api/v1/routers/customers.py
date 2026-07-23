from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import CustomerServiceDep, PaginationDep
from src.app.schemas.customer import CustomerResponse
from src.app.schemas.pagination import Page

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=Page[CustomerResponse])
async def search_customers(
    service: CustomerServiceDep,
    pagination: PaginationDep,
    search: Annotated[str | None, Query(max_length=200, description="Case-insensitive name fragment.")] = None,
) -> Page[CustomerResponse]:
    page = await service.search(search, pagination)
    return Page.from_contract(page, CustomerResponse.from_contract)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, service: CustomerServiceDep) -> CustomerResponse:
    return CustomerResponse.from_contract(await service.get(customer_id))
