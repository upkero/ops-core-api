"""One paging contract, applied identically to every collection.

The point of the shared helper is that a caller learns the rules once. These
tests run the same assertions against every list endpoint to keep it that way.
"""

import pytest
from httpx import AsyncClient

from src.app.contracts.pagination import MAX_LIMIT, PaginationParams
from tests.fakes import FakeCustomerRepository, make_customer

LIST_ENDPOINTS = ["/api/v1/customers", "/api/v1/booking-slots", "/api/v1/pricing/services"]


@pytest.fixture
def customers() -> FakeCustomerRepository:
    # Enough rows to page through several times.
    return FakeCustomerRepository([make_customer(f"Client {index:02d}") for index in range(25)])


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
async def test_every_list_endpoint_returns_the_same_envelope(client: AsyncClient, path: str) -> None:
    body = (await client.get(path)).json()

    assert set(body) == {"items", "total", "limit", "offset", "has_more"}


async def test_the_first_page_reports_what_is_beyond_it(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/customers", params={"limit": 10})).json()

    assert len(body["items"]) == 10
    # Without total, "10 results" is indistinguishable from "10 of 25".
    assert body["total"] == 25
    assert body["has_more"] is True


async def test_offset_walks_the_collection_without_gaps_or_repeats(client: AsyncClient) -> None:
    seen: list[str] = []
    for offset in (0, 10, 20):
        page = (await client.get("/api/v1/customers", params={"limit": 10, "offset": offset})).json()
        seen.extend(item["name"] for item in page["items"])

    assert len(seen) == 25
    assert len(set(seen)) == 25
    assert seen == sorted(seen)


async def test_the_last_page_reports_no_more(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/customers", params={"limit": 10, "offset": 20})).json()

    assert len(body["items"]) == 5
    assert body["has_more"] is False


async def test_an_offset_past_the_end_is_empty_but_still_reports_the_total(client: AsyncClient) -> None:
    body = (await client.get("/api/v1/customers", params={"offset": 999})).json()

    assert body["items"] == []
    assert body["total"] == 25
    assert body["has_more"] is False


async def test_total_counts_the_filtered_set_not_the_whole_table(client: AsyncClient) -> None:
    # The count has to follow the same WHERE clause as the rows, or paging
    # through a filtered search walks off the end of a phantom collection.
    body = (await client.get("/api/v1/customers", params={"search": "Client 1", "limit": 5})).json()

    assert body["total"] == 10  # Client 10..19
    assert len(body["items"]) == 5
    assert body["has_more"] is True


@pytest.mark.parametrize("path", LIST_ENDPOINTS)
@pytest.mark.parametrize(
    ("params", "reason"),
    [
        ({"limit": 0}, "limit below one"),
        ({"limit": MAX_LIMIT + 1}, "limit above the cap"),
        ({"offset": -1}, "negative offset"),
    ],
)
async def test_invalid_paging_is_rejected(
    client: AsyncClient,
    path: str,
    params: dict[str, int],
    reason: str,
) -> None:
    response = await client.get(path, params=params)

    assert response.status_code == 422, reason


def test_the_params_object_validates_itself() -> None:
    # Constructed directly by the seeding command and by the agent services,
    # which never pass through FastAPI's query validation.
    with pytest.raises(ValueError, match="limit must be between"):
        PaginationParams(limit=MAX_LIMIT + 1)
    with pytest.raises(ValueError, match="offset must not be negative"):
        PaginationParams(offset=-1)


async def test_has_more_is_derived_and_cannot_contradict_total(client: AsyncClient) -> None:
    for offset in (0, 10, 20, 25):
        body = (await client.get("/api/v1/customers", params={"limit": 10, "offset": offset})).json()

        expected = body["offset"] + len(body["items"]) < body["total"]
        assert body["has_more"] is expected
