"""Documents left without chunks (migration 0007 drops them) are re-embedded in place."""

from datetime import UTC, datetime
from uuid import uuid4

from src.app.contracts.knowledge import DocumentDTO
from src.app.services.knowledge import KnowledgeService
from tests.fakes import FakeEmbeddingClient, FakeKnowledgeRepository

CONTENT = "Appointments can be cancelled free of charge up to twenty-four hours before the start."


def _unindexed(title: str) -> DocumentDTO:
    return DocumentDTO(id=uuid4(), title=title, content=CONTENT, chunk_count=0, created_at=datetime.now(UTC))


async def test_documents_without_chunks_get_indexed_and_become_searchable() -> None:
    repository, embedder = FakeKnowledgeRepository(), FakeEmbeddingClient()
    repository.unindexed = [_unindexed("Cancellation policy"), _unindexed("Parking")]
    service = KnowledgeService(repository, embedder)

    assert await service.reindex_unindexed_documents() == 2

    assert repository.unindexed == []
    assert {chunk.document_title for chunk in repository.chunks} == {"Cancellation policy", "Parking"}
    assert {chunk.embedding_model for chunk in repository.chunks} == {embedder.fingerprint}
    assert await service.search("cancel", top_k=5)


async def test_nothing_to_do_makes_no_provider_call() -> None:
    embedder = FakeEmbeddingClient()

    assert await KnowledgeService(FakeKnowledgeRepository(), embedder).reindex_unindexed_documents() == 0

    assert embedder.batches == []
