import asyncio
from collections.abc import Sequence
from typing import Any

from src.app.core.settings.embeddings import EmbeddingSettings
from src.app.exceptions.embeddings import EmbeddingConfigurationError, EmbeddingGenerationError, EmbeddingInputError
from src.app.interfaces.llm.embedding_client import EmbeddingClient


class LocalEmbeddingClient(EmbeddingClient):
    """Adapter: a sentence-transformers model (e.g. BAAI/bge-m3) run in this process.

    No network after the first download. The model loads at construction, i.e. at
    startup, so a missing package or a bad model name fails the boot instead of
    the first search. Encoding is CPU-bound, so it runs in a worker thread to keep
    the event loop free.
    """

    def __init__(self, *, settings: EmbeddingSettings) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise EmbeddingConfigurationError(
                "EMBEDDING_PROVIDER=local needs sentence-transformers; build the image with LOCAL_MODELS=true."
            ) from exc
        self._settings = settings
        self._model: Any = SentenceTransformer(settings.model, device="cpu")

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._settings.model

    @property
    def dimensions(self) -> int:
        return self._settings.dimensions

    async def embed_query(self, text: str) -> Sequence[float]:
        if not text.strip():
            raise EmbeddingInputError("Cannot embed empty text.")
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            raise EmbeddingInputError("Cannot embed an empty batch.")
        # Normalised, so cosine distance (the index opclass) is well behaved.
        matrix = await asyncio.to_thread(self._model.encode, list(texts), normalize_embeddings=True)
        vectors = [row.tolist() for row in matrix]
        if any(len(vector) != self.dimensions for vector in vectors):
            raise EmbeddingGenerationError(
                f"Local model returned {len(vectors[0])} dimensions, expected {self.dimensions}."
            )
        return vectors

    async def close(self) -> None:
        return None
