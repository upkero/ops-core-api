"""Cancelling a reservation and putting the table back on offer.

The point of a cancellation is the slot, not the row: if freeing it ever stops
working the restaurant loses a table for the evening and nothing complains.
"""

from uuid import uuid4

import pytest

from src.app.contracts.enums import BookingStatus
from src.app.contracts.pagination import PaginationParams
from src.app.exceptions.domain import EntityNotFoundError
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, make_slot

GUEST = "Dmitri Volkov"


@pytest.fixture
def slot():  # type: ignore[no-untyped-def]
    return make_slot(capacity=4)


@pytest.fixture
def bookings(slot) -> FakeBookingRepository:  # type: ignore[no-untyped-def]
    return FakeBookingRepository([slot])


@pytest.fixture
def service(bookings: FakeBookingRepository) -> BookingService:
    return BookingService(bookings)


async def test_cancelling_marks_the_booking_cancelled(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    booking = await service.create_booking(GUEST, slot.id, party_size=2)

    cancelled = await service.cancel_booking(booking.id)

    assert cancelled.status is BookingStatus.CANCELLED
    assert cancelled.cancelled_at is not None


async def test_cancelling_puts_the_slot_back_on_offer(  # type: ignore[no-untyped-def]
    service: BookingService,
    bookings: FakeBookingRepository,
    slot,
) -> None:
    booking = await service.create_booking(GUEST, slot.id, party_size=2)
    assert bookings.slots[slot.id].is_available is False

    await service.cancel_booking(booking.id)

    assert bookings.slots[slot.id].is_available is True


async def test_a_cancelled_slot_can_be_booked_again(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    first = await service.create_booking(GUEST, slot.id, party_size=2)
    await service.cancel_booking(first.id)

    second = await service.create_booking("Anna Petrova", slot.id, party_size=3)

    assert second.guest_name == "Anna Petrova"
    assert second.status is BookingStatus.ACTIVE


async def test_the_booking_row_survives_cancellation(  # type: ignore[no-untyped-def]
    service: BookingService,
    bookings: FakeBookingRepository,
    slot,
) -> None:
    # The cancellation is itself a fact: the published policy charges half
    # price inside 24 hours, which is unanswerable if the row is deleted.
    booking = await service.create_booking(GUEST, slot.id, party_size=2)

    await service.cancel_booking(booking.id)

    assert len(bookings.bookings) == 1


async def test_cancelling_twice_is_harmless(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    # A dropped call retries; the caller should not have to tell "cancelled"
    # from "cancelled twice".
    booking = await service.create_booking(GUEST, slot.id, party_size=2)

    first = await service.cancel_booking(booking.id)
    second = await service.cancel_booking(booking.id)

    assert first == second


async def test_cancelling_an_unknown_booking_is_a_404(service: BookingService) -> None:
    with pytest.raises(EntityNotFoundError) as error:
        await service.cancel_booking(uuid4())

    assert error.value.status_code == 404


async def test_find_bookings_defaults_to_the_active_ones(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    other = make_slot(capacity=2)
    service._bookings.slots[other.id] = other  # noqa: SLF001
    keep = await service.create_booking(GUEST, slot.id, party_size=2)
    drop = await service.create_booking(GUEST, other.id, party_size=2)
    await service.cancel_booking(drop.id)

    found = await service.find_bookings(None, None, BookingStatus.ACTIVE, PaginationParams())

    assert [booking.id for booking in found.items] == [keep.id]


async def test_find_bookings_matches_a_name_fragment(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    await service.create_booking("Dmitri Volkov", slot.id, party_size=2)

    found = await service.find_bookings("volkov", None, None, PaginationParams())

    assert len(found.items) == 1


async def test_find_bookings_can_include_cancelled_ones(service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
    booking = await service.create_booking(GUEST, slot.id, party_size=2)
    await service.cancel_booking(booking.id)

    assert (await service.find_bookings(None, None, None, PaginationParams())).total == 1
    assert (await service.find_bookings(None, None, BookingStatus.ACTIVE, PaginationParams())).total == 0
