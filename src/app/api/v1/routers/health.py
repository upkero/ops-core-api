from logging import getLogger

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.app.schemas.health import LivenessResponse, ReadinessResponse

logger = getLogger(__name__)

router = APIRouter(prefix="/health", tags=["infra"])


@router.get("/live", response_model=LivenessResponse)
async def liveness() -> LivenessResponse:
    """Is the process up. Nothing else.

    Split from readiness because the container HEALTHCHECK polls this one: a
    liveness probe that touches a dependency restarts a perfectly healthy
    container every time the database blinks, which is the opposite of what
    restarting is for.
    """
    return LivenessResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(request: Request) -> JSONResponse:
    """Can this process serve traffic — which here means: is the database up.

    Does not use the request-scoped session dependency: that dependency would
    raise before the handler runs when the database is unreachable, which is
    exactly the case this endpoint has to report on.

    Consumers treat 200 as ready and anything else as not, so the 503 below is
    the load-bearing part of the response; the body is for humans.
    """
    database_reachable = True
    try:
        async with request.app.state.container.session_factory() as session:
            await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError, RuntimeError) as exc:
        logger.warning("Readiness check could not reach the database: %s", exc)
        database_reachable = False

    body = ReadinessResponse(
        status="ok" if database_reachable else "degraded",
        database="ok" if database_reachable else "unavailable",
    )
    return JSONResponse(status_code=200 if database_reachable else 503, content=body.model_dump())
