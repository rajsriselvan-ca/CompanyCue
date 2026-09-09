from __future__ import annotations

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment or the root .env file."""

    app_name: str = "CompanyCue API"
    api_prefix: str = "/api"
    database_url: str = "sqlite+aiosqlite:///./companycue.db"

    # --- LLM: Groq -------------------------------------------------------
    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    # A smaller, faster model is enough to pick search queries.
    groq_planner_model: str = "openai/gpt-oss-20b"

    # --- Search: SerpAPI -------------------------------------------------
    # SERPER_* aliases keep existing local files working after the provider
    # integration was corrected from Serper.dev to SerpAPI.
    serpapi_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SERPAPI_API_KEY", "SERPER_API_KEY"),
    )
    serpapi_base_url: str = Field(
        default="https://serpapi.com",
        validation_alias=AliasChoices("SERPAPI_BASE_URL", "SERPER_BASE_URL"),
    )
    serpapi_results_per_query: int = Field(
        default=6,
        ge=1,
        le=20,
        validation_alias=AliasChoices("SERPAPI_RESULTS_PER_QUERY", "SERPER_RESULTS_PER_QUERY"),
    )
    serpapi_country: str = Field(
        default="us", validation_alias=AliasChoices("SERPAPI_COUNTRY", "SERPER_COUNTRY")
    )
    serpapi_language: str = Field(
        default="en", validation_alias=AliasChoices("SERPAPI_LANGUAGE", "SERPER_LANGUAGE")
    )

    # --- Agent behaviour -------------------------------------------------
    # How many rounds of "model asks for searches -> we run them" to allow.
    agent_max_tool_rounds: int = Field(default=5, ge=1, le=5)
    agent_max_searches: int = Field(default=8, ge=1, le=20)
    # Serial synthesis is the reliable default for Groq's free-tier limits.
    agent_section_concurrency: int = Field(default=1, ge=1, le=5)

    # --- HTTP transport --------------------------------------------------
    http_connect_timeout: float = Field(default=5.0, gt=0)
    http_read_timeout: float = Field(default=90.0, gt=0)
    http_max_retries: int = Field(default=2, ge=0, le=5)
    http_retry_base_seconds: float = Field(default=1.0, ge=0, le=30)

    # --- SSE -------------------------------------------------------------
    sse_heartbeat_seconds: float = Field(default=15.0, gt=0)
    sse_client_retry_ms: int = Field(default=3000, ge=0)

    # Replace both outbound HTTP transports with recorded fixtures. The client,
    # prompt, tool-call and stream-parsing code paths are identical either way.
    mock_providers: bool = False

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def live_providers_configured(self) -> bool:
        return bool(self.groq_api_key and self.serpapi_api_key)
