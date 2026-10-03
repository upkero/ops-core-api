"""A slot that has started is neither listed nor bookable.

`slot_date`/`slot_time` are the business's wall clock, so "now" is the instant
converted into the business timezone. The clock is fixed at 12:00 UTC, which is
15:00 in Moscow, to make that conversion matter.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from src.app.contracts.pagination import PaginationParams
from src.app.exceptions.domain import SlotInPastError
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, make_slot

MOSCOW = ZoneInfo("Europe/Moscow")
TODAY = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)  # 15:00 in Moscow


def _service(bookings: FakeBookingRepository) -> BookingService:
    return BookingService(bookings, business_tz=MOSCOW, clock=lambda: NOW)


async def test_a_slot_earlier_today_is_not_listed_and_a_later_one_is() -> None:
    earlier = make_slot(slot_date=TODAY, slot_time=time(12, 0))
    later = make_slot(slot_date=TODAY, slot_time=time(19, 30))
    service = _service(FakeBookingRepository([earlier, later]))

    page = await service.list_available_slots(TODAY, None, PaginationParams(limit=10))

    assert [slot.id for slot in page.items] == [later.id]
    assert page.total == 1


async def test_the_listing_follows_the_business_timezone_not_utc() -> None:
    # 14:00 is still ahead of 12:00 UTC but already behind 15:00 Moscow time.
    slot = make_slot(slot_date=TODAY, slot_time=time(14, 0))
    service = _service(FakeBookingRepository([slot]))

    assert (await service.list_available_slots(TODAY, None, PaginationParams(limit=10))).items == []


async def test_yesterday_is_not_listed() -> None:
    slot = make_slot(slot_date=date(2026, 10, 3), slot_time=time(23, 0))
    service = _service(FakeBookingRepository([slot]))

    assert (await service.list_available_slots(None, None, PaginationParams(limit=10))).items == []


async def test_booking_a_started_slot_is_rejected_with_its_own_code() -> None:
    started = make_slot(slot_date=TODAY, slot_time=time(12, 0))
    bookings = FakeBookingRepository([started])

    with pytest.raises(SlotInPastError) as error:
        await _service(bookings).create_booking("Dmitri Volkov", started.id, party_size=2)

    assert (error.value.status_code, error.value.error_code) == (409, "slot_in_past")
    assert bookings.bookings == []
    assert bookings.slots[started.id].is_available is True


async def test_a_slot_starting_exactly_now_has_started() -> None:
    slot = make_slot(slot_date=TODAY, slot_time=time(15, 0))

    with pytest.raises(SlotInPastError):
        await _service(FakeBookingRepository([slot])).create_booking("Dmitri Volkov", slot.id, party_size=1)


async def test_a_slot_later_today_can_still_be_booked() -> None:
    slot = make_slot(slot_date=TODAY, slot_time=time(19, 30))

    booking = await _service(FakeBookingRepository([slot])).create_booking("Dmitri Volkov", slot.id, party_size=1)

    assert booking.slot_id == slot.id


async def test_replaying_a_booking_whose_slot_has_since_passed_still_returns_it() -> None:
    # The replay check comes first on purpose: a retry of a request that already
    # succeeded must get its booking back, however late the retry arrives.
    slot = make_slot(slot_date=TODAY, slot_time=time(19, 30))
    bookings = FakeBookingRepository([slot])
    booked = await _service(bookings).create_booking("Dmitri Volkov", slot.id, 1, idempotency_key="k1")
    later = BookingService(bookings, business_tz=MOSCOW, clock=lambda: datetime(2026, 10, 4, 18, 0, tzinfo=UTC))

    assert await later.create_booking("Dmitri Volkov", slot.id, 1, idempotency_key="k1") == booked
