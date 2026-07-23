from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import ResourceType


class BookingSlotResponse(BaseModel):
    id: UUID
    resource_type: ResourceType
    slot_date: date
    slot_time: time
    capacity: int
    is_available: bool

    @classmethod
    def from_contract(cls, slot: BookingSlotDTO) -> "BookingSlotResponse":
        return cls(
            id=slot.id,
            resource_type=slot.resource_type,
            slot_date=slot.slot_date,
            slot_time=slot.slot_time,
            capacity=slot.capacity,
            is_available=slot.is_available,
        )


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


class BookingResponse(BaseModel):
    id: UUID
    guest_name: str
    slot_id: UUID
    party_size: int
    created_at: datetime

    @classmethod
    def from_contract(cls, booking: BookingDTO) -> "BookingResponse":
        return cls(
            id=booking.id,
            guest_name=booking.guest_name,
            slot_id=booking.slot_id,
            party_size=booking.party_size,
            created_at=booking.created_at,
        )
