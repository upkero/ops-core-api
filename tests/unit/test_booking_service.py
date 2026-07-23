from uuid import uuid4

import pytest

from src.app.contracts.pagination import PaginationParams
from src.app.exceptions.domain import (
    EntityNotFoundError,
    InvalidInputError,
    SlotCapacityExceededError,
    SlotUnavailableError,
)
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, make_slot

GUEST = "Dmitri Volkov"


@pytest.fixture
def slot():  # type: ignore[no-untyped-def]
    return make_slot(capacity=4)


async def test_create_booking_reserves_the_slot(slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings)

    booking = await service.create_booking(GUEST, slot.id, party_size=3)

    assert booking.guest_name == GUEST
    assert booking.party_size == 3
    # The slot must be marked taken in the same call, or the next request would
    # be allowed to book it too.
    assert bookings.slots[slot.id].is_available is False


async def test_a_booking_needs_no_customer_account(slot) -> None:  # type: ignore[no-untyped-def]
    # The whole point of the split: a phone reservation is a slot and a name,
    # so this service has no customer repository to consult at all.
    service = BookingService(FakeBookingRepository([slot]))

    assert (await service.create_booking(GUEST, slot.id, party_size=1)).guest_name == GUEST


async def test_the_guest_name_is_trimmed(slot) -> None:  # type: ignore[no-untyped-def]
    service = BookingService(FakeBookingRepository([slot]))

    booking = await service.create_booking("  Anna Petrova  ", slot.id, party_size=1)

    assert booking.guest_name == "Anna Petrova"


@pytest.mark.parametrize("name", ["", "   "])
async def test_a_blank_guest_name_is_rejected(slot, name: str) -> None:  # type: ignore[no-untyped-def]
    service = BookingService(FakeBookingRepository([slot]))

    with pytest.raises(InvalidInputError) as error:
        await service.create_booking(name, slot.id, party_size=1)

    # 422, not a bare ValueError that would surface as a 500.
    assert error.value.status_code == 422


async def test_create_booking_locks_the_slot_before_checking_it(slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])

    await BookingService(bookings).create_booking(GUEST, slot.id, party_size=1)

    assert bookings.locked == [slot.id]


async def test_create_booking_rejects_an_unknown_slot() -> None:
    service = BookingService(FakeBookingRepository([]))

    with pytest.raises(EntityNotFoundError):
        await service.create_booking(GUEST, uuid4(), party_size=1)


async def test_create_booking_rejects_a_slot_that_is_taken() -> None:
    taken = make_slot(is_available=False)
    bookings = FakeBookingRepository([taken])

    with pytest.raises(SlotUnavailableError) as error:
        await BookingService(bookings).create_booking(GUEST, taken.id, party_size=1)

    assert error.value.status_code == 409
    assert bookings.bookings == []


async def test_create_booking_rejects_a_party_larger_than_the_slot(slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])

    with pytest.raises(SlotCapacityExceededError):
        await BookingService(bookings).create_booking(GUEST, slot.id, party_size=5)

    assert bookings.bookings == []
    assert bookings.slots[slot.id].is_available is True


async def test_a_party_exactly_at_capacity_is_accepted(slot) -> None:  # type: ignore[no-untyped-def]
    service = BookingService(FakeBookingRepository([slot]))

    assert (await service.create_booking(GUEST, slot.id, party_size=4)).party_size == 4


async def test_booking_a_slot_twice_fails_the_second_time(slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings)

    await service.create_booking(GUEST, slot.id, party_size=2)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking("Someone Else", slot.id, party_size=2)

    assert len(bookings.bookings) == 1


async def test_list_available_slots_hides_taken_ones() -> None:
    free, taken = make_slot(), make_slot(is_available=False)
    service = BookingService(FakeBookingRepository([free, taken]))

    available = await service.list_available_slots(None, None, PaginationParams(limit=10))

    assert [slot.id for slot in available.items] == [free.id]
