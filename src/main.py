from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.api.v1.exception_handlers import register_exception_handlers
from src.app.api.v1.middleware.request_id import register_request_id_middleware
from src.app.api.v1.router import api_router
from src.app.api.v1.routers.health import router as health_router
from src.app.bootstrap.container import ApplicationContainer
from src.app.core.logging import setup_logging
from src.app.core.settings.app import get_app_settings
from src.app.core.settings.logging import get_logging_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    container = ApplicationContainer()
    app.state.container = container
    try:
        yield
    finally:
        await container.close()


def create_app() -> FastAPI:
    setup_logging(get_logging_settings())

    app = FastAPI(title="Ops Core API", version="0.1.0", lifespan=lifespan)

    settings = get_app_settings()
    # Starlette runs middleware in reverse registration order, so CORS registered
    # first ends up outermost: error responses produced by inner middleware still
    # carry CORS headers instead of surfacing as opaque failures in the browser.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
    )

    register_request_id_middleware(app)
    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
