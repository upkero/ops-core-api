"""The server span of a request: its name, its route, its parents and its children.

These run the production app, so they also pin what the pinned instrumentation
release gets wrong on this FastAPI (see `middleware/tracing.py`).
"""

from collections.abc import AsyncGenerator
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import ReadableSpan
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.app.db.session import build_engine, build_session_factory
from src.app.services.pricing import QuantityTierDiscountPolicy
from tests import telemetry
from tests.conftest import TEST_API_KEY, TEST_DB_URL, build_app
from tests.fakes import (
    FakeBookingRepository,
    FakeCustomerRepository,
    FakeEmbeddingClient,
    FakeKnowledgeRepository,
    FakePricingRepository,
)

pytestmark = pytest.mark.usefixtures("spans")


def server_spans() -> list[ReadableSpan]:
    return [span for span in telemetry.finished_spans() if span.kind.name == "SERVER"]


async def test_the_server_span_is_named_by_the_route_template_not_the_booking_id(client: AsyncClient) -> None:
    booking_id = uuid4()

    response = await client.delete(f"/api/v1/bookings/{booking_id}")

    assert response.status_code == 404
    (span,) = server_spans()
    assert span.name == "DELETE /api/v1/bookings/{booking_id}"
    assert (span.attributes or {})["http.route"] == "/api/v1/bookings/{booking_id}"
    # The id itself may sit on the span (a UUID is allowed there); it must not be what names it.
    assert str(booking_id) not in span.name


async def test_the_request_duration_metric_is_labelled_by_template(client: AsyncClient) -> None:
    template = "/api/v1/bookings/{booking_id}"
    before = telemetry.reading("http.server.request.duration", **{"http.route": template})

    await client.delete(f"/api/v1/bookings/{uuid4()}")
    await client.delete(f"/api/v1/bookings/{uuid4()}")

    assert telemetry.reading("http.server.request.duration", **{"http.route": template}) == before + 2


async def test_a_method_the_route_does_not_allow_is_a_405_not_a_crash(client: AsyncClient) -> None:
    response = await client.put("/api/v1/bookings")

    assert response.status_code == 405
    (span,) = server_spans()
    assert (span.attributes or {})["http.route"] == "/api/v1/bookings"


async def test_a_path_that_is_no_route_gets_no_route_label(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/{uuid4()}")

    assert response.status_code == 404
    (span,) = server_spans()
    assert "http.route" not in (span.attributes or {})


async def test_the_server_span_carries_the_request_id_the_logs_show(client: AsyncClient) -> None:
    response = await client.get("/api/v1/booking-slots", headers={"X-Request-ID": "room-abc123"})

    assert response.headers["X-Request-ID"] == "room-abc123"
    (span,) = server_spans()
    assert (span.attributes or {})["request_id"] == "room-abc123"


async def test_an_inbound_traceparent_makes_the_callers_span_the_parent(client: AsyncClient) -> None:
    trace_id, caller_span = "0af7651916cd43dd8448eb211c80319c", "b7ad6b7169203331"

    await client.get("/api/v1/booking-slots", headers={"traceparent": f"00-{trace_id}-{caller_span}-01"})

    (span,) = server_spans()
    assert format(span.context.trace_id, "032x") == trace_id
    assert span.parent is not None
    assert format(span.parent.span_id, "016x") == caller_span


async def test_a_throttled_request_is_still_a_span_and_is_counted(client: AsyncClient) -> None:
    # RATE_LIMIT_PER_MINUTE is 5 in the test environment.
    before = telemetry.reading("ops.rate_limited", route="/api/v1/booking-slots", limiter="global")
    for _ in range(5):
        assert (await client.get("/api/v1/booking-slots")).status_code == 200

    response = await client.get("/api/v1/booking-slots")

    assert response.status_code == 429
    assert telemetry.reading("ops.rate_limited", route="/api/v1/booking-slots", limiter="global") == before + 1
    assert (server_spans()[-1].attributes or {})["http.response.status_code"] == 429


async def test_the_embedding_limit_is_counted_apart_from_the_global_one(client: AsyncClient) -> None:
    # EMBEDDING_RATE_LIMIT_PER_MINUTE is 3, under the global 5.
    before = telemetry.reading("ops.rate_limited", route="/api/v1/documents/search", limiter="embedding")
    for _ in range(3):
        await client.post("/api/v1/documents/search", json={"query": "cancel", "top_k": 1})

    response = await client.post("/api/v1/documents/search", json={"query": "cancel", "top_k": 1})

    assert response.status_code == 429
    assert telemetry.reading("ops.rate_limited", route="/api/v1/documents/search", limiter="embedding") == before + 1


@pytest.fixture
async def database_app(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[FastAPI, None]:
    """The production app over the real engine the application builds, not the test one."""
    assert TEST_DB_URL is not None  # session_factory skipped the test otherwise
    engine: AsyncEngine = build_engine(TEST_DB_URL)
    app = build_app(
        FakeCustomerRepository(),
        FakeBookingRepository(),
        FakePricingRepository(),
        FakeKnowledgeRepository(),
        FakeEmbeddingClient(),
    )
    app.dependency_overrides.clear()
    app.state.container = SimpleNamespace(
        session_factory=build_session_factory(engine),
        discount_policy=QuantityTierDiscountPolicy(),
        embedding_client=FakeEmbeddingClient(),
    )
    yield app
    await engine.dispose()


async def test_a_statement_is_a_child_of_the_request_that_ran_it(database_app: FastAPI) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=database_app),
        base_url="http://testserver",
        headers={"X-API-Key": TEST_API_KEY},
    ) as client:
        response = await client.get("/api/v1/pricing/services")

    assert response.status_code == 200
    (server,) = server_spans()
    # Only this request's trace: the instrumentor also spans the fixture's own connections.
    selects = [
        span
        for span in telemetry.finished_spans()
        if span.name.startswith("SELECT") and span.context.trace_id == server.context.trace_id
    ]
    assert selects, "the engine the app builds is not instrumented"
    assert all(span.parent is not None and span.parent.span_id == server.context.span_id for span in selects)
