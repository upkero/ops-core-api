from abc import ABC, abstractmethod
from datetime import date
from uuid import UUID

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams


class BookingRepository(ABC):
    """Slots and bookings share one port: they are written together in a single
    transaction, so splitting them would only invite half-applied changes."""

    @abstractmethod
    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]: ...

    @abstractmethod
    async def lock_slot(self, slot_id: UUID) -> BookingSlotDTO | None:
        """Read a slot with `SELECT ... FOR UPDATE`.

        The row lock is what makes the service's check-then-write sequence safe
        against two concurrent bookings for the same slot.
        """

    @abstractmethod
    async def get_by_idempotency_key(self, idempotency_key: str) -> BookingDTO | None:
        """Find a booking already made under this retry token, if any."""

    @abstractmethod
    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO: ...

    @abstractmethod
    async def mark_slot_taken(self, slot_id: UUID) -> None: ...

    @abstractmethod
    async def mark_slot_free(self, slot_id: UUID) -> None:
        """Return a slot to the pool after its booking is cancelled."""

    @abstractmethod
    async def get_booking(self, booking_id: UUID) -> BookingDTO | None: ...

    @abstractmethod
    async def list_bookings(
        self,
        guest_name: str | None,
        slot_date: date | None,
        status: BookingStatus | None,
        params: PaginationParams,
    ) -> PageDTO[BookingDTO]:
        """Find bookings, ordered by when the slot is. Ordered by slot, not by
        creation, because a caller asking about "my table on Friday" is
        thinking in calendar order."""

    @abstractmethod
    async def mark_cancelled(self, booking_id: UUID) -> BookingDTO: ...
