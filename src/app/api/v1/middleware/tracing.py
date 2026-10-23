from typing import Any

import opentelemetry.instrumentation.fastapi as otel_fastapi

from src.app.api.v1.route_template import UNMATCHED, route_template


def _route_details(scope: dict[str, Any]) -> str | None:
    template = route_template(scope["app"], scope["path"])
    return None if template == UNMATCHED else template


def use_route_templates() -> None:
    """Name server spans and label request metrics by route template.

    NOTE: opentelemetry-instrumentation-fastapi 0.60b1 finds the route by walking `app.routes`, and
    this FastAPI nests every included router in an object with no `path`. Two symptoms follow: the
    span name and `http.route` (a metric label) become the raw path, one series per booking id, and
    a 405 or a CORS preflight raises AttributeError and answers 500. 0.60b1 is the newest release
    livekit-agents' opentelemetry-api pin allows. Drop this once an instrumentation release reads
    `scope["route"]`; `tests/unit/test_tracing.py` fails if it is dropped too early.
    """
    # setattr: the function is private to the library, which is the point of this workaround.
    setattr(otel_fastapi, "_get_route_details", _route_details)  # noqa: B010
