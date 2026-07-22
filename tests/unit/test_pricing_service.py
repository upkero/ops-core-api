from decimal import Decimal

import pytest

from src.app.exceptions.domain import EntityNotFoundError
from src.app.services.pricing import NoDiscountPolicy, PricingService, QuantityTierDiscountPolicy
from tests.fakes import FakePricingRepository, make_pricing_item


@pytest.fixture
def service() -> PricingService:
    repository = FakePricingRepository([make_pricing_item("Deep Tissue Massage", "120.00")])
    return PricingService(repository, QuantityTierDiscountPolicy())


@pytest.mark.parametrize(
    ("quantity", "expected_percent", "expected_total"),
    [
        (1, "0", "120.00"),
        (5, "0", "600.00"),  # boundary: the rule is "more than five"
        (6, "10", "648.00"),
        (19, "10", "2052.00"),
        (20, "15", "2040.00"),
    ],
)
async def test_quote_applies_the_matching_discount_tier(
    service: PricingService,
    quantity: int,
    expected_percent: str,
    expected_total: str,
) -> None:
    quote = await service.quote("Deep Tissue Massage", quantity)

    assert quote.discount_percent == Decimal(expected_percent)
    assert quote.total == Decimal(expected_total)
    assert quote.subtotal - quote.discount_amount == quote.total


async def test_quote_is_case_insensitive_on_the_service_name(service: PricingService) -> None:
    quote = await service.quote("deep tissue massage", 1)

    assert quote.service_name == "Deep Tissue Massage"


async def test_quote_rejects_an_unknown_service(service: PricingService) -> None:
    with pytest.raises(EntityNotFoundError) as error:
        await service.quote("Hot Air Balloon Ride", 1)

    assert error.value.status_code == 404


async def test_quote_rejects_a_non_positive_quantity(service: PricingService) -> None:
    with pytest.raises(ValueError, match="at least 1"):
        await service.quote("Deep Tissue Massage", 0)


async def test_swapping_the_policy_changes_the_price_without_touching_the_service() -> None:
    repository = FakePricingRepository([make_pricing_item("Deep Tissue Massage", "120.00")])

    discounted = await PricingService(repository, QuantityTierDiscountPolicy()).quote("Deep Tissue Massage", 10)
    full_price = await PricingService(repository, NoDiscountPolicy()).quote("Deep Tissue Massage", 10)

    assert discounted.total == Decimal("1080.00")
    assert full_price.total == Decimal("1200.00")


async def test_rounding_is_half_up_rather_than_bankers() -> None:
    # 3 x 8.35 = 25.05, less 10% = 2.505 -> 2.51, not the 2.50 that banker's
    # rounding would produce.
    repository = FakePricingRepository([make_pricing_item("Odd Price", "8.35")])
    service = PricingService(repository, QuantityTierDiscountPolicy([(3, Decimal("10"))]))

    quote = await service.quote("Odd Price", 3)

    assert quote.discount_amount == Decimal("2.51")
    assert quote.total == Decimal("22.54")


async def test_list_services_is_sorted_by_name() -> None:
    repository = FakePricingRepository([make_pricing_item("Zebra"), make_pricing_item("Alpha")])

    items = await PricingService(repository, NoDiscountPolicy()).list_services()

    assert [item.service_name for item in items] == ["Alpha", "Zebra"]
