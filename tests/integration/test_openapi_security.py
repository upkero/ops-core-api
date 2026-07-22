"""The documented security must match the enforced security.

The key is applied by middleware, which FastAPI's schema generator cannot see,
so the two could easily drift apart: Swagger showing an open padlock on an
endpoint that returns 401, or the reverse. These tests pin them together.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.v1.openapi import SECURITY_SCHEME_NAME
from tests.conftest import TEST_API_KEY, build_app
from tests.fakes import (
    FakeBookingRepository,
    FakeCustomerRepository,
    FakeEmbeddingClient,
    FakeKnowledgeRepository,
    FakePricingRepository,
)

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})


def _operations(app: FastAPI) -> dict[tuple[str, str], dict[str, object]]:
    schema = app.openapi()
    return {
        (method.upper(), path): operation
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if method in _HTTP_METHODS
    }


def test_the_api_key_scheme_is_published(app: FastAPI) -> None:
    scheme = app.openapi()["components"]["securitySchemes"][SECURITY_SCHEME_NAME]

    # Without this block Swagger UI renders no Authorize button at all.
    assert scheme["type"] == "apiKey"
    assert scheme["in"] == "header"
    assert scheme["name"] == "X-API-Key"


def test_write_operations_are_marked_as_secured(app: FastAPI) -> None:
    operations = _operations(app)

    assert operations[("POST", "/api/v1/bookings")]["security"] == [{SECURITY_SCHEME_NAME: []}]
    assert operations[("POST", "/api/v1/documents")]["security"] == [{SECURITY_SCHEME_NAME: []}]


def test_secured_operations_document_the_401(app: FastAPI) -> None:
    responses = _operations(app)[("POST", "/api/v1/bookings")]["responses"]

    assert "401" in responses  # type: ignore[operator]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/health"),
        ("GET", "/api/v1/customers"),
        ("GET", "/api/v1/pricing"),
        ("POST", "/api/v1/documents/search"),
    ],
)
def test_public_operations_are_not_marked(app: FastAPI, method: str, path: str) -> None:
    assert "security" not in _operations(app)[(method, path)]


async def test_documented_security_matches_what_the_server_enforces(app: FastAPI) -> None:
    """Every operation's padlock is checked against a real unauthenticated call."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        for (method, path), operation in _operations(app).items():
            if "{" in path:  # skip templated paths; covered by test_api.py
                continue
            response = await client.request(method, path, json={} if method == "POST" else None)
            documented_as_secured = "security" in operation
            assert (response.status_code == 401) is documented_as_secured, (
                f"{method} {path}: schema says secured={documented_as_secured}, server returned {response.status_code}"
            )


class TestPrivateReads:
    """PUBLIC_READS=false — the posture for a private backend holding real data."""

    @pytest.fixture
    def private_app(
        self,
        private_reads: None,
        customers: FakeCustomerRepository,
        slots: FakeBookingRepository,
        pricing: FakePricingRepository,
        knowledge: FakeKnowledgeRepository,
        embedding_client: FakeEmbeddingClient,
    ) -> FastAPI:
        return build_app(customers, slots, pricing, knowledge, embedding_client)

    @pytest.fixture
    async def private_client(self, private_app: FastAPI) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=private_app), base_url="http://testserver")

    @pytest.mark.parametrize(
        "path",
        ["/api/v1/customers", "/api/v1/booking-slots", "/api/v1/pricing/services"],
    )
    async def test_reads_now_require_the_key(self, private_client: AsyncClient, path: str) -> None:
        async with private_client as client:
            assert (await client.get(path)).status_code == 401
            assert (await client.get(path, headers={"X-API-Key": TEST_API_KEY})).status_code == 200

    async def test_semantic_search_now_requires_the_key(self, private_client: AsyncClient) -> None:
        async with private_client as client:
            unauthenticated = await client.post("/api/v1/documents/search", json={"query": "parking"})
            authenticated = await client.post(
                "/api/v1/documents/search",
                json={"query": "parking"},
                headers={"X-API-Key": TEST_API_KEY},
            )

        assert unauthenticated.status_code == 401
        assert authenticated.status_code == 200

    async def test_health_stays_open_for_the_container_runtime(self, private_client: AsyncClient) -> None:
        async with private_client as client:
            assert (await client.get("/health")).status_code == 200

    @pytest.mark.parametrize("path", ["/openapi.json", "/docs"])
    async def test_the_schema_stays_reachable_so_swagger_can_render(
        self,
        private_client: AsyncClient,
        path: str,
    ) -> None:
        async with private_client as client:
            assert (await client.get(path)).status_code == 200

    async def test_cors_preflight_is_never_challenged(self, private_client: AsyncClient) -> None:
        # A browser sends OPTIONS without custom headers by definition, so
        # demanding a key here would break CORS for every origin.
        async with private_client as client:
            response = await client.request(
                "OPTIONS",
                "/api/v1/customers",
                headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:3000"

    def test_the_schema_marks_reads_as_secured_too(self, private_app: FastAPI) -> None:
        operations = _operations(private_app)

        assert operations[("GET", "/api/v1/customers")]["security"] == [{SECURITY_SCHEME_NAME: []}]
        assert operations[("POST", "/api/v1/documents/search")]["security"] == [{SECURITY_SCHEME_NAME: []}]
        assert "security" not in operations[("GET", "/health")]
