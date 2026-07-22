from logging import getLogger

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.app.schemas.health import HealthResponse

logger = getLogger(__name__)

router = APIRouter(prefix="/health", tags=["infra"])


@router.get("", response_model=HealthResponse)
async def health(request: Request) -> JSONResponse:
    """Service status plus database connectivity.

    Does not use the request-scoped session dependency: that dependency would
    raise before the handler runs when the database is unreachable, which is
    exactly the case this endpoint has to report on.
    """
    database = "ok"
    try:
        async with request.app.state.container.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        logger.warning("Health check could not reach the database: %s", exc)
        database = "unavailable"

    body = HealthResponse(status="ok" if database == "ok" else "degraded", database=database)
    return JSONResponse(status_code=200 if database == "ok" else 503, content=body.model_dump())
