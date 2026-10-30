"""What an embeddings response says about its own cost, and what is recorded when it says nothing."""

from types import SimpleNamespace

import pytest

from src.app.core.settings.embeddings import EmbeddingSettings
from src.app.exceptions.embeddings import EmbeddingGenerationError
from src.app.llm.openai_compatible_embedding_client import OpenAICompatibleEmbeddingClient
from tests import telemetry

DIMENSIONS = 4
LABELS = {"provider": "openai_compatible", "model": "baai/bge-m3"}


class _Embeddings:
    def __init__(self, response: SimpleNamespace) -> None:
        self._response = response

    async def create(self, **params: object) -> SimpleNamespace:
        return self._response


def _client(usage: SimpleNamespace | None) -> OpenAICompatibleEmbeddingClient:
    response = SimpleNamespace(
        data=[SimpleNamespace(index=0, embedding=[0.1] * DIMENSIONS)],
        usage=usage,
    )
    settings = EmbeddingSettings(
        provider="openai_compatible",
        model="baai/bge-m3",
        base_url="https://openrouter.ai/api/v1",
        dimensions=DIMENSIONS,
    )
    return OpenAICompatibleEmbeddingClient(settings=settings, client=SimpleNamespace(embeddings=_Embeddings(response)))


def _tokens() -> float:
    return telemetry.reading("gen_ai.client.token.usage", **{"gen_ai.operation.name": "embeddings"})


async def test_the_cost_the_provider_reports_is_recorded_like_the_llm_cost_of_the_other_services() -> None:
    cost = telemetry.reading("llm.cost", **LABELS)
    tokens = _tokens()

    await _client(SimpleNamespace(prompt_tokens=120, total_tokens=120, cost=0.0000024)).embed_batch(["text"])

    assert telemetry.reading("llm.cost", **LABELS) - cost == pytest.approx(0.0000024)
    assert _tokens() - tokens == 1  # one histogram sample, of 120 tokens


async def test_a_response_without_a_cost_records_the_tokens_only() -> None:
    cost = telemetry.reading("llm.cost")
    tokens = _tokens()

    await _client(SimpleNamespace(prompt_tokens=120, total_tokens=120)).embed_batch(["text"])

    assert telemetry.reading("llm.cost") == cost
    assert _tokens() - tokens == 1


async def test_a_response_without_usage_records_nothing_and_still_returns_the_vectors() -> None:
    cost = telemetry.reading("llm.cost")
    tokens = _tokens()

    vectors = await _client(None).embed_batch(["text"])

    assert len(vectors) == 1
    assert telemetry.reading("llm.cost") == cost
    assert _tokens() == tokens


async def test_the_spend_of_a_response_that_is_then_rejected_is_still_recorded() -> None:
    cost = telemetry.reading("llm.cost", **LABELS)
    client = _client(SimpleNamespace(prompt_tokens=5, total_tokens=5, cost=0.1))

    with pytest.raises(EmbeddingGenerationError):
        await client.embed_batch(["one", "two"])

    assert telemetry.reading("llm.cost", **LABELS) - cost == pytest.approx(0.1)
