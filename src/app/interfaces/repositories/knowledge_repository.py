from abc import ABC, abstractmethod
from collections.abc import Sequence

from src.app.contracts.knowledge import ChunkMatchDTO, DocumentDTO, NewDocument


class KnowledgeRepository(ABC):
    @abstractmethod
    async def add_document(self, document: NewDocument) -> DocumentDTO:
        """Persist a document together with its pre-embedded chunks."""

    @abstractmethod
    async def search_chunks(
        self,
        embedding: Sequence[float],
        top_k: int,
        embedding_model: str,
    ) -> Sequence[ChunkMatchDTO]:
        """Nearest chunks by cosine distance, closest first.

        Restricted to chunks embedded by `embedding_model`: vectors from two
        models occupy different spaces, and comparing across them produces
        plausible scores rather than an error.
        """

    @abstractmethod
    async def list_embedding_models(self) -> Sequence[str]:
        """Distinct models present in storage. Used to explain an empty search."""
