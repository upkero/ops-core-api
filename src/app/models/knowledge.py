import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.app.contracts.knowledge import EMBEDDING_DIMENSIONS
from src.app.models.base import Base


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(300), index=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunk"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunk_position"),
        # HNSW with vector_cosine_ops: the opclass must match the operator used
        # by the search query (<=>), otherwise Postgres silently ignores the
        # index and falls back to a sequential scan.
        Index(
            "ix_document_chunk_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_document.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    chunk_index: Mapped[int] = mapped_column(Integer)
    # Which model produced `embedding`. Vectors from different models are not
    # comparable, so search filters on this instead of trusting that whatever
    # is stored matches the currently configured provider.
    embedding_model: Mapped[str] = mapped_column(String(100), index=True)
