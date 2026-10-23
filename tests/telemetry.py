"""In-memory sinks for the spans and metrics the code under test emits.

Importing this installs both providers, so it has to happen before the first
`create_app()`: setup_tracing and setup_metrics keep a provider that is already
there. Metrics are cumulative for the whole run, so a test reads `reading()` before
and after, never an absolute value.
"""

from typing import Any

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.app.core.telemetry import setup_tracing

_reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[_reader]))
_exporter = InMemorySpanExporter()
setup_tracing("ops-core-api", "ops-core-api").add_span_processor(SimpleSpanProcessor(_exporter))


def reading(name: str, **attributes: Any) -> float:
    """Sum of a counter (or the sample count of a histogram) over the points carrying these attributes."""
    data = _reader.get_metrics_data()
    total = 0.0
    for resource in data.resource_metrics if data else []:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if metric.name != name:
                    continue
                for point in metric.data.data_points:
                    if attributes.items() <= dict(point.attributes or {}).items():
                        total += float(getattr(point, "value", None) or getattr(point, "count", 0) or 0)
    return total


def finished_spans() -> list[ReadableSpan]:
    return list(_exporter.get_finished_spans())


def clear_spans() -> None:
    _exporter.clear()
