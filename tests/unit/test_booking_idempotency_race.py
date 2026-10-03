"""Two requests carrying one Idempotency-Key at the same moment.

The fakes replay the interleaving: the competing request commits while this one
is waiting (for the slot lock, or on the unique index of the key).
"""

from uuid import UUID

import pytest

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.exceptions.domain import IdempotencyKeyReusedError
from src.app.interfaces.repositories.booking_repository import IdempotencyKeyTakenError
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, make_slot

GUEST = "Dmitri Volkov"
KEY = "retry-1"


class WinnerLandsWhileWeWaitForTheLock(FakeBookingRepository):
    async def lock_slot(self, slot_id: UUID) -> BookingSlotDTO | None:
        if not self.bookings:
            await super().create_booking(GUEST, slot_id, 2, KEY)
            await self.mark_slot_taken(slot_id)
        return await super().lock_slot(slot_id)


class WinnerLandsWhileWeWaitForTheKey(FakeBookingRepository):
    def __init__(self, winner_slot: BookingSlotDTO, *others: BookingSlotDTO) -> None:
        super().__init__([winner_slot, *others])
        self.winner_slot = winner_slot

    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        await super().create_booking(GUEST, self.winner_slot.id, 2, KEY)
        raise IdempotencyKeyTakenError(KEY)


async def test_a_retry_that_waited_for_the_lock_gets_the_first_booking() -> None:
    slot = make_slot()
    bookings = WinnerLandsWhileWeWaitForTheLock([slot])

    booking = await BookingService(bookings).create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    assert booking is bookings.bookings[0]
    assert len(bookings.bookings) == 1


async def test_the_same_key_on_another_slot_is_reported_as_reuse_not_a_crash() -> None:
    winner, mine = make_slot(), make_slot()
    bookings = WinnerLandsWhileWeWaitForTheKey(winner, mine)

    with pytest.raises(IdempotencyKeyReusedError):
        await BookingService(bookings).create_booking(GUEST, mine.id, 2, idempotency_key=KEY)

    assert bookings.slots[mine.id].is_available is True


async def test_the_same_key_with_the_same_details_replays_the_winner_when_the_insert_is_refused() -> None:
    winner = make_slot()
    bookings = WinnerLandsWhileWeWaitForTheKey(winner)

    booking = await BookingService(bookings).create_booking(GUEST, winner.id, 2, idempotency_key=KEY)

    assert booking is bookings.bookings[0]
