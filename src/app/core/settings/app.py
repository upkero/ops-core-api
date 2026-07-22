from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class AppSettings(BaseSettings):
    db_url: PostgresDsn | None = Field(
        default=None,
        description="PostgreSQL async connection URL (postgresql+asyncpg://...).",
    )
    # Required on purpose: with a default of None the service would start
    # happily and reject every write with a puzzling 401. Failing at startup
    # says what is actually wrong. SecretStr keeps it out of logs and repr.
    api_key: SecretStr = Field(
        ...,
        min_length=16,
        description="Shared secret for write endpoints, sent as the X-API-Key header.",
    )
    public_reads: bool = Field(
        default=True,
        description=(
            "True: read endpoints are open, only writes need the API key — the public "
            "demo posture. False: every endpoint except /health needs the key, for "
            "deployments where this service is the private source of truth."
        ),
    )
    rate_limit_per_minute: int = Field(
        default=60,
        gt=0,
        description="Requests per minute per client IP, applied to every endpoint.",
    )
    embedding_rate_limit_per_minute: int = Field(
        default=20,
        gt=0,
        description="Tighter per-minute limit for endpoints that call the embedding provider.",
    )
    # NoDecode stops the settings source from JSON-decoding this field, which it
    # does for any complex type before validators run. Without it a plain
    # "a,b" env value fails at parse time and split_comma_separated never sees it.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="Allowed CORS origins, comma-separated in the environment. Restrict in production.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def split_comma_separated(cls, value: Any) -> Any:
        # pydantic-settings parses a bare list[str] env var as JSON, so a plain
        # "a,b" value would fail validation without this.
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    return AppSettings()
