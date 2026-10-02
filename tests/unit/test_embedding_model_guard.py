"""Switching embedding provider must not silently degrade search.

Vectors from two models live in different spaces. Cosine distance between them
is a perfectly computable number, so without a guard the only symptom of a
provider switch is that results quietly become irrelevant — the failure mode
that is hardest to notice in production.
"""

import pytest

from src.app.exceptions.embeddings import EmbeddingModelMismatchError
from src.app.llm.hashing_embedding_client import HashingEmbeddingClient
from src.app.services.knowledge import KnowledgeService
from tests.fakes import FakeEmbeddingClient, FakeKnowledgeRepository

CONTENT = "Appointments can be cancelled free of charge up to twenty-four hours before the start."


@pytest.fixture
def repository() -> FakeKnowledgeRepository:
    return FakeKnowledgeRepository()


def _service(repository: FakeKnowledgeRepository, model: str) -> KnowledgeService:
    return KnowledgeService(repository, FakeEmbeddingClient(model=model))


async def test_documents_record_the_model_that_embedded_them(repository: FakeKnowledgeRepository) -> None:
    await _service(repository, "v1").add_document("Policy", CONTENT)

    assert repository.documents[0].embedding_model == "fake:v1"
    assert {chunk.embedding_model for chunk in repository.chunks} == {"fake:v1"}


async def test_search_fails_loudly_after_the_model_changes(repository: FakeKnowledgeRepository) -> None:
    await _service(repository, "v1").add_document("Policy", CONTENT)

    with pytest.raises(EmbeddingModelMismatchError) as error:
        await _service(repository, "v2").search("cancel appointment", top_k=3)

    # The message has to name both sides and the remedy, or whoever hits it at
    # 3am has nothing to go on.
    detail = error.value.detail
    assert "fake:v1" in detail
    assert "fake:v2" in detail
    assert "seed --force" in detail


async def test_search_never_mixes_vector_spaces(repository: FakeKnowledgeRepository) -> None:
    await _service(repository, "v1").add_document("Old", CONTENT)
    await _service(repository, "v2").add_document("New", CONTENT)

    matches = await _service(repository, "v2").search("cancel appointment", top_k=10)

    # Both documents are present and equally relevant; only the ones from the
    # active model may be returned.
    assert [match.document_title for match in matches] == ["New"]


async def test_an_empty_knowledge_base_is_not_an_error(repository: FakeKnowledgeRepository) -> None:
    # Nothing indexed at all is a normal state, not a misconfiguration.
    assert await _service(repository, "v1").search("anything", top_k=3) == []


async def test_search_still_works_when_the_model_is_unchanged(repository: FakeKnowledgeRepository) -> None:
    service = _service(repository, "v1")
    await service.add_document("Policy", CONTENT)

    matches = await service.search("cancel appointment", top_k=3)

    assert [match.document_title for match in matches] == ["Policy"]


def test_the_local_embedder_versions_its_algorithm() -> None:
    # Changing the tokenizer or stemmer changes the vector space just as much
    # as swapping providers does, so the fingerprint carries a version.
    client = HashingEmbeddingClient(dimensions=1024)

    assert client.fingerprint == "hashing:v1"


def test_the_fingerprint_combines_provider_and_model() -> None:
    assert FakeEmbeddingClient(model="text-embedding-3-small").fingerprint == "fake:text-embedding-3-small"
