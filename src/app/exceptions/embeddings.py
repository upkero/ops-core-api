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


class EmbeddingModelMismatchError(EmbeddingError):
    """Raised when stored vectors came from a different model than the one configured.

    Deliberately loud: comparing vectors across models yields confident-looking
    scores rather than an error, so without this the only symptom would be
    silently irrelevant search results.
    """

    error_code = "embedding_model_mismatch"
    default_detail = "Stored embeddings were produced by a different model."


class EmbeddingGenerationError(EmbeddingError):
    """Raised when the provider fails to return embeddings."""

    status_code = 502
    error_code = "embedding_generation_error"
    default_detail = "Embedding provider request failed."
