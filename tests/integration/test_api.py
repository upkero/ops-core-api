from uuid import uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests.conftest import StubContainer
from tests.fakes import FakeBookingRepository, FakeCustomerRepository, FakeEmbeddingClient


async def test_health_reports_the_database_as_reachable(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_reports_a_degraded_database(app: FastAPI) -> None:
    app.state.container = StubContainer(embedding_client=FakeEmbeddingClient(), database_healthy=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as unhealthy_client:
        response = await unhealthy_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


async def test_search_customers_by_name(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers", params={"search": "anna"})

    assert response.status_code == 200
    assert [customer["name"] for customer in response.json()["items"]] == ["Anna Petrova"]


async def test_list_customers_without_a_query(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers")

    body = response.json()
    assert len(body["items"]) == 2
    assert body["total"] == 2
    assert body["has_more"] is False


async def test_get_customer_by_id(client: AsyncClient, customers: FakeCustomerRepository) -> None:
    customer = customers.customers[0]

    response = await client.get(f"/api/v1/customers/{customer.id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(customer.id)
    assert response.json()["status"] == "active"


async def test_get_customer_returns_the_error_envelope_when_missing(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/customers/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "entity_not_found"


async def test_get_customer_rejects_a_malformed_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["error_code"] == "request_validation_error"


async def test_list_booking_slots_filters_by_date_and_resource(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/booking-slots",
        params={"date": "2026-08-01", "resource_type": "table"},
    )

    assert response.status_code == 200
    assert len(response.json()["items"]) == 2


async def test_list_booking_slots_rejects_an_unknown_resource_type(client: AsyncClient) -> None:
    response = await client.get("/api/v1/booking-slots", params={"resource_type": "helipad"})

    assert response.status_code == 422


async def test_create_booking_returns_201_and_removes_the_slot(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    slot = next(iter(slots.slots.values()))
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(slot.id), "party_size": 2}

    created = await client.post("/api/v1/bookings", json=body, headers=auth_headers)
    remaining = await client.get("/api/v1/booking-slots")

    assert created.status_code == 201
    assert created.json()["party_size"] == 2
    assert created.json()["guest_name"] == "Dmitri Volkov"
    assert str(slot.id) not in [item["id"] for item in remaining.json()["items"]]


async def test_booking_the_same_slot_twice_conflicts(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    slot = next(iter(slots.slots.values()))
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(slot.id), "party_size": 2}

    await client.post("/api/v1/bookings", json=body, headers=auth_headers)
    conflict = await client.post("/api/v1/bookings", json=body, headers=auth_headers)

    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "slot_unavailable"


async def test_booking_beyond_capacity_conflicts(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    slot = next(slot for slot in slots.slots.values() if slot.capacity == 2)
    body = {"guest_name": "Dmitri Volkov", "slot_id": str(slot.id), "party_size": 3}

    response = await client.post("/api/v1/bookings", json=body, headers=auth_headers)

    assert response.status_code == 409
    assert response.json()["error_code"] == "slot_capacity_exceeded"


async def test_booking_rejects_a_zero_party_size(
    client: AsyncClient,
    slots: FakeBookingRepository,
    auth_headers: dict[str, str],
) -> None:
    body = {
        "guest_name": "Dmitri Volkov",
        "slot_id": str(next(iter(slots.slots))),
        "party_size": 0,
    }

    response = await client.post("/api/v1/bookings", json=body, headers=auth_headers)

    assert response.status_code == 422


async def test_pricing_quote_applies_the_volume_discount(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pricing", params={"service": "Deep Tissue Massage", "quantity": 6})

    assert response.status_code == 200
    # Money is serialised as a string so cents survive the round trip exactly.
    assert response.json() == {
        "service_name": "Deep Tissue Massage",
        "unit_price": "120.00",
        "quantity": 6,
        "subtotal": "720.00",
        "discount_percent": "10",
        "discount_amount": "72.00",
        "total": "648.00",
    }


async def test_pricing_quote_without_a_discount(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pricing", params={"service": "Deep Tissue Massage", "quantity": 5})

    assert response.json()["discount_percent"] == "0"
    assert response.json()["total"] == "600.00"


async def test_pricing_requires_a_service(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/pricing")).status_code == 422


async def test_pricing_catalogue_lists_services(client: AsyncClient) -> None:
    response = await client.get("/api/v1/pricing/services")

    assert [item["service_name"] for item in response.json()["items"]] == ["Deep Tissue Massage", "Nutrition Coaching"]


async def test_add_document_then_search_finds_it(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await client.post(
        "/api/v1/documents",
        json={"title": "Cancellation policy", "content": "Cancel your appointment online at any time."},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/documents",
        json={"title": "Parking", "content": "Parking is free in the underground garage."},
        headers=auth_headers,
    )

    found = await client.post("/api/v1/documents/search", json={"query": "cancel appointment", "top_k": 2})

    assert created.status_code == 201
    assert created.json()["chunk_count"] == 1
    assert found.status_code == 200
    assert found.json()["query"] == "cancel appointment"
    assert found.json()["matches"][0]["document_title"] == "Cancellation policy"


async def test_search_rejects_an_empty_query(client: AsyncClient) -> None:
    response = await client.post("/api/v1/documents/search", json={"query": "", "top_k": 3})

    assert response.status_code == 422


async def test_every_response_carries_a_request_id(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers")

    assert response.headers["X-Request-ID"]


async def test_an_inbound_request_id_is_propagated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/customers", headers={"X-Request-ID": "trace-me-123"})

    assert response.headers["X-Request-ID"] == "trace-me-123"
