from collections.abc import Awaitable, Callable
from logging import getLogger
from secrets import compare_digest

from fastapi import FastAPI, Request, Response

from src.app.api.v1.exception_handlers import error_response_from_exception
from src.app.core.settings.app import get_app_settings
from src.app.exceptions.auth import UnauthorizedError

logger = getLogger(__name__)

API_KEY_HEADER = "X-API-Key"

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# OPTIONS is the CORS preflight, which a browser sends without custom headers by
# definition — demanding a key there would break CORS for every origin.
_NEVER_GUARDED_METHODS = frozenset({"OPTIONS", "HEAD"})

# Always reachable. /health is polled by the container runtime, and the schema
# endpoints have to load unauthenticated or Swagger UI cannot render at all.
# None of them expose data.
_ALWAYS_OPEN_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"})

# Semantic search is a read operation that happens to be a POST, because the
# query does not belong in a URL. A method-only rule would lock it, so it is
# listed here explicitly. It stays public but carries the stricter rate limit,
# since it is the one open endpoint that costs a call to the embedding provider.
_PUBLIC_READ_ROUTES = frozenset({("POST", "/api/v1/documents/search")})


def _requires_api_key(method: str, path: str) -> bool:
    """The single source of truth for what needs a key.

    The middleware enforces it and the OpenAPI schema is generated from it, so
    the padlock shown in Swagger cannot drift from the rule actually applied.
    """
    if method in _NEVER_GUARDED_METHODS:
        return False

    normalised = path.rstrip("/") or "/"
    if normalised in _ALWAYS_OPEN_PATHS:
        return False

    if not get_app_settings().public_reads:
        return True

    if method not in _WRITE_METHODS:
        return False
    return (method, normalised) not in _PUBLIC_READ_ROUTES


def register_api_key_middleware(app: FastAPI) -> None:
    """Guard write endpoints — or everything — with a shared secret.

    With PUBLIC_READS=true (the default) reads stay open, so the demo is
    browsable while nothing can be modified. Set it to false when the service
    is deployed as a private backend and the data is real: a key that a browser
    would have to hold is not a secret, so open reads are only defensible while
    the data is not.
    """

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not _requires_api_key(request.method, request.url.path):
            return await call_next(request)

        provided = request.headers.get(API_KEY_HEADER)
        expected = get_app_settings().api_key.get_secret_value()
        # compare_digest, not ==, so the comparison time does not leak how many
        # leading characters of a guess were right. Bytes rather than str
        # because compare_digest rejects non-ASCII strings.
        if provided is None or not compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            logger.warning("Rejected %s %s: missing or invalid API key.", request.method, request.url.path)
            # Returned, not raised: exception handlers live inside the
            # middleware stack, so a raise here would escape them and become a
            # 500. This renders the same envelope through the shared helper.
            return error_response_from_exception(UnauthorizedError())

        return await call_next(request)
