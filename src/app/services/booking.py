from datetime import date
from uuid import UUID

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.exceptions.domain import (
    EntityNotFoundError,
    IdempotencyKeyReusedError,
    SlotCapacityExceededError,
    SlotUnavailableError,
)
from src.app.interfaces.repositories.booking_repository import BookingRepository
from src.app.interfaces.repositories.customer_repository import CustomerRepository


class BookingService:
    """Owns the rules for taking a booking.

    The rules live here rather than in the router so that any caller — HTTP,
    the seeding command, a future agent service — gets the same guarantees.
    """

    def __init__(self, bookings: BookingRepository, customers: CustomerRepository) -> None:
        self._bookings = bookings
        self._customers = customers

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]:
        return await self._bookings.list_available_slots(slot_date, resource_type, params)

    async def create_booking(
        self,
        customer_id: UUID,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        # Replay check comes first. A voice call that times out mid-request
        # retries; without this the retry hits "slot taken" and the caller
        # cannot tell its own successful booking from someone else's.
        if idempotency_key is not None:
            replayed = await self._bookings.get_by_idempotency_key(idempotency_key)
            if replayed is not None:
                if (replayed.customer_id, replayed.slot_id, replayed.party_size) != (
                    customer_id,
                    slot_id,
                    party_size,
                ):
                    raise IdempotencyKeyReusedError()
                return replayed

        if await self._customers.get_by_id(customer_id) is None:
            raise EntityNotFoundError(f"Customer '{customer_id}' was not found.")

        # Locking first is what makes the checks below trustworthy: a competing
        # request for the same slot blocks here and then sees is_available=False.
        slot = await self._bookings.lock_slot(slot_id)
        if slot is None:
            raise EntityNotFoundError(f"Booking slot '{slot_id}' was not found.")
        if not slot.is_available:
            raise SlotUnavailableError(f"Booking slot '{slot_id}' is already taken.")
        if party_size > slot.capacity:
            raise SlotCapacityExceededError(
                f"Party of {party_size} exceeds the slot capacity of {slot.capacity}."
            )

        booking = await self._bookings.create_booking(customer_id, slot_id, party_size, idempotency_key)
        await self._bookings.mark_slot_taken(slot_id)
        return booking
