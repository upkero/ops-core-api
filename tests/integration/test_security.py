"""API key, rate limiting and CORS behaviour.

Exercised through the real middleware stack, because the interesting part is
how the layers compose — an early rejection still has to travel back out
through request-id and CORS.
"""

import pytest
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


async def test_write_without_a_key_is_rejected(client: AsyncClient, booking_body: dict[str, object]) -> None:
    response = await client.post("/api/v1/bookings", json=booking_body)

    assert response.status_code == 401
    assert response.json() == {
        "detail": "A valid X-API-Key header is required for this operation.",
        "error_code": "invalid_api_key",
    }


async def test_write_with_a_wrong_key_is_rejected(client: AsyncClient, booking_body: dict[str, object]) -> None:
    response = await client.post("/api/v1/bookings", json=booking_body, headers={"X-API-Key": "not-the-key"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_api_key"


async def test_a_key_that_is_a_prefix_of_the_real_one_is_rejected(
    client: AsyncClient,
    booking_body: dict[str, object],
) -> None:
    response = await client.post(
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


async def test_document_ingestion_needs_a_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/documents", json={"title": "t", "content": "some content"})

    assert response.status_code == 401


@pytest.mark.parametrize(
    "path",
    ["/health", "/api/v1/customers", "/api/v1/booking-slots", "/api/v1/pricing/services"],
)
async def test_reads_stay_open(client: AsyncClient, path: str) -> None:
    assert (await client.get(path)).status_code == 200


async def test_semantic_search_stays_open_despite_being_a_post(client: AsyncClient) -> None:
    # It is a read that happens to be a POST, because the query does not belong
    # in a URL. A method-only rule would have locked it.
    response = await client.post("/api/v1/documents/search", json={"query": "parking", "top_k": 1})

    assert response.status_code == 200


async def test_the_unauthorised_response_still_carries_cors_and_request_id(
    client: AsyncClient,
    booking_body: dict[str, object],
) -> None:
    # Proves the middleware ordering: a 401 raised in the innermost guard has
    # to travel back out through request-id and CORS.
    response = await client.post("/api/v1/bookings", json=booking_body, headers={"Origin": ORIGIN})

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


async def test_health_is_never_rate_limited(client: AsyncClient) -> None:
    # The container runtime polls it; throttling would fail the healthcheck.
    codes = [(await client.get("/health")).status_code for _ in range(12)]

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
