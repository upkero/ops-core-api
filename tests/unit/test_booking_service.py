from uuid import uuid4

import pytest

from src.app.exceptions.domain import EntityNotFoundError, SlotCapacityExceededError, SlotUnavailableError
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, FakeCustomerRepository, make_customer, make_slot


@pytest.fixture
def customer():  # type: ignore[no-untyped-def]
    return make_customer()


@pytest.fixture
def slot():  # type: ignore[no-untyped-def]
    return make_slot(capacity=4)


async def test_create_booking_reserves_the_slot(customer, slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings, FakeCustomerRepository([customer]))

    booking = await service.create_booking(customer.id, slot.id, party_size=3)

    assert booking.customer_id == customer.id
    assert booking.party_size == 3
    # The slot must be marked taken in the same call, or the next request would
    # be allowed to book it too.
    assert bookings.slots[slot.id].is_available is False


async def test_create_booking_locks_the_slot_before_checking_it(customer, slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings, FakeCustomerRepository([customer]))

    await service.create_booking(customer.id, slot.id, party_size=1)

    assert bookings.locked == [slot.id]


async def test_create_booking_rejects_an_unknown_customer(slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings, FakeCustomerRepository([]))

    with pytest.raises(EntityNotFoundError):
        await service.create_booking(uuid4(), slot.id, party_size=1)

    assert bookings.bookings == []


async def test_create_booking_rejects_an_unknown_slot(customer) -> None:  # type: ignore[no-untyped-def]
    service = BookingService(FakeBookingRepository([]), FakeCustomerRepository([customer]))

    with pytest.raises(EntityNotFoundError):
        await service.create_booking(customer.id, uuid4(), party_size=1)


async def test_create_booking_rejects_a_slot_that_is_taken(customer) -> None:  # type: ignore[no-untyped-def]
    taken = make_slot(is_available=False)
    bookings = FakeBookingRepository([taken])
    service = BookingService(bookings, FakeCustomerRepository([customer]))

    with pytest.raises(SlotUnavailableError) as error:
        await service.create_booking(customer.id, taken.id, party_size=1)

    assert error.value.status_code == 409
    assert bookings.bookings == []


async def test_create_booking_rejects_a_party_larger_than_the_slot(customer, slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings, FakeCustomerRepository([customer]))

    with pytest.raises(SlotCapacityExceededError):
        await service.create_booking(customer.id, slot.id, party_size=5)

    assert bookings.bookings == []
    assert bookings.slots[slot.id].is_available is True


async def test_a_party_exactly_at_capacity_is_accepted(customer, slot) -> None:  # type: ignore[no-untyped-def]
    service = BookingService(FakeBookingRepository([slot]), FakeCustomerRepository([customer]))

    booking = await service.create_booking(customer.id, slot.id, party_size=4)

    assert booking.party_size == 4


async def test_booking_a_slot_twice_fails_the_second_time(customer, slot) -> None:  # type: ignore[no-untyped-def]
    bookings = FakeBookingRepository([slot])
    service = BookingService(bookings, FakeCustomerRepository([customer]))

    await service.create_booking(customer.id, slot.id, party_size=2)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(customer.id, slot.id, party_size=2)

    assert len(bookings.bookings) == 1


async def test_list_available_slots_hides_taken_ones(customer) -> None:  # type: ignore[no-untyped-def]
    free, taken = make_slot(), make_slot(is_available=False)
    service = BookingService(FakeBookingRepository([free, taken]), FakeCustomerRepository([customer]))

    available = await service.list_available_slots(None, None, limit=10)

    assert [slot.id for slot in available] == [free.id]
