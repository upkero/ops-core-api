"""Concurrent retries with one Idempotency-Key, against a real Postgres.

The first request is held open (inserted, not committed) while the second one
runs, which is the interleaving a voice agent's retry produces.
"""

import asyncio
from datetime import time
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.app.contracts.booking import BookingDTO
from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.exceptions.domain import IdempotencyKeyReusedError
from src.app.models.booking import BookingSlot
from src.app.repositories.booking import SqlAlchemyBookingRepository
from src.app.services.booking import BookingService
from tests.fakes import FUTURE_DAY

GUEST = "Dmitri Volkov"
KEY = "retry-1"


async def _make_slots(factory: async_sessionmaker[AsyncSession], count: int) -> list[UUID]:
    async with factory() as session, session.begin():
        slots = [
            BookingSlot(resource_type=ResourceType.TABLE, slot_date=FUTURE_DAY, slot_time=time(18, index), capacity=4)
            for index in range(count)
        ]
        session.add_all(slots)
        await session.flush()
        return [slot.id for slot in slots]


async def _wait_until_a_backend_waits_for_a_lock(factory: async_sessionmaker[AsyncSession]) -> None:
    """Block until some other transaction is parked on a lock, i.e. the interleaving is real.

    A fixed sleep proves nothing: connecting can take longer than it.
    """
    for _ in range(100):
        async with factory() as probe:
            waiting = await probe.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND datname = current_database()"
                )
            )
        if waiting:
            return
        await asyncio.sleep(0.05)
    raise AssertionError("the second request never started waiting for the first")


async def _book(factory: async_sessionmaker[AsyncSession], slot_id: UUID) -> BookingDTO:
    async with factory() as session, session.begin():
        return await BookingService(SqlAlchemyBookingRepository(session)).create_booking(
            GUEST, slot_id, 2, idempotency_key=KEY
        )


async def test_a_retry_waiting_on_the_slot_lock_gets_the_first_booking(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    (slot_id,) = await _make_slots(session_factory, 1)

    async with session_factory() as first:
        await first.begin()
        original = await BookingService(SqlAlchemyBookingRepository(first)).create_booking(
            GUEST, slot_id, 2, idempotency_key=KEY
        )
        retry = asyncio.create_task(_book(session_factory, slot_id))
        await _wait_until_a_backend_waits_for_a_lock(session_factory)  # on the slot row lock
        assert not retry.done()
        await first.commit()

    replayed = await asyncio.wait_for(retry, timeout=5)

    assert replayed.id == original.id
    assert replayed.status is BookingStatus.ACTIVE


async def test_the_same_key_on_another_slot_is_refused_cleanly_not_with_a_500(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first_slot, second_slot = await _make_slots(session_factory, 2)

    async with session_factory() as first:
        await first.begin()
        await BookingService(SqlAlchemyBookingRepository(first)).create_booking(
            GUEST, first_slot, 2, idempotency_key=KEY
        )
        other = asyncio.create_task(_book(session_factory, second_slot))
        await _wait_until_a_backend_waits_for_a_lock(session_factory)  # on the key's unique index
        assert not other.done()
        await first.commit()

    with pytest.raises(IdempotencyKeyReusedError):
        await asyncio.wait_for(other, timeout=5)
