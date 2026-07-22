from uuid import uuid4

import pytest

from src.app.exceptions.domain import EntityNotFoundError
from src.app.services.customer import CustomerService
from tests.fakes import FakeCustomerRepository, make_customer


async def test_get_returns_the_customer() -> None:
    customer = make_customer("Anna Petrova")
    service = CustomerService(FakeCustomerRepository([customer]))

    assert (await service.get(customer.id)).name == "Anna Petrova"


async def test_get_raises_for_a_missing_customer() -> None:
    service = CustomerService(FakeCustomerRepository([]))

    with pytest.raises(EntityNotFoundError) as error:
        await service.get(uuid4())

    assert error.value.status_code == 404


async def test_search_matches_a_name_fragment() -> None:
    service = CustomerService(FakeCustomerRepository([make_customer("Anna Petrova"), make_customer("Marcus Feld")]))

    found = await service.search("petro", limit=10)

    assert [customer.name for customer in found] == ["Anna Petrova"]


@pytest.mark.parametrize("query", [None, "", "   "])
async def test_search_without_a_query_lists_everyone(query: str | None) -> None:
    service = CustomerService(FakeCustomerRepository([make_customer("Anna"), make_customer("Marcus")]))

    assert len(await service.search(query, limit=10)) == 2


async def test_search_respects_the_limit() -> None:
    service = CustomerService(FakeCustomerRepository([make_customer(f"Client {i}") for i in range(10)]))

    assert len(await service.search("client", limit=3)) == 3
