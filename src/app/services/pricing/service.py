from decimal import ROUND_HALF_UP, Decimal

from src.app.contracts.pagination import PageDTO, PaginationParams
from src.app.contracts.pricing import PriceQuoteDTO, PricingItemDTO
from src.app.exceptions.domain import EntityNotFoundError, InvalidInputError
from src.app.interfaces.pricing.discount_policy import DiscountPolicy
from src.app.interfaces.repositories.pricing_repository import PricingRepository

_CENTS = Decimal("0.01")


class PricingService:
    """Prices a quantity of a service, applying the configured discount rule."""

    def __init__(self, repository: PricingRepository, discount_policy: DiscountPolicy) -> None:
        # Depends on the ports, not on SqlAlchemyPricingRepository or on a
        # specific discount rule (Dependency Inversion).
        self._repository = repository
        self._discount_policy = discount_policy

    async def list_services(self, params: PaginationParams) -> PageDTO[PricingItemDTO]:
        return await self._repository.list_all(params)

    async def quote(self, service_name: str, quantity: int) -> PriceQuoteDTO:
        if quantity < 1:
            raise InvalidInputError("Quantity must be at least 1.")

        item = await self._repository.get_by_service_name(service_name)
        if item is None:
            raise EntityNotFoundError(f"No pricing found for service '{service_name}'.")

        subtotal = self._to_cents(item.unit_price * quantity)
        discount_percent = self._discount_policy.discount_percent(quantity)
        discount_amount = self._to_cents(subtotal * discount_percent / Decimal("100"))

        return PriceQuoteDTO(
            service_name=item.service_name,
            unit_price=item.unit_price,
            quantity=quantity,
            subtotal=subtotal,
            discount_percent=discount_percent,
            discount_amount=discount_amount,
            total=subtotal - discount_amount,
        )

    @staticmethod
    def _to_cents(amount: Decimal) -> Decimal:
        # Explicit half-up rounding: Decimal defaults to banker's rounding,
        # which is not what an invoice line is expected to do.
        return amount.quantize(_CENTS, rounding=ROUND_HALF_UP)
