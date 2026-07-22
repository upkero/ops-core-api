from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO


class DocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1, max_length=100_000)


class DocumentResponse(BaseModel):
    id: UUID
    title: str
    chunk_count: int
    created_at: datetime

    @classmethod
    def from_contract(cls, document: DocumentDTO) -> "DocumentResponse":
        return cls(
            id=document.id,
            title=document.title,
            chunk_count=document.chunk_count,
            created_at=document.created_at,
        )


class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=50)


class ChunkMatchResponse(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    chunk_text: str
    distance: float
    score: float

    @classmethod
    def from_contract(cls, match: ChunkMatchDTO) -> "ChunkMatchResponse":
        return cls(
            chunk_id=match.chunk_id,
            document_id=match.document_id,
            document_title=match.document_title,
            chunk_index=match.chunk_index,
            chunk_text=match.chunk_text,
            distance=match.distance,
            score=match.score,
        )


class DocumentSearchResponse(BaseModel):
    query: str
    matches: list[ChunkMatchResponse]
