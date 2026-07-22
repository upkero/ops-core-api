from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewDocument
from src.app.interfaces.repositories.knowledge_repository import KnowledgeRepository
from src.app.models.knowledge import DocumentChunk, KnowledgeDocument


class SqlAlchemyKnowledgeRepository(KnowledgeRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_document(self, document: NewDocument) -> DocumentDTO:
        row = KnowledgeDocument(
            title=document.title,
            content=document.content,
            embedding=list(document.embedding) if document.embedding is not None else None,
        )
        self._session.add(row)
        await self._session.flush()

        self._session.add_all(
            [
                DocumentChunk(
                    document_id=row.id,
                    chunk_text=chunk.chunk_text,
                    embedding=list(chunk.embedding),
                    chunk_index=chunk.chunk_index,
                )
                for chunk in document.chunks
            ]
        )
        await self._session.flush()
        await self._session.refresh(row)

        return DocumentDTO(
            id=row.id,
            title=row.title,
            content=row.content,
            chunk_count=len(document.chunks),
            created_at=row.created_at,
        )

    async def search_chunks(self, embedding: Sequence[float], top_k: int) -> Sequence[ChunkMatchDTO]:
        # pgvector's `<=>` (cosine distance) is used directly rather than `<->`
        # (L2) plus a conversion: converting L2 to cosine is only valid when
        # every vector is unit length, which is not guaranteed across embedding
        # providers, and a broken assumption there returns plausible-looking but
        # wrong scores. The HNSW index uses the matching vector_cosine_ops.
        distance = DocumentChunk.embedding.cosine_distance(list(embedding)).label("distance")
        stmt = (
            select(DocumentChunk, KnowledgeDocument.title, distance)
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            .order_by(distance)
            .limit(top_k)
        )
        rows = await self._session.execute(stmt)
        return [
            ChunkMatchDTO(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_title=title,
                chunk_index=chunk.chunk_index,
                chunk_text=chunk.chunk_text,
                distance=float(chunk_distance),
                score=1.0 - float(chunk_distance),
            )
            for chunk, title, chunk_distance in rows
        ]
