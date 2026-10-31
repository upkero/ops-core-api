from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.schemas.base import ResponseModel


class BookingSlotResponse(ResponseModel):
    id: UUID
    resource_type: ResourceType
    slot_date: date
    slot_time: time
    capacity: int
    is_available: bool



class BookingCreateRequest(BaseModel):
    guest_name: str = Field(..., min_length=1, max_length=200, description="Name the table is reserved under.")
    slot_id: UUID
    party_size: int = Field(..., ge=1, le=100)

    @field_validator("guest_name")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("guest_name must not be blank")
        return cleaned


class BookingResponse(ResponseModel):
    id: UUID
    guest_name: str
    slot_id: UUID
    party_size: int
    created_at: datetime
    status: BookingStatus
    cancelled_at: datetime | None = None
