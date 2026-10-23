"""The engine the application builds: bounded statements, and a timed slot lock."""

from datetime import time

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.enums import ResourceType
from src.app.db.session import build_engine
from src.app.models.booking import BookingSlot
from src.app.repositories.booking import SqlAlchemyBookingRepository
from tests import telemetry
from tests.conftest import TEST_DB_URL
from tests.fakes import FUTURE_DAY


@pytest.mark.usefixtures("session_factory")
async def test_the_engine_bounds_a_statement_and_a_lock_wait() -> None:
    assert TEST_DB_URL is not None  # session_factory skipped the test otherwise
    engine = build_engine(TEST_DB_URL)
    try:
        async with engine.connect() as connection:
            statement = await connection.scalar(text("SHOW statement_timeout"))
            lock = await connection.scalar(text("SHOW lock_timeout"))
    finally:
        await engine.dispose()

    assert (statement, lock) == ("5s", "3s")


async def test_locking_a_slot_records_how_long_the_lock_took(session: AsyncSession) -> None:
    slot = BookingSlot(resource_type=ResourceType.TABLE, slot_date=FUTURE_DAY, slot_time=time(18, 0), capacity=4)
    session.add(slot)
    await session.flush()
    before = telemetry.reading("ops.slot_lock.wait")

    assert await SqlAlchemyBookingRepository(session).lock_slot(slot.id) is not None

    assert telemetry.reading("ops.slot_lock.wait") == before + 1
