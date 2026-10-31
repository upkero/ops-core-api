from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.app.schemas.base import ResponseModel


class DocumentCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    content: str = Field(..., min_length=1, max_length=100_000)


class DocumentResponse(ResponseModel):
    id: UUID
    title: str
    chunk_count: int
    created_at: datetime



class DocumentSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2_000)
    top_k: int = Field(default=5, ge=1, le=50)


class ChunkMatchResponse(ResponseModel):
    chunk_id: UUID
    document_id: UUID
    document_title: str
    chunk_index: int
    chunk_text: str
    distance: float
    score: float


class DocumentSearchResponse(ResponseModel):
    query: str
    matches: list[ChunkMatchResponse]
