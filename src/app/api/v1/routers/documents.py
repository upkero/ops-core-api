from fastapi import APIRouter, Request, Response, status

from src.app.api.v1.dependencies import KnowledgeServiceDep
from src.app.api.v1.middleware.rate_limit import embedding_endpoint_limit, limiter
from src.app.schemas.document import (
    ChunkMatchResponse,
    DocumentCreateRequest,
    DocumentResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
)

router = APIRouter(prefix="/documents", tags=["knowledge"])


# slowapi needs `request` to identify the caller and `response` to attach the
# X-RateLimit-* headers to. Routers are the HTTP layer, so handling them here
# breaks no boundary — the services below stay free of both.
@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(embedding_endpoint_limit)
async def add_document(
    request: Request,
    response: Response,
    body: DocumentCreateRequest,
    service: KnowledgeServiceDep,
) -> DocumentResponse:
    # Chunking and embedding are the service's job; the router does not know
    # that either step exists.
    document = await service.add_document(body.title, body.content)
    return DocumentResponse.from_contract(document)


@router.post("/search", response_model=DocumentSearchResponse)
@limiter.limit(embedding_endpoint_limit)
async def search_documents(
    request: Request,
    response: Response,
    body: DocumentSearchRequest,
    service: KnowledgeServiceDep,
) -> DocumentSearchResponse:
    matches = await service.search(body.query, body.top_k)
    return DocumentSearchResponse(
        query=body.query,
        matches=[ChunkMatchResponse.from_contract(match) for match in matches],
    )
