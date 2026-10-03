import math
from collections.abc import Sequence

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewChunk, NewDocument
from src.app.exceptions.embeddings import EmbeddingInputError, EmbeddingModelMismatchError
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.interfaces.repositories.knowledge_repository import KnowledgeRepository
from src.app.services.knowledge.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, chunk_text

MAX_TOP_K = 50


class KnowledgeService:
    """Ingests documents and answers semantic queries.

    Chunking and embedding happen here, on write, so a search is a single
    vector query with no model call per stored chunk.
    """

    def __init__(
        self,
        repository: KnowledgeRepository,
        embedding_client: EmbeddingClient,
        *,
        max_chunk_chars: int = DEFAULT_MAX_CHARS,
        chunk_overlap: int = DEFAULT_OVERLAP,
    ) -> None:
        self._repository = repository
        self._embedding_client = embedding_client
        self._max_chunk_chars = max_chunk_chars
        self._chunk_overlap = chunk_overlap

    async def add_document(self, title: str, content: str) -> DocumentDTO:
        embedding, chunks = await self._embed(content)
        document = NewDocument(
            title=title,
            content=content,
            embedding=embedding,
            chunks=chunks,
            embedding_model=self._embedding_client.fingerprint,
        )
        return await self._repository.add_document(document)

    async def reindex_unindexed_documents(self) -> int:
        """Chunk and embed every stored document that has no chunks; returns how many.

        A migration that changes the vector width has to drop the stored
        vectors, which leaves the documents in place but unsearchable. Running
        this at startup puts them back without anyone having to remember to.
        """
        pending = await self._repository.list_unindexed_documents()
        for document in pending:
            embedding, chunks = await self._embed(document.content)
            await self._repository.index_document(
                document.id, embedding, chunks, self._embedding_client.fingerprint
            )
        return len(pending)

    async def _embed(self, content: str) -> tuple[Sequence[float] | None, list[NewChunk]]:
        pieces = chunk_text(content, max_chars=self._max_chunk_chars, overlap=self._chunk_overlap)
        if not pieces:
            raise EmbeddingInputError("Document content produced no chunks to embed.")

        # One batched provider call for the whole document rather than one per
        # chunk: fewer round trips, and the provider bills per token either way.
        vectors = await self._embedding_client.embed_batch(pieces)
        chunks = [
            NewChunk(chunk_index=index, chunk_text=piece, embedding=vector)
            for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True))
        ]
        return self._mean_vector(vectors), chunks

    async def search(self, query: str, top_k: int) -> Sequence[ChunkMatchDTO]:
        if not query.strip():
            raise EmbeddingInputError("Search query must not be empty.")
        top_k = min(max(top_k, 1), MAX_TOP_K)

        fingerprint = self._embedding_client.fingerprint
        embedding = await self._embedding_client.embed_query(query)
        matches = await self._repository.search_chunks(embedding, top_k, fingerprint)
        if not matches:
            await self._explain_empty_result(fingerprint)
        return matches

    async def _explain_empty_result(self, fingerprint: str) -> None:
        """Distinguish "nothing indexed" from "indexed by a different model".

        The second case is the dangerous one: the knowledge base looks full,
        the search returns nothing, and without this the only clue would be an
        empty list.
        """
        stored = [model for model in await self._repository.list_embedding_models() if model != fingerprint]
        if not stored:
            return
        raise EmbeddingModelMismatchError(
            f"The knowledge base was indexed with {', '.join(sorted(stored))}, but the configured "
            f"embedding model is {fingerprint}. Vectors from different models are not comparable. "
            f"Re-index the documents (python -m src.app.cli.seed --force) or restore the previous "
            f"EMBEDDING_PROVIDER/EMBEDDING_MODEL settings."
        )

    @staticmethod
    def _mean_vector(vectors: Sequence[Sequence[float]]) -> Sequence[float] | None:
        """Document-level embedding: the centroid of its chunks.

        Fills the document's vector column without spending a second provider
        call on the full text. Re-normalised so it sits on the same unit sphere
        as the chunk vectors and stays comparable with cosine distance.
        """
        if not vectors:
            return None
        count = len(vectors)
        centroid = [sum(values) / count for values in zip(*vectors, strict=True)]
        norm = math.sqrt(sum(value * value for value in centroid))
        if norm == 0.0:
            return centroid
        return [value / norm for value in centroid]
