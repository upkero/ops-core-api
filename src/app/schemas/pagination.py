from pydantic import Field

from src.app.schemas.base import ResponseModel


class Page[T](ResponseModel):
    """Envelope for every list endpoint.

    One generic model rather than a wrapper per resource, so the shape a client
    has to handle is identical everywhere and OpenAPI documents it as
    Page[Customer], Page[BookingSlot] and so on.
    """

    items: list[T]
    total: int = Field(..., description="Rows matching the filters, ignoring limit and offset.")
    limit: int
    offset: int
    has_more: bool = Field(..., description="True when further rows exist beyond this page.")
