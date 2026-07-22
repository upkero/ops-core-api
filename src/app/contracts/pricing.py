from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class PricingItemDTO:
    id: UUID
    service_name: str
    unit_price: Decimal
    description: str | None


@dataclass(frozen=True, slots=True)
class PriceQuoteDTO:
    """Result of pricing a quantity of one service."""

    service_name: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    total: Decimal
