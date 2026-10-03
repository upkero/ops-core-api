"""What migration 0007 leaves behind (documents without chunks) is repaired on start."""

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.cli.seed import reindex_unindexed_documents
from src.app.contracts.knowledge import EMBEDDING_DIMENSIONS
from src.app.llm.hashing_embedding_client import HashingEmbeddingClient
from src.app.models.knowledge import DocumentChunk
from src.app.repositories.knowledge import SqlAlchemyKnowledgeRepository
from src.app.services.knowledge import KnowledgeService

CONTENT = "Appointments can be cancelled free of charge up to twenty-four hours before the start time."


@pytest.fixture
def embedder() -> HashingEmbeddingClient:
    return HashingEmbeddingClient(dimensions=EMBEDDING_DIMENSIONS)


async def test_documents_emptied_by_the_migration_are_searchable_again(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    repository = SqlAlchemyKnowledgeRepository(session)
    original = await KnowledgeService(repository, embedder).add_document("Cancellation policy", CONTENT)
    await session.execute(delete(DocumentChunk))  # what 0007 does
    assert [d.id for d in await repository.list_unindexed_documents()] == [original.id]

    assert await reindex_unindexed_documents(session, lambda: embedder) == 1

    assert await repository.list_unindexed_documents() == []
    matches = await KnowledgeService(repository, embedder).search("cancel my appointment", top_k=3)
    assert matches
    assert {match.document_id for match in matches} == {original.id}


async def test_an_indexed_database_is_left_alone_and_builds_no_client(
    session: AsyncSession,
    embedder: HashingEmbeddingClient,
) -> None:
    await KnowledgeService(SqlAlchemyKnowledgeRepository(session), embedder).add_document("Policy", CONTENT)
    before = await session.scalar(select(func.count()).select_from(DocumentChunk))

    def no_client() -> HashingEmbeddingClient:
        raise AssertionError("the embedding client must not be built when nothing needs re-indexing")

    assert await reindex_unindexed_documents(session, no_client) == 0
    assert await session.scalar(select(func.count()).select_from(DocumentChunk)) == before
