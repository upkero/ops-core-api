from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from src.app.api.v1.exception_handlers import register_exception_handlers
from src.app.api.v1.middleware.rate_limit import register_rate_limiting
from src.app.api.v1.middleware.request_id import register_request_id_middleware
from src.app.api.v1.middleware.tracing import use_route_templates
from src.app.api.v1.router import api_router
from src.app.api.v1.routers.health import router as health_router
from src.app.bootstrap.container import ApplicationContainer
from src.app.core.logging import setup_logging
from src.app.core.metrics import setup_metrics
from src.app.core.settings.app import get_app_settings
from src.app.core.settings.logging import get_logging_settings
from src.app.core.settings.security import get_security_settings
from src.app.core.telemetry import instrument_app, setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    container = ApplicationContainer()
    app.state.container = container
    try:
        # The container is lazy; build the graph the requests use now, so a
        # misconfiguration fails the boot instead of the first request.
        _ = container.embedding_client, container.session_factory
        yield
    finally:
        await container.close()


def create_app() -> FastAPI:
    setup_logging(get_logging_settings())
    # Providers first: the instrumentations below read the global ones when they attach.
    setup_metrics(setup_tracing("ops-core-api", "ops-core-api").resource)
    # The OpenAI SDK's own httpx client, when an embedding provider is configured.
    httpx_instrumentor = HTTPXClientInstrumentor()
    if not httpx_instrumentor.is_instrumented_by_opentelemetry:  # the app factory runs once per test
        httpx_instrumentor.instrument()

    app = FastAPI(title="Ops Core API", version="0.1.0", lifespan=lifespan)

    settings = get_app_settings()
    get_security_settings()  # a missing or short SECURITY_API_KEY fails the boot, not the first request

    # Middleware is registered inside-out: Starlette prepends each one, so the
    # LAST registered runs FIRST. The order below produces the runtime chain
    #     CORS -> request_id -> rate_limit -> routes
    # which matters because the rate limit middleware short-circuits with 429.
    # That response has to travel back out through request_id and CORS, or the
    # rejection reaches the browser without CORS headers (shown as an opaque
    # network error rather than a real status) and without a request id in the
    # logs. The API key is a route dependency, not middleware, so it needs no
    # place in this ordering.
    register_rate_limiting(app)
    register_request_id_middleware(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    # Last, so the server span is the outermost layer: it also wraps the rate-limit middleware,
    # and a 429 is a span like any other response.
    use_route_templates()
    instrument_app(app)
    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
