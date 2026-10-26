"""The slot window rolls forward on every start without duplicating rows."""

from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.cli.seed import ensure_slots
from src.app.cli.seed_data import slot_template_for
from src.app.contracts.enums import ResourceType
from src.app.models.booking import BookingSlot

TODAY = date(2026, 10, 4)


def _expected(first_day: date, days: int) -> int:
    return sum(len(slot_template_for(first_day + timedelta(days=offset))) for offset in range(days))


async def _slot_dates(session: AsyncSession) -> list[date]:
    return list(await session.scalars(select(BookingSlot.slot_date).distinct().order_by(BookingSlot.slot_date)))


async def test_first_run_fills_tomorrow_through_the_window(session: AsyncSession) -> None:
    added = await ensure_slots(session, today=TODAY, days=14)

    assert added == _expected(TODAY + timedelta(days=1), 14)
    dates = await _slot_dates(session)
    assert dates[0] == TODAY + timedelta(days=1)
    assert dates[-1] == TODAY + timedelta(days=14)


async def test_running_again_adds_nothing(session: AsyncSession) -> None:
    await ensure_slots(session, today=TODAY, days=14)

    assert await ensure_slots(session, today=TODAY, days=14) == 0
    total = await session.scalar(select(func.count()).select_from(BookingSlot))
    assert total == _expected(TODAY + timedelta(days=1), 14)


async def test_the_window_moves_with_the_date_and_keeps_existing_rows(session: AsyncSession) -> None:
    await ensure_slots(session, today=TODAY, days=14)
    booked = await session.scalar(select(BookingSlot).limit(1))
    assert booked is not None
    booked.is_available = False
    await session.flush()

    added = await ensure_slots(session, today=TODAY + timedelta(days=3), days=14)

    assert added == _expected(TODAY + timedelta(days=15), 3)
    assert (await _slot_dates(session))[-1] == TODAY + timedelta(days=17)
    await session.refresh(booked)
    assert booked.is_available is False


async def test_a_year_of_slots_fits_in_the_bind_parameter_limit(session: AsyncSession) -> None:
    """A year is far past one statement's 32,767 parameters; batching must keep each under it."""
    added = await ensure_slots(session, today=TODAY, days=365)

    assert added == _expected(TODAY + timedelta(days=1), 365)
    assert await ensure_slots(session, today=TODAY, days=365) == 0


async def test_treatment_rooms_keep_the_clinics_opening_hours(session: AsyncSession) -> None:
    """The seeded "Opening hours" document: closed Sundays, Saturday 9-18, last start an hour before closing."""
    await ensure_slots(session, today=TODAY, days=14)

    rows = (
        await session.execute(
            select(BookingSlot.slot_date, BookingSlot.slot_time).where(
                BookingSlot.resource_type == ResourceType.TREATMENT_ROOM
            )
        )
    ).all()

    assert rows
    assert {day.weekday() for day, _ in rows} == {0, 1, 2, 3, 4, 5}  # no Sunday
    saturday_times = sorted({at for day, at in rows if day.weekday() == 5})
    assert saturday_times == [time(10), time(12, 30), time(15)]  # 17:30 starts after 17:00, the last start
    assert max(at for _, at in rows) == time(17, 30)  # weekdays still offer it
    assert {day for day, _ in rows if day.weekday() == 6} == set()
    # Everything else is offered every day, Sundays included.
    sunday = next(d for d in (TODAY + timedelta(days=n) for n in range(1, 8)) if d.weekday() == 6)
    assert await session.scalar(
        select(func.count()).select_from(BookingSlot).where(BookingSlot.slot_date == sunday)
    ) == len(slot_template_for(sunday))


def test_the_template_drops_only_treatment_rooms_on_sunday_and_late_saturday() -> None:
    saturday, sunday, monday = date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12)
    full = slot_template_for(monday)
    treatment = ResourceType.TREATMENT_ROOM

    assert [e for e in full if e[0] is treatment and (e[2], e[3]) == (17, 30)]
    assert {e for e in full if e[0] is not treatment} == {e for e in slot_template_for(sunday) if e[0] is not treatment}
    assert not [e for e in slot_template_for(sunday) if e[0] is treatment]
    assert [(e[2], e[3]) for e in slot_template_for(saturday) if e[0] is treatment] == [(10, 0), (12, 30), (15, 0)]
