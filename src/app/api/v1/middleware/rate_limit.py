import time
from collections.abc import Awaitable, Callable
from logging import getLogger

from fastapi import FastAPI, Request, Response
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.app.api.v1.exception_handlers import error_response_from_exception
from src.app.core.settings.app import get_app_settings
from src.app.exceptions.rate_limit import RateLimitExceededError

logger = getLogger(__name__)

_settings = get_app_settings()

# ponytail: in-memory counters, so limits are per process. Correct while the
# Dockerfile pins uvicorn to one worker; swap MemoryStorage for Redis storage
# if it is ever scaled out. get_remote_address also sees the proxy's IP unless
# uvicorn runs with --proxy-headers behind a trusted proxy.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{_settings.rate_limit_per_minute}/minute"],
    headers_enabled=True,
)

# Stricter allowance for the endpoints that call the embedding provider, which
# cost real money and latency per request. Applied with slowapi's decorator.
EMBEDDING_ENDPOINT_LIMIT = f"{_settings.embedding_rate_limit_per_minute}/minute"

# The global cap is enforced here rather than through SlowAPIMiddleware.
# slowapi resolves the matching route to decide whether a request is exempt,
# and it only scans the top level of app.routes. This FastAPI version wraps
# every include_router() in a private container object that matches the path
# but exposes no endpoint, so slowapi finds nothing, treats every route as
# exempt, and quietly applies no limit at all. Counting here against the
# `limits` public API keeps the cap working regardless of how FastAPI chooses
# to represent nested routers.
_global_limit = parse(f"{_settings.rate_limit_per_minute}/minute")
_global_limiter = FixedWindowRateLimiter(MemoryStorage())

# Health checks are polled by the container runtime and by the four agent
# services that depend on this one, and must never be throttled: a 429 there
# reads as "ops-core-api is down" and takes the caller out of service with it.
_EXEMPT_PATHS = frozenset({"/health/live", "/health/ready"})


def reset_global_rate_limit() -> None:
    """Drop all counters. Used by tests to keep cases independent."""
    _global_limiter.storage.reset()


def _rate_limit_headers(identifier: str, scope: str) -> dict[str, str]:
    stats = _global_limiter.get_window_stats(_global_limit, identifier, scope)
    return {
        "Retry-After": str(max(0, int(stats.reset_time - time.time()))),
        "X-RateLimit-Limit": str(_global_limit.amount),
        "X-RateLimit-Remaining": str(stats.remaining),
        "X-RateLimit-Reset": str(int(stats.reset_time)),
    }


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)

    @app.middleware("http")
    async def global_rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        identifier = get_remote_address(request)
        # Counted per path so that hammering one endpoint cannot lock a client
        # out of the whole API.
        if not _global_limiter.hit(_global_limit, identifier, path):
            logger.warning("Rate limit exceeded for %s on %s %s", identifier, request.method, path)
            headers = _rate_limit_headers(identifier, path)
            return error_response_from_exception(
                RateLimitExceededError(f"Rate limit exceeded: {_global_limit}."),
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(_rate_limit_headers(identifier, path))
        return response


async def handle_rate_limit_exceeded(request: Request, exc: Exception) -> Response:
    """Return 429 in this project's error envelope.

    slowapi's own handler emits `{"error": "Rate limit exceeded: ..."}`, which
    would be the one response shape in the API that clients have to special-case.
    """
    detail = f"Rate limit exceeded: {exc.detail}." if isinstance(exc, RateLimitExceeded) else None
    response = error_response_from_exception(RateLimitExceededError(detail))

    # Keep slowapi's Retry-After / X-RateLimit-* headers where it set them.
    view_rate_limit = getattr(request.state, "view_rate_limit", None)
    if view_rate_limit is not None:
        return limiter._inject_headers(response, view_rate_limit)  # noqa: SLF001
    return response
