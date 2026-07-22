from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from src.app.contracts.enums import ResourceType


@dataclass(frozen=True, slots=True)
class BookingSlotDTO:
    id: UUID
    resource_type: ResourceType
    slot_date: date
    slot_time: time
    capacity: int
    is_available: bool


@dataclass(frozen=True, slots=True)
class BookingDTO:
    id: UUID
    customer_id: UUID
    slot_id: UUID
    party_size: int
    created_at: datetime
