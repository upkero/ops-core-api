from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

# Vector width of the knowledge base. Baked into the schema, so changing it
# means writing a migration; the embedding provider must be configured to
# return exactly this many dimensions.
EMBEDDING_DIMENSIONS = 1024


@dataclass(frozen=True, slots=True)
class NewChunk:
    """A chunk ready to be persisted, embedding already computed."""

    chunk_index: int
    chunk_text: str
    embedding: Sequence[float]


@dataclass(frozen=True, slots=True)
class NewDocument:
    title: str
    content: str
    embedding: Sequence[float] | None
    chunks: Sequence[NewChunk]
    # Fingerprint of the model that produced every vector in this document.
    embedding_model: str


@dataclass(frozen=True, slots=True)
class DocumentDTO:
    id: UUID
    title: str
    content: str
    chunk_count: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChunkMatchDTO:
    """One semantic-search hit.

    `distance` is pgvector's cosine distance (0 = identical direction, 2 =
    opposite). `score` is the cosine similarity `1 - distance`, so it reads the
    intuitive way round: higher is more relevant.
    """

    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    chunk_text: str
    distance: float
    score: float
