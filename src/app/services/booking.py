from collections.abc import Callable
from datetime import UTC, date, datetime, tzinfo
from uuid import UUID

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.exceptions.domain import (
    EntityNotFoundError,
    IdempotencyKeyConsumedError,
    IdempotencyKeyReusedError,
    InvalidInputError,
    SlotCapacityExceededError,
    SlotInPastError,
    SlotUnavailableError,
)
from src.app.interfaces.repositories.booking_repository import BookingRepository, IdempotencyKeyTakenError


class BookingService:
    """Owns the rules for taking a booking.

    The rules live here rather than in the router so that any caller — HTTP,
    the seeding command, a future agent service — gets the same guarantees.
    """

    def __init__(
        self,
        bookings: BookingRepository,
        *,
        business_tz: tzinfo = UTC,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        # One dependency: a booking is a slot and a name. Resolving a CRM
        # account is a different flow's job, so this service never needs to
        # reach for one.
        self._bookings = bookings
        # Slots are stored as a bare date and time: the wall clock of the business,
        # not an instant. "Has it started" therefore compares against the current
        # time in the business's zone, which the clock is converted into here.
        self._business_tz = business_tz
        self._clock = clock

    def _local_now(self) -> datetime:
        return self._clock().astimezone(self._business_tz).replace(tzinfo=None)

    async def find_bookings(
        self,
        guest_name: str | None,
        slot_date: date | None,
        status: BookingStatus | None,
        params: PaginationParams,
    ) -> PageDTO[BookingDTO]:
        return await self._bookings.list_bookings(guest_name, slot_date, status, params)

    async def cancel_booking(self, booking_id: UUID) -> BookingDTO:
        """Cancel a reservation and put the slot back on offer.

        Idempotent: cancelling an already-cancelled booking returns it
        unchanged rather than failing. A dropped call retries, and the caller
        should not have to distinguish "I cancelled it" from "I cancelled it
        twice".
        """
        booking = await self._bookings.get_booking(booking_id)
        if booking is None:
            raise EntityNotFoundError(f"Booking '{booking_id}' was not found.")
        if booking.status is BookingStatus.CANCELLED:
            return booking

        cancelled = await self._bookings.mark_cancelled(booking_id)
        # Freeing the slot is the point of cancelling: it has to become
        # bookable again in the same transaction, or the table sits empty.
        await self._bookings.mark_slot_free(booking.slot_id)
        return cancelled

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]:
        return await self._bookings.list_available_slots(
            slot_date, resource_type, params, not_before=self._local_now()
        )

    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        name = guest_name.strip()
        if not name:
            raise InvalidInputError("A booking needs a guest name.")

        # Replay check comes first. A voice call that times out mid-request
        # retries; without this the retry hits "slot taken" and the caller
        # cannot tell its own successful booking from someone else's.
        if idempotency_key is not None:
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is not None:
                return replayed

        # Locking first is what makes the checks below trustworthy: a competing
        # request for the same slot blocks here and then sees is_available=False.
        slot = await self._bookings.lock_slot(slot_id)
        # A retry fired while the first request was still in flight passed the check above
        # (nothing was stored yet), then waited for the lock. The first request has committed
        # by now, so look again: the answer is its booking, not "slot taken".
        if idempotency_key is not None:
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is not None:
                return replayed
        if slot is None:
            raise EntityNotFoundError(f"Booking slot '{slot_id}' was not found.")
        if datetime.combine(slot.slot_date, slot.slot_time) <= self._local_now():
            raise SlotInPastError(f"Booking slot '{slot_id}' has already started.")
        if not slot.is_available:
            raise SlotUnavailableError(f"Booking slot '{slot_id}' is already taken.")
        if party_size > slot.capacity:
            raise SlotCapacityExceededError(
                f"Party of {party_size} exceeds the slot capacity of {slot.capacity}."
            )

        try:
            booking = await self._bookings.create_booking(name, slot_id, party_size, idempotency_key)
        except IdempotencyKeyTakenError:
            # The same key on a different slot, sent at the same moment: the other request
            # holds the key and this one waited on the unique index. Same answer as a retry.
            if idempotency_key is None:
                raise
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is None:
                raise
            return replayed
        await self._bookings.mark_slot_taken(slot_id)
        return booking

    async def _replay(self, idempotency_key: str, name: str, slot_id: UUID, party_size: int) -> BookingDTO | None:
        """The booking this key already made, if any; refuses a key that cannot be replayed."""
        replayed = await self._bookings.get_by_idempotency_key(idempotency_key)
        if replayed is None:
            return None
        if (replayed.guest_name, replayed.slot_id, replayed.party_size) != (name, slot_id, party_size):
            raise IdempotencyKeyReusedError()
        # Only an active booking may be replayed. Handing back a cancelled one would
        # answer "booked" with a reservation that no longer exists, leaving the slot
        # free and the caller believing they have a table.
        if replayed.status is BookingStatus.CANCELLED:
            raise IdempotencyKeyConsumedError()
        return replayed
