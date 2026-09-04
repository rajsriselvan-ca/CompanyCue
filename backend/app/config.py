from __future__ import annotations

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    app_name: str = "Briefd API"
    api_prefix: str = "/api"
    database_url: str = "sqlite+aiosqlite:///./briefd.db"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.7-flash"
    gemini_fallback_model: str | None = "gemini-3.7-flash"
    gemini_google_search_enabled: bool = False
    gemini_quota_max_retries: int = Field(default=2, ge=0, le=4)
    gemini_quota_retry_base_seconds: float = Field(default=20.0, ge=0, le=60)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value
