from __future__ import annotations

import os

# The recorded transports pace themselves so a local demo looks like a real
# stream. Tests want them instant. Set before importing anything from `app`.
os.environ.setdefault("MOCK_STREAM_DELAY", "0")

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.agent import build_runtime  # noqa: E402
from app.agent.llm import ChatRequest, GroqClient  # noqa: E402
from app.agent.search import SerpApiSearchClient  # noqa: E402
from app.config import Settings  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Mock providers on, a throwaway database, no retry sleeps in tests."""
    return Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        mock_providers=True,
        http_retry_base_seconds=0.0,
        sse_heartbeat_seconds=0.05,
        agent_section_concurrency=5,
    )


@pytest.fixture
def runtime(settings: Settings):
    return build_runtime(settings)


def make_llm(handler, **overrides) -> GroqClient:
    """A GroqClient wired to a caller-supplied transport."""
    kwargs = {
        "api_key": None,
        "base_url": "https://api.groq.com/openai/v1",
        "connect_timeout": 1.0,
        "read_timeout": 5.0,
        "max_retries": 0,
        "retry_base_seconds": 0.0,
        "transport": httpx.MockTransport(handler),
    }
    kwargs.update(overrides)
    return GroqClient(**kwargs)  # type: ignore[arg-type]


def make_search(handler, **overrides) -> SerpApiSearchClient:
    kwargs = {
        "api_key": None,
        "base_url": "https://serpapi.com",
        "results_per_query": 6,
        "country": "us",
        "language": "en",
        "connect_timeout": 1.0,
        "read_timeout": 5.0,
        "max_retries": 0,
        "retry_base_seconds": 0.0,
        "transport": httpx.MockTransport(handler),
    }
    kwargs.update(overrides)
    return SerpApiSearchClient(**kwargs)  # type: ignore[arg-type]


def simple_request(**overrides) -> ChatRequest:
    payload = {"messages": [{"role": "user", "content": "hi"}], "model": "test-model"}
    payload.update(overrides)
    return ChatRequest(**payload)  # type: ignore[arg-type]
