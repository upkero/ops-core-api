from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from src.app.contracts.pricing import PriceQuoteDTO, PricingItemDTO


class PricingItemResponse(BaseModel):
    id: UUID
    service_name: str
    unit_price: Decimal
    description: str | None

    @classmethod
    def from_contract(cls, item: PricingItemDTO) -> "PricingItemResponse":
        return cls(
            id=item.id,
            service_name=item.service_name,
            unit_price=item.unit_price,
            description=item.description,
        )


class PriceQuoteResponse(BaseModel):
    """Money fields are Decimal and serialise as JSON strings ("240.00").

    Deliberate: rendering them as floats would hand clients a value that
    cannot represent cents exactly.
    """

    service_name: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    total: Decimal

    @classmethod
    def from_contract(cls, quote: PriceQuoteDTO) -> "PriceQuoteResponse":
        return cls(
            service_name=quote.service_name,
            unit_price=quote.unit_price,
            quantity=quote.quantity,
            subtotal=quote.subtotal,
            discount_percent=quote.discount_percent,
            discount_amount=quote.discount_amount,
            total=quote.total,
        )
