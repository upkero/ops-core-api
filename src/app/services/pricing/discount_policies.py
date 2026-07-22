from collections.abc import Sequence
from decimal import Decimal

from src.app.interfaces.pricing.discount_policy import DiscountPolicy

# (minimum quantity, discount percent), ascending. The business rule is
# "more than 5 units earns a discount", so the first tier starts at 6.
DEFAULT_TIERS: tuple[tuple[int, Decimal], ...] = (
    (6, Decimal("10")),
    (20, Decimal("15")),
)


class NoDiscountPolicy(DiscountPolicy):
    """Every quantity is charged at list price."""

    def discount_percent(self, quantity: int) -> Decimal:
        return Decimal("0")


class QuantityTierDiscountPolicy(DiscountPolicy):
    """Volume discount: the highest tier the quantity reaches wins."""

    def __init__(self, tiers: Sequence[tuple[int, Decimal]] = DEFAULT_TIERS) -> None:
        self._tiers = sorted(tiers, key=lambda tier: tier[0])

    def discount_percent(self, quantity: int) -> Decimal:
        percent = Decimal("0")
        for minimum_quantity, tier_percent in self._tiers:
            if quantity >= minimum_quantity:
                percent = tier_percent
        return percent
