from openai import AsyncOpenAI

from src.app.contracts.knowledge import EMBEDDING_DIMENSIONS
from src.app.core.settings.embeddings import EmbeddingSettings
from src.app.exceptions.embeddings import EmbeddingConfigurationError
from src.app.interfaces.llm.embedding_client import EmbeddingClient
from src.app.llm.hashing_embedding_client import HashingEmbeddingClient
from src.app.llm.local_embedding_client import LocalEmbeddingClient
from src.app.llm.openai_compatible_embedding_client import OpenAICompatibleEmbeddingClient


def create_embedding_client(settings: EmbeddingSettings) -> EmbeddingClient:
    """Factory: the single place that knows how to build a concrete client.

    Callers depend on the EmbeddingClient port, so adding a provider means
    adding a branch and a class here — no service, router or repository
    changes (Open/Closed). This is also the only place AsyncOpenAI is
    instantiated.
    """
    if settings.dimensions != EMBEDDING_DIMENSIONS:
        # Caught at startup rather than as an opaque database error on the
        # first insert into a vector(1536) column.
        raise EmbeddingConfigurationError(
            f"EMBEDDING_DIMENSIONS is {settings.dimensions}, but the schema stores "
            f"vector({EMBEDDING_DIMENSIONS}). Change both together with a migration."
        )

    if settings.provider == "hashing":
        return HashingEmbeddingClient(dimensions=settings.dimensions)

    if settings.provider == "local":
        return LocalEmbeddingClient(settings=settings)

    raw_client = AsyncOpenAI(
        api_key=settings.api_key.get_secret_value() if settings.api_key else None,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )
    return OpenAICompatibleEmbeddingClient(settings=settings, client=raw_client)
