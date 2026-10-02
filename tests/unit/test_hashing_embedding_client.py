import math

import pytest

from src.app.contracts.knowledge import EMBEDDING_DIMENSIONS
from src.app.core.settings.embeddings import EmbeddingSettings
from src.app.exceptions.embeddings import EmbeddingConfigurationError, EmbeddingInputError
from src.app.llm.embedding_factory import create_embedding_client
from src.app.llm.hashing_embedding_client import HashingEmbeddingClient
from src.app.llm.openai_compatible_embedding_client import OpenAICompatibleEmbeddingClient


@pytest.fixture
def client() -> HashingEmbeddingClient:
    return HashingEmbeddingClient(dimensions=EMBEDDING_DIMENSIONS)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


async def test_embedding_is_deterministic(client: HashingEmbeddingClient) -> None:
    assert await client.embed_query("cancellation policy") == await client.embed_query("cancellation policy")


async def test_embedding_is_unit_length(client: HashingEmbeddingClient) -> None:
    vector = await client.embed_query("deep tissue massage")

    assert math.isclose(math.sqrt(sum(value**2 for value in vector)), 1.0, rel_tol=1e-9)
    assert len(vector) == EMBEDDING_DIMENSIONS


async def test_text_without_usable_tokens_is_still_a_finite_vector(client: HashingEmbeddingClient) -> None:
    # A zero vector would make pgvector's cosine distance NaN and silently
    # corrupt the ranking instead of failing.
    vector = await client.embed_query("!!! ???")

    assert math.isclose(math.sqrt(sum(value**2 for value in vector)), 1.0, rel_tol=1e-9)


async def test_inflected_forms_match_their_root(client: HashingEmbeddingClient) -> None:
    query = list(await client.embed_query("cancel appointment"))
    related = list(await client.embed_query("cancelled appointments"))
    unrelated = list(await client.embed_query("underground parking garage"))

    assert _cosine(query, related) > _cosine(query, unrelated)


async def test_related_text_scores_above_unrelated_text(client: HashingEmbeddingClient) -> None:
    query = list(await client.embed_query("how do I cancel my appointment"))
    policy = list(
        await client.embed_query(
            "Appointments can be cancelled or rescheduled free of charge up to twenty-four hours before."
        )
    )
    parking = list(await client.embed_query("Parking is available in the underground garage beneath the building."))

    assert _cosine(query, policy) > _cosine(query, parking)


@pytest.mark.parametrize("text", ["", "   "])
async def test_empty_text_is_rejected(client: HashingEmbeddingClient, text: str) -> None:
    with pytest.raises(EmbeddingInputError):
        await client.embed_query(text)


async def test_empty_batch_is_rejected(client: HashingEmbeddingClient) -> None:
    with pytest.raises(EmbeddingInputError):
        await client.embed_batch([])


async def test_batch_matches_individual_embeddings(client: HashingEmbeddingClient) -> None:
    texts = ["first text", "second text"]

    batch = await client.embed_batch(texts)

    assert [list(vector) for vector in batch] == [list(await client.embed_query(text)) for text in texts]


def test_factory_returns_the_local_client_by_default() -> None:
    client = create_embedding_client(EmbeddingSettings())

    assert isinstance(client, HashingEmbeddingClient)
    assert client.provider_name == "hashing"


def test_factory_returns_the_provider_adapter_when_configured() -> None:
    client = create_embedding_client(EmbeddingSettings(provider="openai", api_key="sk-not-a-real-key"))

    assert isinstance(client, OpenAICompatibleEmbeddingClient)


def test_factory_rejects_a_dimension_mismatch_with_the_schema() -> None:
    # Caught at startup instead of as an opaque database error on first insert.
    with pytest.raises(EmbeddingConfigurationError):
        create_embedding_client(EmbeddingSettings(dimensions=768))


def test_settings_require_an_api_key_for_the_openai_provider() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        EmbeddingSettings(provider="openai", api_key=None)


def test_settings_require_a_base_url_for_a_compatible_provider() -> None:
    with pytest.raises(ValueError, match="base_url is required"):
        EmbeddingSettings(_env_file=None, provider="openai_compatible")


def test_local_provider_needs_no_key_or_url() -> None:
    settings = EmbeddingSettings(_env_file=None, provider="local", model="BAAI/bge-m3")

    assert settings.provider == "local"
