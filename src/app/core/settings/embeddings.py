from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProvider = Literal["hashing", "openai", "openai_compatible"]


class EmbeddingSettings(BaseSettings):
    provider: EmbeddingProvider = Field(
        default="hashing",
        description=(
            "Embedding provider profile. 'hashing' is a deterministic local "
            "implementation that needs no API key, so the stack runs offline."
        ),
    )
    model: str = Field(
        default="text-embedding-3-small",
        description="Model name sent to the provider. Ignored by the 'hashing' provider.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description="Provider API key. Required for provider='openai'.",
    )
    base_url: str | None = Field(
        default=None,
        description="OpenAI-compatible API base URL. Required for provider='openai_compatible'.",
    )
    dimensions: int = Field(
        default=1536,
        gt=0,
        description="Vector width. Must match the vector(N) column width in the database schema.",
    )
    timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        description="Provider request timeout in seconds.",
    )
    max_retries: int = Field(
        default=2,
        ge=0,
        description="Maximum provider SDK retries. Retry/backoff is handled by the SDK, not by hand.",
    )

    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=".env",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_provider_requirements(self) -> "EmbeddingSettings":
        if self.provider == "openai" and self.api_key is None:
            raise ValueError("api_key is required when provider='openai'.")
        if self.provider == "openai_compatible" and not self.base_url:
            raise ValueError("base_url is required when provider='openai_compatible'.")
        return self


@lru_cache(maxsize=1)
def get_embedding_settings() -> EmbeddingSettings:
    return EmbeddingSettings()
