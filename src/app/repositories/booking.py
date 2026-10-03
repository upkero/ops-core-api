from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import BookingStatus, ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.interfaces.repositories.booking_repository import BookingRepository, IdempotencyKeyTakenError
from src.app.models.booking import Booking, BookingSlot
from src.app.repositories.pagination import paginate


def _slot_to_dto(row: BookingSlot) -> BookingSlotDTO:
    return BookingSlotDTO(
        id=row.id,
        resource_type=row.resource_type,
        slot_date=row.slot_date,
        slot_time=row.slot_time,
        capacity=row.capacity,
        is_available=row.is_available,
    )


def _booking_to_dto(row: Booking) -> BookingDTO:
    return BookingDTO(
        id=row.id,
        guest_name=row.guest_name,
        slot_id=row.slot_id,
        party_size=row.party_size,
        created_at=row.created_at,
        status=row.status,
        cancelled_at=row.cancelled_at,
    )


class SqlAlchemyBookingRepository(BookingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
        not_before: datetime | None = None,
    ) -> PageDTO[BookingSlotDTO]:
        stmt = select(BookingSlot).where(BookingSlot.is_available.is_(True))
        if not_before is not None:
            stmt = stmt.where(
                or_(
                    BookingSlot.slot_date > not_before.date(),
                    and_(BookingSlot.slot_date == not_before.date(), BookingSlot.slot_time > not_before.time()),
                )
            )
        if slot_date is not None:
            stmt = stmt.where(BookingSlot.slot_date == slot_date)
        if resource_type is not None:
            stmt = stmt.where(BookingSlot.resource_type == resource_type)
        stmt = stmt.order_by(BookingSlot.slot_date, BookingSlot.slot_time)
        # `total` is counted over exactly these filters, so a caller asking for
        # Tuesday sees how many Tuesday slots exist, not how many exist overall.
        return await paginate(self._session, stmt, params, _slot_to_dto)

    async def lock_slot(self, slot_id: UUID) -> BookingSlotDTO | None:
        # FOR UPDATE holds the row until the request transaction ends, so a
        # concurrent booking for the same slot waits here and then observes
        # is_available=False instead of racing past the check.
        stmt = select(BookingSlot).where(BookingSlot.id == slot_id).with_for_update()
        row = await self._session.scalar(stmt)
        return _slot_to_dto(row) if row is not None else None

    async def get_by_idempotency_key(self, idempotency_key: str) -> BookingDTO | None:
        row = await self._session.scalar(select(Booking).where(Booking.idempotency_key == idempotency_key))
        return _booking_to_dto(row) if row is not None else None

    async def create_booking(
        self,
        guest_name: str,
        slot_id: UUID,
        party_size: int,
        idempotency_key: str | None = None,
    ) -> BookingDTO:
        booking = Booking(
            guest_name=guest_name,
            slot_id=slot_id,
            party_size=party_size,
            idempotency_key=idempotency_key,
        )
        try:
            # A savepoint, so that a refused insert leaves the request's transaction usable:
            # the caller still has to look the winning booking up.
            async with self._session.begin_nested():
                self._session.add(booking)
                # Flush, not commit: the request-scoped transaction owns the commit.
                # This populates server-side defaults so the DTO is complete.
                await self._session.flush()
        except IntegrityError as error:
            # Another request inserted the same key first (this insert waited for it to commit).
            # Anything else that violates a constraint is a bug and stays an error.
            if idempotency_key is not None and await self.get_by_idempotency_key(idempotency_key) is not None:
                raise IdempotencyKeyTakenError(idempotency_key) from error
            raise
        await self._session.refresh(booking)
        return _booking_to_dto(booking)

    async def mark_slot_taken(self, slot_id: UUID) -> None:
        await self._set_slot_available(slot_id, available=False)

    async def mark_slot_free(self, slot_id: UUID) -> None:
        await self._set_slot_available(slot_id, available=True)

    async def _set_slot_available(self, slot_id: UUID, *, available: bool) -> None:
        await self._session.execute(
            update(BookingSlot).where(BookingSlot.id == slot_id).values(is_available=available)
        )

    async def get_booking(self, booking_id: UUID) -> BookingDTO | None:
        row = await self._session.get(Booking, booking_id)
        return _booking_to_dto(row) if row is not None else None

    async def list_bookings(
        self,
        guest_name: str | None,
        slot_date: date | None,
        status: BookingStatus | None,
        params: PaginationParams,
    ) -> PageDTO[BookingDTO]:
        stmt = select(Booking).join(BookingSlot, Booking.slot_id == BookingSlot.id)
        if guest_name:
            pattern = f"%{guest_name.replace('!', '!!').replace('%', '!%').replace('_', '!_')}%"
            stmt = stmt.where(Booking.guest_name.ilike(pattern, escape="!"))
        if slot_date is not None:
            stmt = stmt.where(BookingSlot.slot_date == slot_date)
        if status is not None:
            stmt = stmt.where(Booking.status == status)
        stmt = stmt.order_by(BookingSlot.slot_date, BookingSlot.slot_time)
        return await paginate(self._session, stmt, params, _booking_to_dto)

    async def mark_cancelled(self, booking_id: UUID) -> BookingDTO:
        row = await self._session.get(Booking, booking_id)
        if row is None:
            raise LookupError(f"Booking {booking_id} disappeared while cancelling it.")
        row.status = BookingStatus.CANCELLED
        row.cancelled_at = datetime.now(UTC)
        await self._session.flush()
        return _booking_to_dto(row)
