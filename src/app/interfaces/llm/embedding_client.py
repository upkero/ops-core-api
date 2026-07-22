from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbeddingClient(ABC):
    """Port for turning text into vectors.

    Deliberately separate from any text-generation port: embedding and
    completion are different responsibilities with different providers, models
    and failure modes, and a service that only needs one should not be coupled
    to the other (Single Responsibility / Interface Segregation).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @abstractmethod
    async def embed_query(self, text: str) -> Sequence[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    @abstractmethod
    async def close(self) -> None: ...
