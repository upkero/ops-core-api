from abc import ABC, abstractmethod
from decimal import Decimal


class DiscountPolicy(ABC):
    """Strategy: an interchangeable rule for how quantity affects price.

    PricingService holds one of these rather than an `if quantity > 5` branch,
    so a new promotion is a new class — the service does not change (Open/Closed).
    """

    @abstractmethod
    def discount_percent(self, quantity: int) -> Decimal:
        """Discount for this quantity, as a percentage between 0 and 100."""
