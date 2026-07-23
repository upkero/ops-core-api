from datetime import date
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.booking import BookingDTO, BookingSlotDTO
from src.app.contracts.enums import ResourceType
from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.interfaces.repositories.booking_repository import BookingRepository
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
    )


class SqlAlchemyBookingRepository(BookingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_available_slots(
        self,
        slot_date: date | None,
        resource_type: ResourceType | None,
        params: PaginationParams,
    ) -> PageDTO[BookingSlotDTO]:
        stmt = select(BookingSlot).where(BookingSlot.is_available.is_(True))
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
        self._session.add(booking)
        # Flush, not commit: the request-scoped transaction owns the commit.
        # This populates server-side defaults so the DTO is complete.
        await self._session.flush()
        await self._session.refresh(booking)
        return _booking_to_dto(booking)

    async def mark_slot_taken(self, slot_id: UUID) -> None:
        await self._session.execute(
            update(BookingSlot).where(BookingSlot.id == slot_id).values(is_available=False)
        )
