"""The slot window rolls forward on every start without duplicating rows."""

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.cli.seed import ensure_slots
from src.app.cli.seed_data import SLOT_TEMPLATE
from src.app.models.booking import BookingSlot

TODAY = date(2026, 10, 4)


async def _slot_dates(session: AsyncSession) -> list[date]:
    return list(await session.scalars(select(BookingSlot.slot_date).distinct().order_by(BookingSlot.slot_date)))


async def test_first_run_fills_tomorrow_through_the_window(session: AsyncSession) -> None:
    added = await ensure_slots(session, today=TODAY, days=14)

    assert added == 14 * len(SLOT_TEMPLATE)
    dates = await _slot_dates(session)
    assert dates[0] == TODAY + timedelta(days=1)
    assert dates[-1] == TODAY + timedelta(days=14)


async def test_running_again_adds_nothing(session: AsyncSession) -> None:
    await ensure_slots(session, today=TODAY, days=14)

    assert await ensure_slots(session, today=TODAY, days=14) == 0
    assert await session.scalar(select(func.count()).select_from(BookingSlot)) == 14 * len(SLOT_TEMPLATE)


async def test_the_window_moves_with_the_date_and_keeps_existing_rows(session: AsyncSession) -> None:
    await ensure_slots(session, today=TODAY, days=14)
    booked = await session.scalar(select(BookingSlot).limit(1))
    assert booked is not None
    booked.is_available = False
    await session.flush()

    added = await ensure_slots(session, today=TODAY + timedelta(days=3), days=14)

    assert added == 3 * len(SLOT_TEMPLATE)
    assert (await _slot_dates(session))[-1] == TODAY + timedelta(days=17)
    await session.refresh(booked)
    assert booked.is_available is False
