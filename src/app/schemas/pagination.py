from collections.abc import Callable

from pydantic import BaseModel, Field

from src.app.contracts.pagination import PageDTO


class Page[T](BaseModel):
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

    @classmethod
    def from_contract[C](cls, page: PageDTO[C], to_schema: Callable[[C], T]) -> "Page[T]":
        return cls(
            items=[to_schema(item) for item in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            has_more=page.has_more,
        )
