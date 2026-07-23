"""Retrying a booking must not depend on guessing what happened the first time.

A voice call drops mid-request often enough that this is the normal path, not
an edge case: the agent has to retry, and without a retry token the retry looks
exactly like someone else having taken the slot.
"""

import pytest

from src.app.exceptions.domain import IdempotencyKeyReusedError, SlotUnavailableError
from src.app.services.booking import BookingService
from tests.fakes import FakeBookingRepository, FakeCustomerRepository, make_customer, make_slot

KEY = "call-42-booking-attempt-1"


@pytest.fixture
def customer():  # type: ignore[no-untyped-def]
    return make_customer()


@pytest.fixture
def slot():  # type: ignore[no-untyped-def]
    return make_slot(capacity=4)


@pytest.fixture
def service(customer, slot) -> BookingService:  # type: ignore[no-untyped-def]
    return BookingService(FakeBookingRepository([slot]), FakeCustomerRepository([customer]))


async def test_retrying_with_the_same_key_returns_the_original_booking(service, customer, slot) -> None:  # type: ignore[no-untyped-def]
    first = await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)
    retry = await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)

    assert retry == first


async def test_a_retry_does_not_create_a_second_booking(service, customer, slot) -> None:  # type: ignore[no-untyped-def]
    await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)
    await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)

    assert len(service._bookings.bookings) == 1  # noqa: SLF001


async def test_without_a_key_a_repeat_is_still_a_conflict(service, customer, slot) -> None:  # type: ignore[no-untyped-def]
    # The old behaviour is unchanged for callers that do not opt in.
    await service.create_booking(customer.id, slot.id, 2)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(customer.id, slot.id, 2)


async def test_a_different_caller_still_gets_a_conflict(service, customer, slot) -> None:  # type: ignore[no-untyped-def]
    # This is the case the key has to stay distinguishable from: someone else
    # genuinely took the slot.
    await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(customer.id, slot.id, 2, idempotency_key="another-call")


@pytest.mark.parametrize(
    ("field", "value"),
    [("party_size", 3), ("slot_id", "other")],
)
async def test_reusing_a_key_with_different_parameters_is_rejected(  # type: ignore[no-untyped-def]
    service,
    customer,
    slot,
    field: str,
    value: object,
) -> None:
    other_slot = make_slot(capacity=4)
    service._bookings.slots[other_slot.id] = other_slot  # noqa: SLF001
    await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)

    args = {"customer_id": customer.id, "slot_id": slot.id, "party_size": 2}
    args[field] = other_slot.id if value == "other" else value

    # Returning the stored booking here would answer a question nobody asked.
    with pytest.raises(IdempotencyKeyReusedError) as error:
        await service.create_booking(idempotency_key=KEY, **args)  # type: ignore[arg-type]

    assert error.value.status_code == 409


async def test_the_replay_check_runs_before_any_other_validation(service, customer, slot) -> None:  # type: ignore[no-untyped-def]
    # Once the slot is taken, the replay must still succeed — otherwise the
    # retry would fail on the very availability check it is meant to bypass.
    first = await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY)

    assert service._bookings.slots[slot.id].is_available is False  # noqa: SLF001
    assert await service.create_booking(customer.id, slot.id, 2, idempotency_key=KEY) == first
