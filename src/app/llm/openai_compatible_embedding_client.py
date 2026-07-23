from collections.abc import Sequence
from typing import Any

from src.app.core.settings.embeddings import EmbeddingSettings
from src.app.exceptions.embeddings import EmbeddingGenerationError, EmbeddingInputError
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.llm.errors import wrap_provider_errors


class OpenAICompatibleEmbeddingClient(EmbeddingClient):
    """Adapter: wraps the OpenAI embeddings SDK behind our EmbeddingClient port.

    Everything provider-shaped (SDK objects, error types, response envelopes)
    stops here, so services never learn which vendor is in use and a different
    provider can be added without touching them.
    """

    def __init__(self, *, settings: EmbeddingSettings, client: Any) -> None:
        self._settings = settings
        self._client = client

    @property
    def provider_name(self) -> str:
        return self._settings.provider

    @property
    def model_name(self) -> str:
        return self._settings.model

    @property
    def dimensions(self) -> int:
        return self._settings.dimensions

    async def embed_query(self, text: str) -> Sequence[float]:
        if not text.strip():
            raise EmbeddingInputError("Cannot embed empty text.")
        vectors = await self.embed_batch([text])
        return vectors[0]

    @wrap_provider_errors("embed_batch")
    async def embed_batch(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            raise EmbeddingInputError("Cannot embed an empty batch.")

        response = await self._client.embeddings.create(**self._request_params(texts))
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

        if len(vectors) != len(texts):
            raise EmbeddingGenerationError("Embedding provider returned a different number of vectors than inputs.")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingGenerationError(
                    f"Embedding provider returned {len(vector)} dimensions, expected {self.dimensions}."
                )
        return vectors

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if callable(close):
            await close()

    def _request_params(self, texts: Sequence[str]) -> dict[str, object]:
        params: dict[str, object] = {"model": self._settings.model, "input": list(texts)}
        if self._settings.provider == "openai":
            # Only the OpenAI text-embedding-3 family accepts this parameter;
            # sending it to an arbitrary compatible server is a 400.
            params["dimensions"] = self._settings.dimensions
        return params
