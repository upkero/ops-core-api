from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, status

from src.app.api.v1.dependencies import BookingServiceDep, PaginationDep
from src.app.contracts.enums import BookingStatus
from src.app.schemas.booking import BookingCreateRequest, BookingResponse
from src.app.schemas.pagination import Page

router = APIRouter(prefix="/bookings", tags=["bookings"])


@router.post("", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreateRequest,
    service: BookingServiceDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            max_length=64,
            description=(
                "Optional retry token. Repeating a request with the same key returns the booking "
                "that key already created instead of reporting the slot as taken."
            ),
        ),
    ] = None,
) -> BookingResponse:
    # Availability and capacity rules live in the service; the router only
    # translates schema -> arguments -> schema.
    booking = await service.create_booking(
        guest_name=body.guest_name,
        slot_id=body.slot_id,
        party_size=body.party_size,
        idempotency_key=idempotency_key,
    )
    return BookingResponse.from_contract(booking)


@router.get("", response_model=Page[BookingResponse])
async def find_bookings(
    service: BookingServiceDep,
    pagination: PaginationDep,
    guest_name: Annotated[str | None, Query(max_length=200, description="Case-insensitive name fragment.")] = None,
    slot_date: Annotated[date | None, Query(alias="date", description="Filter by the slot's calendar date.")] = None,
    status_filter: Annotated[
        BookingStatus | None,
        Query(alias="status", description="Defaults to active bookings only."),
    ] = BookingStatus.ACTIVE,
) -> Page[BookingResponse]:
    # Guarded by the API key even when reads are public: this is the one
    # endpoint that reveals who is dining where and when.
    page = await service.find_bookings(guest_name, slot_date, status_filter, pagination)
    return Page.from_contract(page, BookingResponse.from_contract)


@router.delete("/{booking_id}", response_model=BookingResponse)
async def cancel_booking(booking_id: UUID, service: BookingServiceDep) -> BookingResponse:
    # DELETE rather than POST /cancel: HTTP defines it as idempotent, which is
    # exactly the behaviour a dropped call needs, and the row survives as a
    # cancelled booking rather than being destroyed.
    return BookingResponse.from_contract(await service.cancel_booking(booking_id))
