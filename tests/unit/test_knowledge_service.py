import math

import pytest

from src.app.exceptions.embeddings import EmbeddingInputError
from src.app.services.knowledge import KnowledgeService
from tests.fakes import FakeEmbeddingClient, FakeKnowledgeRepository

LONG_DOCUMENT = "\n\n".join(
    [
        "Appointments can be cancelled free of charge up to twenty-four hours before the start. " * 3,
        "Cancellations inside that window are charged at fifty percent of the price. " * 3,
        "We waive the fee for illness, bereavement and travel disruption. " * 3,
    ]
)


@pytest.fixture
def repository() -> FakeKnowledgeRepository:
    return FakeKnowledgeRepository()


@pytest.fixture
def embedding_client() -> FakeEmbeddingClient:
    return FakeEmbeddingClient()


@pytest.fixture
def service(repository: FakeKnowledgeRepository, embedding_client: FakeEmbeddingClient) -> KnowledgeService:
    return KnowledgeService(repository, embedding_client)


async def test_add_document_chunks_and_embeds(
    service: KnowledgeService,
    repository: FakeKnowledgeRepository,
    embedding_client: FakeEmbeddingClient,
) -> None:
    document = await service.add_document("Cancellation policy", LONG_DOCUMENT)

    assert document.chunk_count > 1
    stored = repository.documents[0]
    assert len(stored.chunks) == document.chunk_count
    # One batched provider call for the whole document, not one per chunk.
    assert len(embedding_client.batches) == 1
    assert len(embedding_client.batches[0]) == document.chunk_count


async def test_chunk_indexes_are_sequential(service: KnowledgeService, repository: FakeKnowledgeRepository) -> None:
    await service.add_document("Cancellation policy", LONG_DOCUMENT)

    indexes = [chunk.chunk_index for chunk in repository.documents[0].chunks]
    assert indexes == list(range(len(indexes)))


async def test_every_chunk_gets_its_own_embedding(
    service: KnowledgeService,
    repository: FakeKnowledgeRepository,
) -> None:
    await service.add_document("Cancellation policy", LONG_DOCUMENT)

    chunks = repository.documents[0].chunks
    assert all(len(chunk.embedding) == 8 for chunk in chunks)


async def test_document_embedding_is_a_unit_length_centroid(
    service: KnowledgeService,
    repository: FakeKnowledgeRepository,
) -> None:
    await service.add_document("Cancellation policy", LONG_DOCUMENT)

    embedding = repository.documents[0].embedding
    assert embedding is not None
    # Re-normalised, so it is comparable with chunk vectors under cosine distance.
    assert math.isclose(math.sqrt(sum(value**2 for value in embedding)), 1.0, rel_tol=1e-9)


async def test_search_embeds_the_query_and_returns_ranked_matches(
    service: KnowledgeService,
    embedding_client: FakeEmbeddingClient,
) -> None:
    await service.add_document("Cancellation", "Cancel your appointment online at any time.")
    await service.add_document("Parking", "Parking is free in the underground garage for two hours.")

    matches = await service.search("cancel appointment", top_k=2)

    assert embedding_client.queries == ["cancel appointment"]
    assert matches[0].document_title == "Cancellation"
    # Ordered by relevance, best first.
    assert matches[0].score >= matches[1].score


async def test_search_caps_top_k(service: KnowledgeService) -> None:
    await service.add_document("Doc", "Some content about appointments and parking.")

    assert len(await service.search("appointments", top_k=10_000)) <= 50


@pytest.mark.parametrize("query", ["", "   "])
async def test_search_rejects_an_empty_query(service: KnowledgeService, query: str) -> None:
    with pytest.raises(EmbeddingInputError):
        await service.search(query, top_k=5)


async def test_add_document_rejects_content_with_no_usable_text(service: KnowledgeService) -> None:
    with pytest.raises(EmbeddingInputError):
        await service.add_document("Empty", "   \n\n  ")
