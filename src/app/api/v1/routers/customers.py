from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from src.app.api.v1.dependencies import CustomerServiceDep, PaginationDep
from src.app.schemas.customer import CustomerCreateRequest, CustomerResponse
from src.app.schemas.pagination import Page

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(body: CustomerCreateRequest, service: CustomerServiceDep) -> CustomerResponse:
    customer = await service.create(body.name, body.status, body.notes)
    return CustomerResponse.model_validate(customer)


@router.get("", response_model=Page[CustomerResponse])
async def search_customers(
    service: CustomerServiceDep,
    pagination: PaginationDep,
    search: Annotated[str | None, Query(max_length=200, description="Case-insensitive name fragment.")] = None,
) -> Page[CustomerResponse]:
    page = await service.search(search, pagination)
    return Page[CustomerResponse].model_validate(page)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, service: CustomerServiceDep) -> CustomerResponse:
    return CustomerResponse.model_validate(await service.get(customer_id))
