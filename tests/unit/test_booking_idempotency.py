"""Retrying a booking must not depend on guessing what happened the first time.

A voice call drops mid-request often enough that this is the normal path, not
an edge case: the agent has to retry, and without a retry token the retry looks
exactly like someone else having taken the slot.
"""

import pytest

from src.app.contracts.enums import BookingStatus
from src.app.exceptions.domain import (
    IdempotencyKeyConsumedError,
    IdempotencyKeyReusedError,
    SlotUnavailableError,
)
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, make_slot

KEY = "call-42-booking-attempt-1"
GUEST = "Dmitri Volkov"


@pytest.fixture
def slot():  # type: ignore[no-untyped-def]
    return make_slot(capacity=4)


@pytest.fixture
def service(slot) -> BookingService:  # type: ignore[no-untyped-def]
    return BookingService(FakeBookingRepository([slot]))


async def test_retrying_with_the_same_key_returns_the_original_booking(service, slot) -> None:  # type: ignore[no-untyped-def]
    first = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)
    retry = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    assert retry == first


async def test_a_retry_does_not_create_a_second_booking(service, slot) -> None:  # type: ignore[no-untyped-def]
    await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)
    await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    assert len(service._bookings.bookings) == 1  # noqa: SLF001


async def test_without_a_key_a_repeat_is_still_a_conflict(service, slot) -> None:  # type: ignore[no-untyped-def]
    # The old behaviour is unchanged for callers that do not opt in.
    await service.create_booking(GUEST, slot.id, 2)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(GUEST, slot.id, 2)


async def test_a_different_caller_still_gets_a_conflict(service, slot) -> None:  # type: ignore[no-untyped-def]
    # This is the case the key has to stay distinguishable from: someone else
    # genuinely took the slot.
    await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(GUEST, slot.id, 2, idempotency_key="another-call")


@pytest.mark.parametrize(
    ("field", "value"),
    [("party_size", 3), ("slot_id", "other"), ("guest_name", "Someone Else")],
)
async def test_reusing_a_key_with_different_parameters_is_rejected(  # type: ignore[no-untyped-def]
    service,
    slot,
    field: str,
    value: object,
) -> None:
    other_slot = make_slot(capacity=4)
    service._bookings.slots[other_slot.id] = other_slot  # noqa: SLF001
    await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    args: dict[str, object] = {"guest_name": GUEST, "slot_id": slot.id, "party_size": 2}
    args[field] = other_slot.id if value == "other" else value

    # Returning the stored booking here would answer a question nobody asked.
    with pytest.raises(IdempotencyKeyReusedError) as error:
        await service.create_booking(idempotency_key=KEY, **args)  # type: ignore[arg-type]

    assert error.value.status_code == 409


async def test_the_replay_check_runs_before_any_other_validation(service, slot) -> None:  # type: ignore[no-untyped-def]
    # Once the slot is taken, the replay must still succeed — otherwise the
    # retry would fail on the very availability check it is meant to bypass.
    first = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

    assert service._bookings.slots[slot.id].is_available is False  # noqa: SLF001
    assert await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY) == first


class TestKeyAfterCancellation:
    """book → cancel → book within one call.

    The dangerous version of this is silent: replaying the key returns the
    cancelled booking with a success code, so the caller is told the table is
    reserved while the slot sits free and no booking exists.
    """

    async def test_replaying_a_cancelled_booking_is_refused(self, service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
        booking = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)
        await service.cancel_booking(booking.id)

        with pytest.raises(IdempotencyKeyConsumedError) as error:
            await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

        assert error.value.status_code == 409

    async def test_a_fresh_key_books_the_freed_slot(self, service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
        first = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)
        await service.cancel_booking(first.id)

        second = await service.create_booking(GUEST, slot.id, 2, idempotency_key="call-42-attempt-2")

        assert second.id != first.id
        assert second.status is BookingStatus.ACTIVE
        assert service._bookings.slots[slot.id].is_available is False  # noqa: SLF001

    async def test_the_refusal_leaves_the_slot_bookable(self, service: BookingService, slot) -> None:  # type: ignore[no-untyped-def]
        # The 409 must not consume the slot as a side effect.
        booking = await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)
        await service.cancel_booking(booking.id)

        with pytest.raises(IdempotencyKeyConsumedError):
            await service.create_booking(GUEST, slot.id, 2, idempotency_key=KEY)

        assert service._bookings.slots[slot.id].is_available is True  # noqa: SLF001
