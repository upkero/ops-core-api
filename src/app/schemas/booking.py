from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field

from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.schemas.base import NonBlankName, ResponseModel


class BookingSlotResponse(ResponseModel):
    id: UUID
    resource_type: ResourceType
    slot_date: date
    slot_time: time
    capacity: int
    is_available: bool



class BookingCreateRequest(BaseModel):
    guest_name: NonBlankName = Field(..., description="Name the table is reserved under.")
    slot_id: UUID
    party_size: int = Field(..., ge=1, le=100)


class BookingResponse(ResponseModel):
    id: UUID
    guest_name: str
    slot_id: UUID
    party_size: int
    created_at: datetime
    status: BookingStatus
    cancelled_at: datetime | None = None
