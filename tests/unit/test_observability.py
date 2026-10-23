"""What an incident is read from: the counters, the spans and the log lines of the business paths.

Each case drives the real service over the in-memory repositories, and the telemetry
lands in the in-memory sinks of `tests/telemetry.py`. A name the guest gave must
appear in none of them; its fingerprint must appear in all.
"""

import logging
from uuid import uuid4

import pytest

from src.app.api.v1.middleware.rate_limit import _network_of
from src.app.contracts.enums import ResourceType
from src.app.contracts.pagination import PaginationParams
from src.app.core.logging import _RequestIdFilter
from src.app.core.telemetry import guest_name_fp
from src.app.exceptions.domain import EntityNotFoundError, SlotUnavailableError
from src.app.exceptions.embeddings import EmbeddingModelMismatchError
from src.app.services.booking import BookingService
from src.app.services.knowledge import KnowledgeService
from tests import telemetry
from tests.fakes import FakeBookingRepository, FakeEmbeddingClient, FakeKnowledgeRepository, make_slot

GUEST = "Иванова"
PARAMS = PaginationParams()


@pytest.fixture(autouse=True)
def _fingerprint_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBS_FINGERPRINT_KEY", "test-fingerprint-key")


@pytest.fixture
def info_logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO)
    return caplog


def events(caplog: pytest.LogCaptureFixture, event: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.__dict__.get("event") == event]


def attributes_of(name: str) -> dict[str, object]:
    span = next(span for span in telemetry.finished_spans() if span.name == name)
    return dict(span.attributes or {})


def never_in_telemetry(secret: str) -> None:
    for span in telemetry.finished_spans():
        assert secret not in str(span.attributes), span.name
        assert secret not in [event.name for event in span.events]


async def test_a_lookup_that_finds_nothing_is_counted_and_never_names_the_guest(
    spans: None, info_logs: pytest.LogCaptureFixture
) -> None:
    service = BookingService(FakeBookingRepository([make_slot()]))
    before = telemetry.reading("ops.booking.lookups", by="name", result="not_found")

    page = await service.find_bookings(GUEST, None, None, PARAMS)

    assert page.total == 0
    assert telemetry.reading("ops.booking.lookups", by="name", result="not_found") == before + 1
    span = attributes_of("booking.find")
    assert span["ops.lookup.by"] == "name"
    assert span["ops.results.count"] == 0
    assert span["booking.guest_name_fp"] == guest_name_fp(GUEST) != ""
    never_in_telemetry(GUEST)
    (record,) = events(info_logs, "booking.lookup")
    assert record.__dict__["result"] == "not_found"
    assert record.__dict__["guest_name_fp"] == guest_name_fp(GUEST)
    assert GUEST not in str(record.__dict__) + record.getMessage()


async def test_a_booking_and_the_lookup_for_it_share_a_fingerprint(
    spans: None, info_logs: pytest.LogCaptureFixture
) -> None:
    # The F6 question: did the guest give the same name at booking and at lookup?
    slot = make_slot()
    service = BookingService(FakeBookingRepository([slot]))

    await service.create_booking(GUEST, slot.id, party_size=2)
    await service.find_bookings("иванова", None, None, PARAMS)
    await service.find_bookings("Иванову", None, None, PARAMS)

    (created,) = events(info_logs, "booking.created")
    same, different = events(info_logs, "booking.lookup")
    assert created.__dict__["guest_name_fp"] == same.__dict__["guest_name_fp"] != ""
    assert different.__dict__["guest_name_fp"] != created.__dict__["guest_name_fp"]
    never_in_telemetry(GUEST)
    assert all("Иванов" not in str(record.__dict__) for record in info_logs.records)


@pytest.mark.parametrize(
    ("guest", "on_date", "by"),
    [(GUEST, True, "name_date"), (GUEST, False, "name"), (None, True, "date"), (None, False, "none")],
)
async def test_a_lookup_says_which_filters_it_used(guest: str | None, on_date: bool, by: str) -> None:
    slot = make_slot()
    service = BookingService(FakeBookingRepository([slot]))
    before = telemetry.reading("ops.booking.lookups", by=by)

    await service.find_bookings(guest, slot.slot_date if on_date else None, None, PARAMS)

    assert telemetry.reading("ops.booking.lookups", by=by) == before + 1


async def test_a_new_booking_and_a_replay_are_counted_apart(spans: None) -> None:
    slot = make_slot()
    service = BookingService(FakeBookingRepository([slot]))
    new = telemetry.reading("ops.bookings.created", resource_type="table", idempotent="new")
    replayed = telemetry.reading("ops.bookings.created", idempotent="replayed")

    await service.create_booking(GUEST, slot.id, party_size=2, idempotency_key="key-1")
    await service.create_booking(GUEST, slot.id, party_size=2, idempotency_key="key-1")

    assert telemetry.reading("ops.bookings.created", resource_type="table", idempotent="new") == new + 1
    assert telemetry.reading("ops.bookings.created", idempotent="replayed") == replayed + 1
    outcomes = [
        (span.attributes or {})["ops.idempotent_replay"]
        for span in telemetry.finished_spans()
        if span.name == "booking.create"
    ]
    assert outcomes == [False, True]


async def test_a_rejected_booking_is_counted_by_the_code_the_caller_got(
    spans: None, info_logs: pytest.LogCaptureFixture
) -> None:
    slot = make_slot(is_available=False)
    service = BookingService(FakeBookingRepository([slot]))
    before = telemetry.reading("ops.booking.rejections", reason="slot_unavailable")

    with pytest.raises(SlotUnavailableError):
        await service.create_booking(GUEST, slot.id, party_size=2)

    assert telemetry.reading("ops.booking.rejections", reason="slot_unavailable") == before + 1
    assert attributes_of("booking.create")["ops.outcome"] == "slot_unavailable"
    (record,) = events(info_logs, "booking.rejected")
    assert record.__dict__["reason"] == "slot_unavailable"
    assert record.__dict__["slot_id"] == str(slot.id)
    never_in_telemetry(GUEST)


async def test_each_way_a_cancellation_ends_is_counted(spans: None) -> None:
    slot = make_slot()
    service = BookingService(FakeBookingRepository([slot]))
    booking = await service.create_booking(GUEST, slot.id, party_size=2)
    counts = {
        outcome: telemetry.reading("ops.bookings.cancelled", outcome=outcome)
        for outcome in ("cancelled", "already_cancelled", "not_found")
    }

    await service.cancel_booking(booking.id)
    await service.cancel_booking(booking.id)
    with pytest.raises(EntityNotFoundError):
        await service.cancel_booking(uuid4())

    for outcome, before in counts.items():
        assert telemetry.reading("ops.bookings.cancelled", outcome=outcome) == before + 1, outcome


async def test_an_availability_check_says_whether_it_found_anything(spans: None) -> None:
    service = BookingService(FakeBookingRepository([make_slot(resource_type=ResourceType.TABLE)]))
    slots = telemetry.reading("ops.availability.checks", resource_type="table", result="slots")
    empty = telemetry.reading("ops.availability.checks", resource_type="treatment_room", result="empty")

    await service.list_available_slots(None, ResourceType.TABLE, PARAMS)
    await service.list_available_slots(None, ResourceType.TREATMENT_ROOM, PARAMS)

    assert telemetry.reading("ops.availability.checks", resource_type="table", result="slots") == slots + 1
    assert telemetry.reading("ops.availability.checks", resource_type="treatment_room", result="empty") == empty + 1
    assert attributes_of("booking.check_availability")["ops.slots.returned"] == 1


async def test_a_search_is_counted_timed_and_never_carries_the_query(spans: None) -> None:
    repository = FakeKnowledgeRepository()
    embeddings = FakeEmbeddingClient()
    service = KnowledgeService(repository, embeddings)
    await service.add_document("Cancellation policy", "Cancel up to 24 hours ahead for a full refund.")
    hits = telemetry.reading("ops.knowledge.search", outcome="hits")
    embedded = telemetry.reading("ops.embedding.duration", operation="query", outcome="ok")
    scored = telemetry.reading("ops.knowledge.top_score")

    matches = await service.search("secret-query-text", top_k=3)

    assert matches
    assert telemetry.reading("ops.knowledge.search", outcome="hits") == hits + 1
    assert telemetry.reading("ops.embedding.duration", operation="query", outcome="ok") == embedded + 1
    assert telemetry.reading("ops.knowledge.top_score") == scored + 1
    search = attributes_of("knowledge.search")
    assert search["ops.query.length"] == len("secret-query-text")
    assert search["ops.matches.count"] == len(matches)
    embed = next(span for span in telemetry.finished_spans() if span.name == "embedding.embed")
    assert (embed.attributes or {})["gen_ai.provider.name"] == embeddings.provider_name
    never_in_telemetry("secret-query-text")


async def test_a_search_against_another_models_vectors_is_counted_as_a_mismatch(spans: None) -> None:
    repository = FakeKnowledgeRepository()
    await KnowledgeService(repository, FakeEmbeddingClient()).add_document("Policy", "Cancel up to 24 hours ahead.")
    other = FakeEmbeddingClient()
    other.model = "some-other-model"
    before = telemetry.reading("ops.knowledge.search", outcome="model_mismatch")

    with pytest.raises(EmbeddingModelMismatchError):
        await KnowledgeService(repository, other).search("cancel", top_k=3)

    assert telemetry.reading("ops.knowledge.search", outcome="model_mismatch") == before + 1


def test_log_lines_carry_the_trace_they_were_written_in() -> None:
    from opentelemetry import trace

    record = logging.LogRecord("t", logging.INFO, "", 0, "m", (), None)
    with trace.get_tracer(__name__).start_as_current_span("outer") as span:
        _RequestIdFilter().filter(record)

    assert record.__dict__["trace_id"] == format(span.get_span_context().trace_id, "032x")
    assert record.__dict__["span_id"] == format(span.get_span_context().span_id, "016x")

    outside = logging.LogRecord("t", logging.INFO, "", 0, "m", (), None)
    _RequestIdFilter().filter(outside)
    assert outside.__dict__["trace_id"] == outside.__dict__["span_id"] == ""


def test_guest_name_fp_matches_across_case_and_spacing_and_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert guest_name_fp("  Иванова ") == guest_name_fp("ИВАНОВА")
    assert guest_name_fp("Иванова") != guest_name_fp("Иванову")
    assert len(guest_name_fp("Иванова")) == 12

    monkeypatch.delenv("OBS_FINGERPRINT_KEY")
    assert guest_name_fp("Иванова") == ""


@pytest.mark.parametrize(
    ("address", "network"),
    [
        ("203.0.113.77", "203.0.113.0/24"),
        ("2001:db8:1234:5678::1", "2001:db8:1234::/48"),
        ("testclient", "unknown"),
    ],
)
def test_a_logged_address_is_its_network_not_the_visitor(address: str, network: str) -> None:
    assert _network_of(address) == network

