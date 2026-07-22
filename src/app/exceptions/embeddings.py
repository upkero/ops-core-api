from src.app.exceptions.base import BaseAppException


class EmbeddingError(BaseAppException):
    """Base exception for embedding client operations."""

    error_code = "embedding_error"
    default_detail = "Embedding operation failed."


class EmbeddingConfigurationError(EmbeddingError):
    """Raised when the embedding client configuration is invalid."""

    error_code = "embedding_configuration_error"


class EmbeddingInputError(EmbeddingError, ValueError):
    """Raised when the text handed to the embedding client is unusable."""

    status_code = 422
    error_code = "embedding_input_error"


class EmbeddingGenerationError(EmbeddingError):
    """Raised when the provider fails to return embeddings."""

    status_code = 502
    error_code = "embedding_generation_error"
    default_detail = "Embedding provider request failed."
