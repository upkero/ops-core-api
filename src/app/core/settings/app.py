from functools import lru_cache
from typing import Annotated, Any
from zoneinfo import ZoneInfo

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
        description="Shared secret for every /api/v1 endpoint, sent as the X-API-Key header.",
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
    business_timezone: str = Field(
        default="Europe/Moscow",
        description=(
            "IANA timezone the slots are scheduled in. slot_date/slot_time carry no zone: they are the "
            "wall clock of the business, so 'now' for slot purposes is the current time in this zone."
        ),
    )
    slot_window_days: int = Field(
        default=14,
        gt=0,
        le=365,
        description="How many days ahead (starting tomorrow) booking slots are kept on offer.",
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

    @field_validator("business_timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError) as exc:  # unknown key, or a malformed one
            raise ValueError(f"unknown timezone {value!r}") from exc
        return value

    @property
    def business_tz(self) -> ZoneInfo:
        return ZoneInfo(self.business_timezone)

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
