from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import date
from uuid import UUID

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import ResourceType


class BookingRepository(ABC):
    """Slots and bookings share one port: they are written together in a single
    transaction, so splitting them would only invite half-applied changes."""

    @abstractmethod
    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        limit: int,
    ) -> Sequence[BookingSlotDTO]: ...

    @abstractmethod
    async def lock_slot(self, slot_id: UUID) -> BookingSlotDTO | None:
        """Read a slot with `SELECT ... FOR UPDATE`.

        The row lock is what makes the service's check-then-write sequence safe
        against two concurrent bookings for the same slot.
        """

    @abstractmethod
    async def create_booking(self, customer_id: UUID, slot_id: UUID, party_size: int) -> BookingDTO: ...

    @abstractmethod
    async def mark_slot_taken(self, slot_id: UUID) -> None: ...
