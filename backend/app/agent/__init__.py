from __future__ import annotations

from dataclasses import dataclass

from app.agent.agent import ResearchAgent
from app.agent.errors import (
    AgentError,
    ConfigurationError,
    InvalidResponseError,
    NoEvidenceError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.agent.events import AgentEvent
from app.agent.llm import GroqClient
from app.agent.mocks import groq_mock_transport, serpapi_mock_transport
from app.agent.search import SerpApiSearchClient
from app.config import Settings

__all__ = [
    "AgentError",
    "AgentEvent",
    "AgentRuntime",
    "ConfigurationError",
    "GroqClient",
    "InvalidResponseError",
    "NoEvidenceError",
    "ProviderUnavailableError",
    "RateLimitError",
    "ResearchAgent",
    "SerpApiSearchClient",
    "build_runtime",
]


@dataclass(slots=True)
class AgentRuntime:
    """Long-lived clients plus the agent that uses them.

    Held on `app.state` so HTTP connections are pooled across requests rather
    than re-established per research run.
    """

    agent: ResearchAgent
    llm: GroqClient
    search: SerpApiSearchClient

    async def aclose(self) -> None:
        await self.llm.aclose()
        await self.search.aclose()


def build_runtime(settings: Settings) -> AgentRuntime:
    mock = settings.mock_providers
    llm = GroqClient(
        api_key=settings.groq_api_key.get_secret_value() if settings.groq_api_key else None,
        base_url=settings.groq_base_url,
        connect_timeout=settings.http_connect_timeout,
        read_timeout=settings.http_read_timeout,
        max_retries=settings.http_max_retries,
        retry_base_seconds=settings.http_retry_base_seconds,
        transport=groq_mock_transport() if mock else None,
    )
    search = SerpApiSearchClient(
        api_key=(
            settings.serpapi_api_key.get_secret_value() if settings.serpapi_api_key else None
        ),
        base_url=settings.serpapi_base_url,
        results_per_query=settings.serpapi_results_per_query,
        country=settings.serpapi_country,
        language=settings.serpapi_language,
        connect_timeout=settings.http_connect_timeout,
        read_timeout=settings.http_read_timeout,
        max_retries=settings.http_max_retries,
        retry_base_seconds=settings.http_retry_base_seconds,
        transport=serpapi_mock_transport() if mock else None,
    )
    return AgentRuntime(
        agent=ResearchAgent(llm=llm, search=search, settings=settings),
        llm=llm,
        search=search,
    )
