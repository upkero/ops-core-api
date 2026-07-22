from fastapi import APIRouter, status

from src.app.api.v1.dependencies import KnowledgeServiceDep
from src.app.schemas.document import (
    ChunkMatchResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
)

router = APIRouter(prefix="/documents", tags=["knowledge"])


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def add_document(body: DocumentCreateRequest, service: KnowledgeServiceDep) -> DocumentResponse:
    # Chunking and embedding are the service's job; the router does not know
    # that either step exists.
    document = await service.add_document(body.title, body.content)
    return DocumentResponse.from_contract(document)


@router.post("/search", response_model=DocumentSearchResponse)
async def search_documents(body: DocumentSearchRequest, service: KnowledgeServiceDep) -> DocumentSearchResponse:
    matches = await service.search(body.query, body.top_k)
    return DocumentSearchResponse(
        query=body.query,
        matches=[ChunkMatchResponse.from_contract(match) for match in matches],
    )
