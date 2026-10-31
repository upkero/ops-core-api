import time
from collections.abc import Callable
from datetime import UTC, date, datetime, tzinfo
from logging import getLogger
from uuid import UUID

from opentelemetry import trace

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.core.metrics import (
    availability_checks,
    booking_lookups,
    booking_rejections,
    bookings_cancelled,
    bookings_created,
)
from src.app.core.telemetry import guest_name_fp
from src.app.exceptions.base import BaseAppException
from src.app.exceptions.domain import (
    EntityNotFoundError,
    IdempotencyKeyConsumedError,
    IdempotencyKeyReusedError,
    InvalidInputError,
    SlotCapacityExceededError,
    SlotInPastError,
    SlotUnavailableError,
)
from src.app.interfaces.repositories.booking_repository import BookingRepository, IdempotencyKeyTakenError

logger = getLogger(__name__)
_tracer = trace.get_tracer(__name__)


def _log(event: str, started: float, message: str, **fields: object) -> None:
    duration_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(message, extra={"event": event, **fields, "duration_ms": duration_ms})


class BookingService:
    """Owns the rules for taking a booking.

    The rules live here rather than in the router so that any caller — HTTP,
    the seeding command, a future agent service — gets the same guarantees.
    """

    def __init__(
        self,
        bookings: BookingRepository,
        *,
        business_tz: tzinfo = UTC,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        # One dependency: a booking is a slot and a name. Resolving a CRM
        # account is a different flow's job, so this service never needs to
        # reach for one.
        self._bookings = bookings
        # Slots are stored as a bare date and time: the wall clock of the business,
        # not an instant. "Has it started" therefore compares against the current
        # time in the business's zone, which the clock is converted into here.
        self._business_tz = business_tz
        self._clock = clock

    def _local_now(self) -> datetime:
        return self._clock().astimezone(self._business_tz).replace(tzinfo=None)

    async def find_bookings(
        self,
        guest_name: str | None,
        slot_date: date | None,
        status: BookingStatus | None,
        params: PaginationParams,
    ) -> PageDTO[BookingDTO]:
        started = time.perf_counter()
        by = {(True, True): "name_date", (True, False): "name", (False, True): "date"}.get(
            (bool(guest_name), slot_date is not None), "none"
        )
        with _tracer.start_as_current_span("booking.find", attributes={"ops.lookup.by": by}) as span:
            page = await self._bookings.list_bookings(guest_name, slot_date, status, params)
            result = "found" if page.total else "not_found"
            fingerprint = guest_name_fp(guest_name) if guest_name else ""
            span.set_attribute("ops.results.count", page.total)
            span.set_attribute("booking.guest_name_fp", fingerprint)
        booking_lookups.add(1, {"by": by, "result": result})
        _log(
            "booking.lookup",
            started,
            f"Booking lookup: {result}",
            by=by,
            result=result,
            results=page.total,
            guest_name_fp=fingerprint,
        )
        return page

    async def cancel_booking(self, booking_id: UUID) -> BookingDTO:
        """Cancel a reservation and put the slot back on offer.

        Idempotent: cancelling an already-cancelled booking returns it
        unchanged rather than failing. A dropped call retries, and the caller
        should not have to distinguish "I cancelled it" from "I cancelled it
        twice".
        """
        started = time.perf_counter()
        with _tracer.start_as_current_span("booking.cancel", attributes={"booking.id": str(booking_id)}) as span:
            booking, outcome = await self._cancel_booking(booking_id)
            span.set_attribute("ops.outcome", outcome)
        bookings_cancelled.add(1, {"outcome": outcome})
        _log("booking.cancelled", started, f"Booking cancel: {outcome}", booking_id=str(booking_id), outcome=outcome)
        if booking is None:
            raise EntityNotFoundError(f"Booking '{booking_id}' was not found.")
        return booking

    async def _cancel_booking(self, booking_id: UUID) -> tuple[BookingDTO | None, str]:
        """The booking after the call (None when there is none) and what happened to it."""
        booking = await self._bookings.get_booking(booking_id)
        if booking is None:
            return None, "not_found"
        if booking.status is BookingStatus.CANCELLED:
            return booking, "already_cancelled"

        cancelled = await self._bookings.mark_cancelled(booking_id)
        # Freeing the slot is the point of cancelling: it has to become
        # bookable again in the same transaction, or the table sits empty.
        await self._bookings.mark_slot_free(booking.slot_id)
        return cancelled, "cancelled"

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]:
        label = resource_type.value if resource_type is not None else "any"
        with _tracer.start_as_current_span("booking.check_availability", attributes={"resource_type": label}) as span:
            page = await self._bookings.list_available_slots(
                slot_date, resource_type, params, not_before=self._local_now()
            )
            span.set_attribute("ops.slots.returned", len(page.items))
        availability_checks.add(1, {"resource_type": label, "result": "slots" if page.total else "empty"})
        return page

    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        started = time.perf_counter()
        fingerprint = guest_name_fp(guest_name)
        fields = {"slot_id": str(slot_id), "party_size": party_size, "guest_name_fp": fingerprint}
        with _tracer.start_as_current_span(
            "booking.create", attributes={"ops.party_size": party_size, "booking.guest_name_fp": fingerprint}
        ) as span:
            try:
                booking, slot, replayed = await self._create_booking(guest_name, slot_id, party_size, idempotency_key)
            except BaseAppException as exc:
                span.set_attribute("ops.outcome", exc.error_code)
                booking_rejections.add(1, {"reason": exc.error_code})
                message = f"Booking rejected: {exc.error_code}"
                _log("booking.rejected", started, message, reason=exc.error_code, **fields)
                raise
            span.set_attribute("ops.outcome", "created")
            span.set_attribute("ops.idempotent_replay", replayed)
        # A replay answered before the slot was locked never saw the slot, so its type is unknown.
        bookings_created.add(
            1,
            {
                "resource_type": slot.resource_type.value if slot is not None else "unknown",
                "idempotent": "replayed" if replayed else "new",
            },
        )
        _log(
            "booking.created",
            started,
            "Booking created",
            booking_id=str(booking.id),
            **fields,
            idempotent_replay=replayed,
        )
        return booking

    async def _create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None,
    ) -> tuple[BookingDTO, BookingSlotDTO | None, bool]:
        """The booking, the slot it took (None when a replay answered first), and whether it was a replay."""
        name = guest_name.strip()
        if not name:
            raise InvalidInputError("A booking needs a guest name.")

        # Replay check comes first. A voice call that times out mid-request
        # retries; without this the retry hits "slot taken" and the caller
        # cannot tell its own successful booking from someone else's.
        if idempotency_key is not None:
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is not None:
                return replayed, None, True

        # Locking first is what makes the checks below trustworthy: a competing
        # request for the same slot blocks here and then sees is_available=False.
        slot = await self._bookings.lock_slot(slot_id)
        # A retry fired while the first request was still in flight passed the check above
        # (nothing was stored yet), then waited for the lock. The first request has committed
        # by now, so look again: the answer is its booking, not "slot taken".
        if idempotency_key is not None:
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is not None:
                return replayed, slot, True
        if slot is None:
            raise EntityNotFoundError(f"Booking slot '{slot_id}' was not found.")
        if datetime.combine(slot.slot_date, slot.slot_time) <= self._local_now():
            raise SlotInPastError(f"Booking slot '{slot_id}' has already started.")
        if not slot.is_available:
            raise SlotUnavailableError(f"Booking slot '{slot_id}' is already taken.")
        if party_size > slot.capacity:
            raise SlotCapacityExceededError(
                f"Party of {party_size} exceeds the slot capacity of {slot.capacity}."
            )

        try:
            booking = await self._bookings.create_booking(name, slot_id, party_size, idempotency_key)
        except IdempotencyKeyTakenError:
            # The same key on a different slot, sent at the same moment: the other request
            # holds the key and this one waited on the unique index. Same answer as a retry.
            if idempotency_key is None:
                raise
            replayed = await self._replay(idempotency_key, name, slot_id, party_size)
            if replayed is None:
                raise
            return replayed, slot, True
        await self._bookings.mark_slot_taken(slot_id)
        return booking, slot, False

    async def _replay(self, idempotency_key: str, name: str, slot_id: UUID, party_size: int) -> BookingDTO | None:
        """The booking this key already made, if any; refuses a key that cannot be replayed."""
        replayed = await self._bookings.get_by_idempotency_key(idempotency_key)
        if replayed is None:
            return None
        if (replayed.guest_name, replayed.slot_id, replayed.party_size) != (name, slot_id, party_size):
            raise IdempotencyKeyReusedError()
        # Only an active booking may be replayed. Handing back a cancelled one would
        # answer "booked" with a reservation that no longer exists, leaving the slot
        # free and the caller believing they have a table.
        if replayed.status is BookingStatus.CANCELLED:
            raise IdempotencyKeyConsumedError()
        return replayed
