from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewDocument


class KnowledgeRepository(ABC):
    @abstractmethod
    async def add_document(self, document: NewDocument) -> DocumentDTO:
        """Persist a document together with its pre-embedded chunks."""

    @abstractmethod
    async def search_chunks(self, embedding: Sequence[float], top_k: int) -> Sequence[ChunkMatchDTO]:
        """Nearest chunks by cosine distance, closest first."""
