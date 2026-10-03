from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewChunk, NewDocument
from src.app.interfaces.repositories.knowledge_repository import KnowledgeRepository
from src.app.models.knowledge import DocumentChunk, KnowledgeDocument


def _document_to_dto(row: KnowledgeDocument, chunk_count: int) -> DocumentDTO:
    return DocumentDTO(
        id=row.id, title=row.title, content=row.content, chunk_count=chunk_count, created_at=row.created_at
    )


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
                    embedding_model=document.embedding_model,
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

    async def list_unindexed_documents(self) -> Sequence[DocumentDTO]:
        stmt = (
            select(KnowledgeDocument)
            .outerjoin(DocumentChunk, DocumentChunk.document_id == KnowledgeDocument.id)
            .group_by(KnowledgeDocument.id)
            .having(func.count(DocumentChunk.id) == 0)
            .order_by(KnowledgeDocument.created_at, KnowledgeDocument.id)
        )
        return [_document_to_dto(row, 0) for row in await self._session.scalars(stmt)]

    async def index_document(
        self,
        document_id: UUID,
        embedding: Sequence[float] | None,
        chunks: Sequence[NewChunk],
        embedding_model: str,
    ) -> DocumentDTO:
        row = await self._session.get(KnowledgeDocument, document_id)
        if row is None:
            raise LookupError(f"Document {document_id} disappeared while it was being re-indexed.")
        row.embedding = list(embedding) if embedding is not None else None
        self._session.add_all(
            [
                DocumentChunk(
                    document_id=document_id,
                    chunk_text=chunk.chunk_text,
                    embedding=list(chunk.embedding),
                    chunk_index=chunk.chunk_index,
                    embedding_model=embedding_model,
                )
                for chunk in chunks
            ]
        )
        await self._session.flush()
        return _document_to_dto(row, len(chunks))

    async def list_embedding_models(self) -> Sequence[str]:
        result = await self._session.scalars(select(DocumentChunk.embedding_model).distinct())
        return list(result)

    async def search_chunks(
        self,
        embedding: Sequence[float],
        top_k: int,
        embedding_model: str,
    ) -> Sequence[ChunkMatchDTO]:
        # pgvector's `<=>` (cosine distance) is used directly rather than `<->`
        # (L2) plus a conversion: converting L2 to cosine is only valid when
        # every vector is unit length, which is not guaranteed across embedding
        # providers, and a broken assumption there returns plausible-looking but
        # wrong scores. The HNSW index uses the matching vector_cosine_ops.
        distance = DocumentChunk.embedding.cosine_distance(list(embedding)).label("distance")
        stmt = (
            select(DocumentChunk, KnowledgeDocument.title, distance)
            .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
            # Filtering here, rather than checking afterwards, makes a
            # cross-model comparison impossible by construction.
            .where(DocumentChunk.embedding_model == embedding_model)
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
