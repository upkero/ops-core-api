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
    def model_name(self) -> str: ...

    @property
    @abstractmethod
    def dimensions(self) -> int: ...

    @property
    def fingerprint(self) -> str:
        """Identifies the vector space these embeddings live in.

        Vectors from two different models are not comparable, and cosine
        distance between them returns a plausible number rather than an error.
        Storing this alongside every vector is what lets the search refuse to
        mix spaces instead of silently returning nonsense. Defined once here so
        every implementation reports it the same way.
        """
        return f"{self.provider_name}:{self.model_name}"

    @abstractmethod
    async def embed_query(self, text: str) -> Sequence[float]: ...

    @abstractmethod
    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    @abstractmethod
    async def close(self) -> None: ...
