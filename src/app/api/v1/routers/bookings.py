from typing import Annotated

from fastapi import APIRouter, Header, status

from src.app.api.v1.dependencies import BookingServiceDep
from src.app.schemas.booking import BookingCreateRequest, BookingResponse

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
        customer_id=body.customer_id,
        slot_id=body.slot_id,
        party_size=body.party_size,
        idempotency_key=idempotency_key,
    )
    return BookingResponse.from_contract(booking)
