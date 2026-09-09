"""SerpAPI search client - the agent's live web-search tool.

SerpAPI exposes structured Google Search results through `/search.json`.
General searches use the normal Google engine; news searches add `tbm=nws`
and a one-year recency filter so publication dates are available to the
"recent news" section.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent.errors import ConfigurationError, ProviderUnavailableError, RateLimitError
from app.agent.transport import (
    RETRYABLE_STATUS,
    build_async_client,
    parse_retry_after,
    with_retries,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    published: str | None = None
    source: str | None = None

    def as_source(self) -> dict[str, Any]:
        return {"title": self.title, "url": self.url, "published": self.published}


class SerpApiSearchClient:
    provider_name = "SerpAPI"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        results_per_query: int,
        country: str,
        language: str,
        connect_timeout: float,
        read_timeout: float,
        max_retries: int,
        retry_base_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key or ("mock-key" if transport is not None else None)
        self._results_per_query = results_per_query
        self._country = country
        self._language = language
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds

        if not self._api_key:
            raise ConfigurationError(
                "Live web search is not configured. Set SERPAPI_API_KEY in the server "
                "environment, or run with MOCK_PROVIDERS=true."
            )
        self._client = build_async_client(
            base_url=base_url.rstrip("/"),
            headers={"Accept": "application/json"},
            connect_timeout=connect_timeout,
            # Search is fast; a long read timeout only delays the failure.
            read_timeout=min(read_timeout, 20.0),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search_web(self, query: str, *, limit: int | None = None) -> list[SearchResult]:
        payload = {
            "engine": "google",
            "q": query,
            "num": limit or self._results_per_query,
            "gl": self._country,
            "hl": self._language,
        }
        body = await self._get(payload)
        return self._parse_web(body, limit or self._results_per_query)

    async def search_news(self, query: str, *, limit: int | None = None) -> list[SearchResult]:
        payload = {
            "engine": "google",
            "q": query,
            "num": limit or self._results_per_query,
            "gl": self._country,
            "hl": self._language,
            "tbm": "nws",
            # Google's recency filter: past year. Anything older is not
            # "recent news" for a sales call.
            "tbs": "qdr:y",
        }
        body = await self._get(payload)
        return self._parse_news(body, limit or self._results_per_query)

    # --- HTTP ----------------------------------------------------------------

    async def _get(self, payload: dict[str, Any]) -> dict[str, Any]:
        async def send() -> httpx.Response:
            response = await self._client.get(
                "/search.json", params={**payload, "api_key": self._api_key}
            )
            if response.status_code >= 400:
                self._raise_for_status(response)
            return response

        response = await with_retries(
            send,
            max_retries=self._max_retries,
            base_delay=self._retry_base_seconds,
            provider=self.provider_name,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderUnavailableError(
                "Web search returned an unreadable response.", retryable=True
            ) from exc
        if not isinstance(body, dict):
            return {}

        error = self._clean(body.get("error"))
        if error:
            lowered = error.casefold()
            if "api key" in lowered:
                raise ConfigurationError(
                    "The web search provider rejected the configured API key. "
                    "Check SERPAPI_API_KEY."
                )
            if any(word in lowered for word in ("quota", "limit", "run out")):
                raise RateLimitError("The SerpAPI search quota has been exhausted.")
            if "no results" in lowered or "hasn't returned any results" in lowered:
                return body
            logger.warning("SerpAPI search error: %s", error[:300])
            raise ProviderUnavailableError("Web search could not complete.", retryable=True)
        return body

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status in {401, 403}:
            raise ConfigurationError(
                "The web search provider rejected the configured API key. Check SERPAPI_API_KEY."
            )
        if status == 429:
            raise RateLimitError(
                "Web search is rate limiting requests. CompanyCue will retry shortly.",
                retry_after=parse_retry_after(response),
            )
        if status in RETRYABLE_STATUS or status >= 500:
            raise ProviderUnavailableError(
                "Web search is temporarily unavailable. Please try again.", retryable=True
            )
        logger.error("Unexpected %s from SerpAPI: %s", status, response.text[:300])
        raise ProviderUnavailableError("Web search could not complete.", retryable=True)

    # --- Response shaping ----------------------------------------------------

    @staticmethod
    def _clean(value: object) -> str:
        return " ".join(str(value or "").split())

    def _parse_web(self, body: dict[str, Any], limit: int) -> list[SearchResult]:
        results: list[SearchResult] = []

        # The knowledge panel is often the single best source for what a
        # company does, so it leads the evidence list when present.
        knowledge = body.get("knowledge_graph")
        if isinstance(knowledge, dict) and knowledge.get("description"):
            attributes = knowledge.get("attributes")
            extra = ""
            if isinstance(attributes, dict) and attributes:
                extra = " " + "; ".join(f"{k}: {v}" for k, v in list(attributes.items())[:8])
            source = knowledge.get("source")
            source_url = source.get("link") if isinstance(source, dict) else None
            results.append(
                SearchResult(
                    title=self._clean(knowledge.get("title") or "Knowledge panel"),
                    url=self._clean(knowledge.get("website") or source_url or ""),
                    snippet=self._clean(knowledge.get("description")) + self._clean(extra),
                    source="Google Knowledge Graph",
                )
            )

        for item in body.get("organic_results") or []:
            if not isinstance(item, dict) or not item.get("link"):
                continue
            results.append(
                SearchResult(
                    title=self._clean(item.get("title")) or "Untitled result",
                    url=self._clean(item.get("link")),
                    snippet=self._clean(item.get("snippet")),
                    published=self._clean(item.get("date")) or None,
                )
            )

        for item in body.get("top_stories") or []:
            if not isinstance(item, dict) or not item.get("link"):
                continue
            results.append(
                SearchResult(
                    title=self._clean(item.get("title")) or "Untitled result",
                    url=self._clean(item.get("link")),
                    snippet=self._clean(item.get("snippet")),
                    published=self._clean(item.get("date")) or None,
                    source=self._source_name(item.get("source")),
                )
            )

        return [result for result in results if result.url][:limit]

    def _parse_news(self, body: dict[str, Any], limit: int) -> list[SearchResult]:
        results = []
        for item in body.get("news_results") or []:
            if not isinstance(item, dict) or not item.get("link"):
                continue
            results.append(
                SearchResult(
                    title=self._clean(item.get("title")) or "Untitled result",
                    url=self._clean(item.get("link")),
                    snippet=self._clean(item.get("snippet")),
                    published=self._clean(item.get("published_at") or item.get("date")) or None,
                    source=self._source_name(item.get("source")),
                )
            )
        return results[:limit]

    @classmethod
    def _source_name(cls, value: object) -> str | None:
        if isinstance(value, dict):
            value = value.get("title") or value.get("name")
        return cls._clean(value) or None


# Kept as an import alias for downstream code written against CompanyCue 1.0.
SerperSearchClient = SerpApiSearchClient
