from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import BookingServiceDep, PaginationDep
from src.app.contracts.enums import ResourceType
from src.app.schemas.booking import BookingSlotResponse
from src.app.schemas.pagination import Page

router = APIRouter(prefix="/booking-slots", tags=["bookings"])


@router.get("", response_model=Page[BookingSlotResponse])
async def list_available_slots(
    service: BookingServiceDep,
    pagination: PaginationDep,
    slot_date: Annotated[date | None, Query(alias="date", description="Filter by calendar date.")] = None,
    resource_type: Annotated[ResourceType | None, Query()] = None,
) -> Page[BookingSlotResponse]:
    page = await service.list_available_slots(slot_date, resource_type, pagination)
    return Page.from_contract(page, BookingSlotResponse.from_contract)
