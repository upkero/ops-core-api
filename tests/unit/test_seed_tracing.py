"""The seed command is a process of its own, so it is its own trace root."""

import sys

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider

from src.app.cli import seed
from tests import telemetry


def test_the_seed_run_is_a_root_span_and_is_flushed_before_the_process_exits(
    monkeypatch: pytest.MonkeyPatch, spans: None
) -> None:
    ran: list[bool] = []
    flushed: list[int] = []

    async def fake_seed(*, force: bool) -> None:
        ran.append(force)

    def fake_flush(timeout_millis: int) -> bool:
        flushed.append(timeout_millis)
        return True

    provider = trace.get_tracer_provider()
    assert isinstance(provider, TracerProvider)
    monkeypatch.setattr(provider, "force_flush", fake_flush)
    monkeypatch.setattr(seed, "seed", fake_seed)
    monkeypatch.setattr(sys, "argv", ["seed", "--force"])

    seed.main()

    assert ran == [True]
    assert flushed == [5000]
    (span,) = [span for span in telemetry.finished_spans() if span.name == "seed.run"]
    assert (span.attributes or {})["seed.force"] is True
    assert span.parent is None
