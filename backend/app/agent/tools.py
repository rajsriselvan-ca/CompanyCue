"""Tool definitions the LLM can call, and the dispatcher that executes them.

These are ordinary OpenAI-style function schemas. The model decides which
queries to run; this module is the only place that actually touches the search
provider, which keeps the "what should I look up" decision and the "how do I
look it up" mechanics separable and separately testable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from app.agent.errors import AgentError
from app.agent.llm import ToolCall
from app.agent.search import SearchResult, SerpApiSearchClient

logger = logging.getLogger(__name__)

WEB_SEARCH = "web_search"
NEWS_SEARCH = "news_search"

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": WEB_SEARCH,
            "description": (
                "Search the live web for facts about a company: what it does, its "
                "products and customers, its leadership, headcount, revenue, market "
                "cap, litigation or regulatory issues. Use precise queries; one "
                "topic per call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A focused search query, e.g. 'Stripe CEO and executive team 2026'.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": NEWS_SEARCH,
            "description": (
                "Search recent news coverage from the past year. Use this for "
                "acquisitions, funding, earnings, product launches, partnerships, "
                "layoffs, leadership changes and breaking risk events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "A focused news query, e.g. 'Stripe acquisition announcement'.",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(slots=True)
class ToolExecution:
    call_id: str
    tool: str
    query: str
    results: list[SearchResult]
    elapsed_ms: int
    error: str | None = None

    def to_tool_message(self) -> dict[str, Any]:
        """The `role: tool` message fed back to the model for the next round."""
        if self.error:
            content = f"Search failed: {self.error}"
        elif not self.results:
            content = "No results found for this query."
        else:
            content = "\n".join(
                f"- {result.title}"
                + (f" ({result.published})" if result.published else "")
                + f"\n  {result.url}\n  {result.snippet[:280]}"
                for result in self.results
            )
        return {"role": "tool", "tool_call_id": self.call_id, "content": content}


class SearchToolbox:
    """Executes model-requested searches under a hard budget."""

    def __init__(self, search_client: SerpApiSearchClient, *, max_searches: int) -> None:
        self._search = search_client
        self._remaining = max_searches
        self._seen_queries: set[str] = set()

    @property
    def remaining(self) -> int:
        return self._remaining

    async def execute_all(self, tool_calls: list[ToolCall]) -> list[ToolExecution]:
        """Run every requested search concurrently, preserving request order."""
        return list(await asyncio.gather(*(self.execute(call) for call in tool_calls)))

    async def execute(self, call: ToolCall) -> ToolExecution:
        started = time.perf_counter()
        args = call.parsed_arguments()
        query = " ".join(str(args.get("query", "")).split())

        def finish(results: list[SearchResult], error: str | None = None) -> ToolExecution:
            return ToolExecution(
                call_id=call.id,
                tool=call.name,
                query=query,
                results=results,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                error=error,
            )

        if call.name not in {WEB_SEARCH, NEWS_SEARCH}:
            return finish([], f"Unknown tool '{call.name}'.")
        if not query:
            return finish([], "The query was empty.")

        dedupe_key = f"{call.name}:{query.casefold()}"
        if dedupe_key in self._seen_queries:
            return finish([], "This query was already run; results are already available above.")
        if self._remaining <= 0:
            return finish([], "The search budget for this briefing is exhausted.")

        self._seen_queries.add(dedupe_key)
        self._remaining -= 1

        try:
            if call.name == NEWS_SEARCH:
                results = await self._search.search_news(query)
            else:
                results = await self._search.search_web(query)
        except AgentError as exc:
            logger.warning("Search tool %s failed for %r: %s", call.name, query, exc)
            return finish([], exc.user_message)
        return finish(results)
