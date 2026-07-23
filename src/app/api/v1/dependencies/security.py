from secrets import compare_digest
from typing import Annotated

from fastapi import Security
from fastapi.security import APIKeyHeader

from src.app.core.settings.app import get_app_settings
from src.app.exceptions.auth import UnauthorizedError

API_KEY_HEADER = "X-API-Key"

# auto_error=False so a missing key reaches the check below and is reported
# through this project's error envelope, instead of FastAPI's own 403 shape.
api_key_scheme = APIKeyHeader(
    name=API_KEY_HEADER,
    auto_error=False,
    description=(
        "Shared secret for the whole API. Never embed it in a browser bundle: call this API from a "
        "server-side component that holds the key in its environment."
    ),
)


async def require_api_key(provided: Annotated[str | None, Security(api_key_scheme)]) -> None:
    """Guard every endpoint under /api/v1.

    A dependency rather than middleware: dependencies run inside Starlette's
    exception middleware, so raising here reaches the registered handlers and
    produces the normal error envelope. Declaring it with Security() also puts
    the scheme into the OpenAPI document automatically, which is what gives
    Swagger its Authorize button — no hand-written schema patching.
    """
    expected = get_app_settings().api_key.get_secret_value()
    # compare_digest, not ==, so the comparison time does not leak how many
    # leading characters of a guess were right. Bytes rather than str because
    # compare_digest rejects non-ASCII strings.
    if provided is None or not compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        raise UnauthorizedError()
