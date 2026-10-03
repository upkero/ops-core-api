"""API key, rate limiting and CORS behaviour.

Exercised through the real middleware stack, because the interesting part is
how the layers compose — an early rejection still has to travel back out
through request-id and CORS.
"""

from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.conftest import TEST_API_KEY
from tests.fakes import FakeBookingRepository

ORIGIN = "http://localhost:3000"


@pytest.fixture
def booking_body(slots: FakeBookingRepository) -> dict[str, object]:
    return {
        "guest_name": "Dmitri Volkov",
        "slot_id": str(next(iter(slots.slots))),
        "party_size": 2,
    }


async def test_a_request_without_a_key_is_rejected(
    anonymous_client: AsyncClient,
    booking_body: dict[str, object],
) -> None:
    response = await anonymous_client.post("/api/v1/bookings", json=booking_body)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "A valid X-API-Key header is required for this operation.",
        "error_code": "invalid_api_key",
    }


async def test_a_wrong_key_is_rejected(anonymous_client: AsyncClient, booking_body: dict[str, object]) -> None:
    response = await anonymous_client.post(
        "/api/v1/bookings",
        json=booking_body,
        headers={"X-API-Key": "not-the-key"},
    )

    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_api_key"


async def test_a_key_that_is_a_prefix_of_the_real_one_is_rejected(
    anonymous_client: AsyncClient,
    booking_body: dict[str, object],
) -> None:
    response = await anonymous_client.post(
        "/api/v1/bookings",
        json=booking_body,
        headers={"X-API-Key": TEST_API_KEY[:-1]},
    )

    assert response.status_code == 401


async def test_write_with_the_right_key_succeeds(
    client: AsyncClient,
    booking_body: dict[str, object],
    auth_headers: dict[str, str],
) -> None:
    response = await client.post("/api/v1/bookings", json=booking_body, headers=auth_headers)

    assert response.status_code == 201


async def test_document_ingestion_needs_a_key(anonymous_client: AsyncClient) -> None:
    response = await anonymous_client.post("/api/v1/documents", json={"title": "t", "content": "some content"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/api/v1/customers", "/api/v1/booking-slots", "/api/v1/pricing/services", "/api/v1/bookings"],
)
async def test_every_read_needs_a_key_too(anonymous_client: AsyncClient, client: AsyncClient, path: str) -> None:
    # One rule for the whole API: there is no endpoint under /api/v1 that
    # answers without the key, so nothing can be left open by accident.
    assert (await anonymous_client.get(path)).status_code == 401
    assert (await client.get(path)).status_code == 200


async def test_semantic_search_needs_a_key(anonymous_client: AsyncClient, client: AsyncClient) -> None:
    body = {"query": "parking", "top_k": 1}

    assert (await anonymous_client.post("/api/v1/documents/search", json=body)).status_code == 401
    assert (await client.post("/api/v1/documents/search", json=body)).status_code == 200


@pytest.mark.parametrize("path", ["/health/live", "/health/ready", "/openapi.json", "/docs"])
async def test_infrastructure_endpoints_stay_open(anonymous_client: AsyncClient, path: str) -> None:
    # /health/* is polled by the container runtime and by the dependent
    # services; the schema endpoints have to load unauthenticated or Swagger UI
    # cannot render at all.
    assert (await anonymous_client.get(path)).status_code == 200


async def test_the_unauthorised_response_still_carries_cors_and_request_id(
    anonymous_client: AsyncClient,
    booking_body: dict[str, object],
) -> None:
    # The key is a dependency now, so the 401 is raised inside the routing
    # layer and travels back out through request-id and CORS like any other
    # handled error.
    response = await anonymous_client.post("/api/v1/bookings", json=booking_body, headers={"Origin": ORIGIN})

    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["X-Request-ID"]


async def test_the_global_rate_limit_applies(client: AsyncClient) -> None:
    # conftest sets RATE_LIMIT_PER_MINUTE=5.
    codes = [(await client.get("/api/v1/customers")).status_code for _ in range(6)]

    assert codes[:5] == [200] * 5
    assert codes[5] == 429


async def test_the_rate_limited_response_uses_the_shared_error_envelope(client: AsyncClient) -> None:
    for _ in range(5):
        await client.get("/api/v1/customers")

    response = await client.get("/api/v1/customers")

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limit_exceeded"
    assert "Rate limit exceeded" in response.json()["detail"]


async def test_the_rate_limited_response_tells_the_client_when_to_retry(client: AsyncClient) -> None:
    for _ in range(6):
        response = await client.get("/api/v1/customers")

    assert int(response.headers["Retry-After"]) >= 0
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "0"


async def test_the_rate_limited_response_still_carries_cors_and_request_id(client: AsyncClient) -> None:
    for _ in range(6):
        response = await client.get("/api/v1/customers", headers={"Origin": ORIGIN})

    assert response.status_code == 429
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["X-Request-ID"]


async def test_limits_are_counted_per_path(client: AsyncClient) -> None:
    # Hammering one endpoint must not lock a client out of the whole API.
    for _ in range(6):
        await client.get("/api/v1/customers")

    assert (await client.get("/api/v1/pricing/services")).status_code == 200


@pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
async def test_health_is_never_rate_limited(client: AsyncClient, path: str) -> None:
    # The container runtime polls liveness and four services poll readiness;
    # throttling either would report this API as down while it is serving.
    codes = [(await client.get(path)).status_code for _ in range(12)]

    assert codes == [200] * 12


async def test_embedding_endpoints_have_a_stricter_limit(client: AsyncClient) -> None:
    # conftest sets EMBEDDING_RATE_LIMIT_PER_MINUTE=3, below the global 5.
    codes = [
        (await client.post("/api/v1/documents/search", json={"query": "parking"})).status_code for _ in range(4)
    ]

    assert codes[:3] == [200] * 3
    assert codes[3] == 429
    assert (await client.post("/api/v1/documents/search", json={"query": "parking"})).json()["error_code"] == (
        "rate_limit_exceeded"
    )


async def test_cors_preflight_is_allowed_for_a_known_origin(client: AsyncClient) -> None:
    response = await client.request(
        "OPTIONS",
        "/api/v1/bookings",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "x-api-key" in response.headers["access-control-allow-headers"].lower()


async def test_cors_preflight_is_refused_for_an_unknown_origin(client: AsyncClient) -> None:
    response = await client.request(
        "OPTIONS",
        "/api/v1/bookings",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )

    assert "access-control-allow-origin" not in response.headers


async def test_credentials_are_not_allowed(client: AsyncClient) -> None:
    # The key travels in a header, so cookies are never needed; allowing
    # credentials would widen the surface for nothing.
    response = await client.get("/api/v1/customers", headers={"Origin": ORIGIN})

    assert "access-control-allow-credentials" not in response.headers


class TestOpenApiSecurity:
    """Swagger must show the key, and the schema must match what is enforced.

    Declaring the guard as a Security() dependency means FastAPI derives both
    from the same object — there is no hand-written schema to drift.
    """

    def test_the_key_scheme_is_published(self, app: FastAPI) -> None:
        schemes = app.openapi()["components"]["securitySchemes"]

        scheme = next(iter(schemes.values()))
        assert scheme["type"] == "apiKey"
        assert scheme["in"] == "header"
        assert scheme["name"] == "X-API-Key"

    def test_every_api_operation_is_marked_as_secured(self, app: FastAPI) -> None:
        unsecured = [
            f"{method.upper()} {path}"
            for path, operations in app.openapi()["paths"].items()
            for method, operation in operations.items()
            if path.startswith("/api/v1") and "security" not in operation
        ]

        assert unsecured == []

    @pytest.mark.parametrize("path", ["/health/live", "/health/ready"])
    def test_health_is_not_marked_as_secured(self, app: FastAPI, path: str) -> None:
        assert "security" not in app.openapi()["paths"][path]["get"]


async def test_ids_in_the_path_share_one_counter(client: AsyncClient) -> None:
    # /bookings/{id} is one endpoint, however many ids it is called with. Counted per
    # concrete path, every id would start with a fresh allowance and nothing would cap it.
    codes = [(await client.delete(f"/api/v1/bookings/{uuid4()}")).status_code for _ in range(6)]

    assert codes[:5] == [404] * 5
    assert codes[5] == 429


async def test_unknown_paths_share_one_counter(client: AsyncClient) -> None:
    codes = [(await client.get(f"/api/v1/nope-{index}")).status_code for index in range(6)]

    assert codes[5] == 429
    # ...without touching the allowance of the real endpoints.
    assert (await client.get("/api/v1/customers")).status_code == 200

