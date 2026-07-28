import os
from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.app.api.v1.dependencies import (
    get_booking_service,
    get_customer_service,
    get_knowledge_service,
    get_pricing_service,
)
from src.app.api.v1.middleware.rate_limit import limiter, reset_global_rate_limit
from src.app.services.booking import BookingService
from src.app.services.customer import CustomerService
from src.app.services.knowledge import KnowledgeService
from src.app.services.pricing import PricingService, QuantityTierDiscountPolicy
from tests.fakes import (
    FakeBookingRepository,
    FakeCustomerRepository,
    FakeEmbeddingClient,
    FakeKnowledgeRepository,
    FakePricingRepository,
    make_customer,
    make_pricing_item,
    make_slot,
)

# No module under src/app reads settings at import time, so these assignments
# do not have to come before the imports above — which is why this file needs
# no per-import lint suppressions. Environment variables take priority over any
# local .env, so a developer's own file cannot change what the tests assert on.
TEST_API_KEY = "test-api-key-long-enough-1234567890"
os.environ["API_KEY"] = TEST_API_KEY
os.environ["RATE_LIMIT_PER_MINUTE"] = "5"
os.environ["EMBEDDING_RATE_LIMIT_PER_MINUTE"] = "3"
os.environ["CORS_ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["EMBEDDING_PROVIDER"] = "hashing"
os.environ.setdefault("DB_URL", "postgresql+asyncpg://unused:unused@localhost:1/unused")
os.environ.setdefault("LOG_LEVEL", "WARNING")


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> Iterator[None]:
    """Keep cases independent: counters are process-global."""
    reset_global_rate_limit()
    limiter.reset()
    yield
    reset_global_rate_limit()
    limiter.reset()


class StubContainer:
    """Stands in for ApplicationContainer without opening a database."""

    def __init__(self, *, embedding_client: FakeEmbeddingClient, database_healthy: bool = True) -> None:
        self.embedding_client = embedding_client
        self.discount_policy = QuantityTierDiscountPolicy()
        self.database_healthy = database_healthy

    def session_factory(self) -> "_StubSession":
        return _StubSession(healthy=self.database_healthy)


class _StubSession:
    def __init__(self, *, healthy: bool) -> None:
        self._healthy = healthy

    async def __aenter__(self) -> "_StubSession":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def execute(self, *args: object, **kwargs: object) -> None:
        if not self._healthy:
            raise OSError("database is unreachable")


@pytest.fixture
def customers() -> FakeCustomerRepository:
    return FakeCustomerRepository([make_customer("Anna Petrova"), make_customer("Marcus Feld")])


@pytest.fixture
def slots() -> FakeBookingRepository:
    return FakeBookingRepository([make_slot(capacity=4), make_slot(capacity=2)])


@pytest.fixture
def pricing() -> FakePricingRepository:
    return FakePricingRepository([make_pricing_item(), make_pricing_item("Nutrition Coaching", "95.00")])


@pytest.fixture
def knowledge() -> FakeKnowledgeRepository:
    return FakeKnowledgeRepository()


@pytest.fixture
def embedding_client() -> FakeEmbeddingClient:
    return FakeEmbeddingClient()


def build_app(
    customers: FakeCustomerRepository,
    slots: FakeBookingRepository,
    pricing: FakePricingRepository,
    knowledge: FakeKnowledgeRepository,
    embedding_client: FakeEmbeddingClient,
) -> FastAPI:
    """The real app, with only the outermost boundary (the database) replaced.

    Middleware, routing, schema validation and exception handling are all the
    production ones, so these tests exercise the wiring rather than a mock of it.
    """
    # Imported here rather than at module scope: `src.main` builds the ASGI app
    # uvicorn serves as a side effect of being imported, and that reads settings.
    # By the time this runs the environment above is in place.
    from src.main import create_app

    application = create_app()
    application.state.container = StubContainer(embedding_client=embedding_client)

    application.dependency_overrides[get_customer_service] = lambda: CustomerService(customers)
    application.dependency_overrides[get_booking_service] = lambda: BookingService(slots)
    application.dependency_overrides[get_pricing_service] = lambda: PricingService(
        pricing, QuantityTierDiscountPolicy()
    )
    application.dependency_overrides[get_knowledge_service] = lambda: KnowledgeService(knowledge, embedding_client)
    return application


@pytest.fixture
def app(
    customers: FakeCustomerRepository,
    slots: FakeBookingRepository,
    pricing: FakePricingRepository,
    knowledge: FakeKnowledgeRepository,
    embedding_client: FakeEmbeddingClient,
) -> Iterator[FastAPI]:
    application = build_app(customers, slots, pricing, knowledge, embedding_client)
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
async def client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """Authenticated by default — every /api/v1 endpoint needs the key now.

    Consumers of this API are all server-side and always hold the key, so this
    is the realistic client. Tests about rejection use `anonymous_client`.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-API-Key": TEST_API_KEY},
    ) as async_client:
        yield async_client


@pytest.fixture
async def anonymous_client(app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as async_client:
        yield async_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"X-API-Key": TEST_API_KEY}
