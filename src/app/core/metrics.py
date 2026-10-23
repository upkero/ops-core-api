"""Business and rate-limit instruments (OBSERVABILITY-AUDIT §1.1), and the provider that exports them.

Labels are bounded sets only: never a name, an id, a path or a free-text value.
The instruments are created against the global meter, which binds to the provider
`setup_metrics` installs even though this module is imported first; until then
they record nothing, which is what a script that never sets one up wants.
"""

import os

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

_meter = metrics.get_meter("ops-core-api")

_SECONDS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
_UNIT_INTERVAL = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

rate_limited = _meter.create_counter(
    "ops.rate_limited", description="Requests answered 429, which the route's own span never sees."
)
embedding_duration = _meter.create_histogram(
    "ops.embedding.duration",
    unit="s",
    description="Embedding time, including providers that run in-process and have no HTTP span.",
    explicit_bucket_boundaries_advisory=_SECONDS,
)
bookings_created = _meter.create_counter("ops.bookings.created", description="Bookings taken, or replayed by key.")
booking_rejections = _meter.create_counter(
    "ops.booking.rejections", description="Bookings refused, by the error code the caller received."
)
booking_lookups = _meter.create_counter("ops.booking.lookups", description="Booking searches, by filter and result.")
bookings_cancelled = _meter.create_counter("ops.bookings.cancelled", description="Cancellations, by outcome.")
availability_checks = _meter.create_counter("ops.availability.checks", description="Free-slot searches, by result.")
slot_lock_wait = _meter.create_histogram(
    "ops.slot_lock.wait",
    unit="s",
    description="Time spent waiting for the row lock on a slot (FOR UPDATE).",
    explicit_bucket_boundaries_advisory=_SECONDS,
)
knowledge_searches = _meter.create_counter("ops.knowledge.search", description="Knowledge searches, by outcome.")
knowledge_top_score = _meter.create_histogram(
    "ops.knowledge.top_score",
    unit="1",
    description="Cosine similarity of the best match, to watch retrieval quality drift.",
    explicit_bucket_boundaries_advisory=_UNIT_INTERVAL,
)


def setup_metrics(resource: Resource) -> MeterProvider:
    """Install the process-wide MeterProvider, once, before the HTTP and SQL instrumentation runs.

    Same shape as `setup_tracing`: idempotent, and exporting only when a collector
    is configured (OTEL_EXPORTER_OTLP_ENDPOINT; the interval is OTEL_METRIC_EXPORT_INTERVAL).
    The tracing module is shared verbatim between services and sets up spans only.
    """
    current = metrics.get_meter_provider()
    if isinstance(current, MeterProvider):
        return current
    exporting = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    readers = [PeriodicExportingMetricReader(OTLPMetricExporter())] if exporting else []
    provider = MeterProvider(resource=resource, metric_readers=readers)
    metrics.set_meter_provider(provider)
    return provider
