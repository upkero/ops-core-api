from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from src.app.api.v1.dependencies import BookingServiceDep
from src.app.contracts.enums import ResourceType
from src.app.schemas.booking import BookingSlotResponse

router = APIRouter(prefix="/booking-slots", tags=["bookings"])

MAX_SLOTS = 200


@router.get("", response_model=list[BookingSlotResponse])
async def list_available_slots(
    service: BookingServiceDep,
    slot_date: Annotated[date | None, Query(alias="date", description="Filter by calendar date.")] = None,
    resource_type: Annotated[ResourceType | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_SLOTS)] = 50,
) -> list[BookingSlotResponse]:
    slots = await service.list_available_slots(slot_date, resource_type, limit)
    return [BookingSlotResponse.from_contract(slot) for slot in slots]
