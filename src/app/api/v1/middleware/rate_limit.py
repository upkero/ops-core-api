import re
import time
from collections.abc import Awaitable, Callable
from logging import getLogger

from fastapi import FastAPI, Request, Response
from limits import RateLimitItem, parse
from limits.storage import MemoryStorage
from limits.strategies import FixedWindowRateLimiter
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.app.api.v1.exception_handlers import error_response_from_exception
from src.app.core.settings.app import get_app_settings
from src.app.exceptions.rate_limit import RateLimitExceededError

logger = getLogger(__name__)

# NOTE: in-memory counters, so limits are per process. Correct while the
# Dockerfile pins uvicorn to one worker; swap MemoryStorage for Redis storage
# if it is ever scaled out. get_remote_address also sees the proxy's IP unless
# uvicorn runs with --proxy-headers behind a trusted proxy.


def global_limit() -> str:
    return f"{get_app_settings().rate_limit_per_minute}/minute"


def embedding_endpoint_limit() -> str:
    """Stricter allowance for the endpoints that call the embedding provider,
    which cost real money and latency per request. Applied with slowapi's
    decorator."""
    return f"{get_app_settings().embedding_rate_limit_per_minute}/minute"


# Both limits are passed to slowapi as callables rather than formatted strings.
# slowapi resolves a callable per request, which is what keeps this module free
# of settings at import time: a decorator argument is evaluated when the module
# is imported, so a literal here would read the environment before a test (or
# anything else) has had a chance to arrange it.
limiter = Limiter(key_func=get_remote_address, default_limits=[global_limit], headers_enabled=True)

# The global cap is enforced here rather than through SlowAPIMiddleware.
# slowapi resolves the matching route to decide whether a request is exempt,
# and it only scans the top level of app.routes. This FastAPI version wraps
# every include_router() in a private container object that matches the path
# but exposes no endpoint, so slowapi finds nothing, treats every route as
# exempt, and quietly applies no limit at all. Counting here against the
# `limits` public API keeps the cap working regardless of how FastAPI chooses
# to represent nested routers.
_global_limiter = FixedWindowRateLimiter(MemoryStorage())

# Health checks are polled by the container runtime and by the four agent
# services that depend on this one, and must never be throttled: a 429 there
# reads as "ops-core-api is down" and takes the caller out of service with it.
_EXEMPT_PATHS = frozenset({"/health/live", "/health/ready"})


# Every path that matches no route shares this one counter, so junk URLs can neither
# dodge the limit nor make the counters grow without bound.
_UNMATCHED = "<unmatched>"


def _route_matchers(app: FastAPI) -> list[tuple[re.Pattern[str], str]]:
    """(regex, template) for every documented route, e.g. `/api/v1/bookings/{booking_id}`.

    Built from the OpenAPI document rather than from `app.routes`: the routing
    objects are private to FastAPI and nested, while the document is the public,
    flattened list of the same templates. Fewest parameters first, so a literal
    segment (`/pricing/services`) wins over a parameterised sibling.
    """
    templates = sorted(app.openapi()["paths"], key=lambda template: template.count("{"))
    return [
        (
            re.compile(
                "".join(
                    "[^/]+" if part.startswith("{") else re.escape(part) for part in re.split(r"(\{[^}]+\})", template)
                )
            ),
            template,
        )
        for template in templates
    ]


def reset_global_rate_limit() -> None:
    """Drop all counters. Used by tests to keep cases independent."""
    _global_limiter.storage.reset()


def _rate_limit_headers(limit: RateLimitItem, identifier: str, scope: str, *, rejected: bool) -> dict[str, str]:
    stats = _global_limiter.get_window_stats(limit, identifier, scope)
    headers = {
        "X-RateLimit-Limit": str(limit.amount),
        "X-RateLimit-Remaining": str(stats.remaining),
        "X-RateLimit-Reset": str(int(stats.reset_time)),
    }
    if rejected:
        # Only a 429 tells the client to wait; on a success it would read as a back-off request.
        headers["Retry-After"] = str(max(0, int(stats.reset_time - time.time())))
    return headers


def register_rate_limiting(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, handle_rate_limit_exceeded)

    # Settings are read here, at application build time, rather than at module
    # import: importing this module must not depend on a configured environment.
    limit = parse(global_limit())
    matchers: list[tuple[re.Pattern[str], str]] = []

    def route_template(path: str) -> str:
        # Built on first use: the routers are included after this function runs.
        if not matchers:
            matchers.extend(_route_matchers(app))
        return next((template for pattern, template in matchers if pattern.fullmatch(path)), _UNMATCHED)

    @app.middleware("http")
    async def global_rate_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path in _EXEMPT_PATHS:
            return await call_next(request)

        identifier = get_remote_address(request)
        # Counted per route template, not per concrete path: hammering one endpoint
        # must not lock a client out of the whole API, and /bookings/{id} must not
        # get a fresh allowance for every id.
        scope = route_template(path)
        if not _global_limiter.hit(limit, identifier, scope):
            logger.warning("Rate limit exceeded for %s on %s %s", identifier, request.method, path)
            headers = _rate_limit_headers(limit, identifier, scope, rejected=True)
            return error_response_from_exception(
                RateLimitExceededError(f"Rate limit exceeded: {limit}."),
                headers=headers,
            )

        response = await call_next(request)
        # The embedding endpoints are also capped by their own, tighter slowapi limit, which has
        # already put its figures on the response. Those are the ones the client must pace itself on.
        for name, value in _rate_limit_headers(limit, identifier, scope, rejected=False).items():
            response.headers.setdefault(name, value)
        if response.status_code != 429:
            del response.headers["Retry-After"]
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
