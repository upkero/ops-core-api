from decimal import Decimal
from uuid import UUID

from src.app.schemas.base import ResponseModel


class PricingItemResponse(ResponseModel):
    id: UUID
    service_name: str
    unit_price: Decimal
    description: str | None



class PriceQuoteResponse(ResponseModel):
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
