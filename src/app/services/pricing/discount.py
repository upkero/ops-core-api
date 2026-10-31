from collections.abc import Sequence
from decimal import Decimal

# (minimum quantity, discount percent). The business rule is "more than 5 units
# earns a discount", so the first tier starts at 6.
DEFAULT_TIERS: tuple[tuple[int, Decimal], ...] = (
    (6, Decimal("10")),
    (20, Decimal("15")),
)


def discount_percent(quantity: int, tiers: Sequence[tuple[int, Decimal]] = DEFAULT_TIERS) -> Decimal:
    """The best discount among the tiers the quantity reaches; 0 below the first."""
    return max((percent for minimum, percent in tiers if quantity >= minimum), default=Decimal("0"))
