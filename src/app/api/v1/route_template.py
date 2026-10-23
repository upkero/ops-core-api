import re

from fastapi import FastAPI

UNMATCHED = "<unmatched>"


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


def route_template(app: FastAPI, path: str) -> str:
    """The template a concrete path belongs to, or UNMATCHED.

    For anything that needs a bounded name for a request: a rate-limit counter, a
    metric label, a span name. A raw path carries ids, and there is one per booking.
    """
    # Built on first use: the routers are included after the app is created.
    matchers = getattr(app.state, "route_matchers", None)
    if matchers is None:
        matchers = app.state.route_matchers = _route_matchers(app)
    return next((template for pattern, template in matchers if pattern.fullmatch(path)), UNMATCHED)
