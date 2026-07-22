from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from src.app.api.v1.middleware.api_key import API_KEY_HEADER, _requires_api_key

SECURITY_SCHEME_NAME = "ApiKeyHeader"

_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})


def customise_openapi(app: FastAPI) -> None:
    """Advertise the API key in the schema so Swagger UI can send it.

    The key is enforced by middleware, which sits outside FastAPI's dependency
    system and is therefore invisible to the generated schema: without this,
    /docs shows no Authorize button and every write endpoint returns 401 when
    executed from the browser, with nothing on the page explaining why.

    The per-operation flags are derived from `_requires_api_key`, the same
    function the middleware calls, so the padlock in the docs always matches
    what the server actually enforces — including when PUBLIC_READS is off and
    the whole API needs a key.
    """

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[SECURITY_SCHEME_NAME] = {
            "type": "apiKey",
            "in": "header",
            "name": API_KEY_HEADER,
            "description": (
                "Shared secret for protected endpoints. Never embed it in a browser bundle: "
                "call this API from a server-side component that holds the key in its environment."
            ),
        }

        for path, operations in schema["paths"].items():
            for method, operation in operations.items():
                if method.lower() in _HTTP_METHODS and _requires_api_key(method.upper(), path):
                    operation["security"] = [{SECURITY_SCHEME_NAME: []}]
                    operation.setdefault("responses", {}).setdefault(
                        "401",
                        {"description": "Missing or invalid API key."},
                    )

        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
