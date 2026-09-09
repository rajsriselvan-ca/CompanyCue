"""The research agent.

Two phases, deliberately separated:

  Phase 1 - RESEARCH. The model is given the two search tools and no ability to
  answer. It issues queries, we execute them against SerpAPI, and the results
  accumulate into a numbered evidence corpus. Bounded by a round limit and a
  hard search budget so a confused model cannot spend the user's quota.

  Phase 2 - SYNTHESIS. Tools off, JSON mode on, one streamed call per section.
  Each section sees only the evidence and must cite it. Tokens are pushed out
  as they arrive and repaired into partial objects, so the UI fills in live.

Cancellation is cooperative through asyncio: when the client disconnects the
API cancels the task running this generator, which unwinds through the awaits
below and closes the upstream HTTP connections. There is no polling.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import ValidationError

from app.agent.errors import AgentError, InvalidResponseError, NoEvidenceError
from app.agent.evidence import EvidenceCorpus
from app.agent.events import (
    AgentEvent,
    RESEARCH_READY,
    RESEARCH_STARTED,
    SECTION_COMPLETED,
    SECTION_DELTA,
    SECTION_FAILED,
    SECTION_STARTED,
    STAGE,
    TOOL_CALL,
    TOOL_RESULT,
)
from app.agent.llm import ChatRequest, GroqClient, StreamFinished, TextDelta, ToolCallsReady
from app.agent.partial_json import parse_partial, parse_strict
from app.agent.prompts import build_research_messages, build_section_messages
from app.agent.search import SerpApiSearchClient
from app.agent.tools import TOOL_SCHEMAS, SearchToolbox, ToolExecution
from app.config import Settings
from app.schemas import (
    SECTION_LABELS,
    SECTION_MODELS,
    SECTION_ORDER,
    SectionKey,
)

logger = logging.getLogger(__name__)

# Sentinel put on the internal queue when a section task finishes.
_SECTION_DONE = object()

# GPT-OSS currently emits one local tool call per turn even when parallel tool
# calls are enabled. Keep asking until the evidence covers the five briefing
# areas, while the existing round and search limits still bound provider use.
_MIN_RESEARCH_SEARCHES = 5


class ResearchAgent:
    def __init__(
        self,
        *,
        llm: GroqClient,
        search: SerpApiSearchClient,
        settings: Settings,
    ) -> None:
        self._llm = llm
        self._search = search
        self._settings = settings

    async def run(self, company_name: str) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            RESEARCH_STARTED,
            {
                "company_name": company_name,
                "sections": [
                    {"key": key, "label": SECTION_LABELS[key]} for key in SECTION_ORDER
                ],
            },
        )

        evidence = EvidenceCorpus()
        async for event in self._research_phase(company_name, evidence):
            yield event

        if not evidence:
            raise NoEvidenceError(
                f"No usable web results were found for “{company_name}”. Check the "
                "spelling, or add a distinguishing word such as the country or industry.",
                retryable=False,
            )

        yield AgentEvent(
            STAGE,
            {
                "stage": "synthesizing",
                "message": f"Writing the briefing from {len(evidence)} sources",
                "evidence_count": len(evidence),
            },
        )

        sections: dict[str, Any] = {key: None for key in SECTION_ORDER}
        section_sources: dict[str, list[dict[str, Any]]] = {}
        warnings: list[str] = []

        async for event in self._synthesis_phase(company_name, evidence):
            if event.name == SECTION_COMPLETED:
                key = event.data["section"]
                sections[key] = event.data["data"]
                section_sources[key] = event.data["sources"]
            elif event.name == SECTION_FAILED:
                warnings.append(event.data["message"])
            yield event

        if all(value is None for value in sections.values()):
            raise InvalidResponseError(
                "The briefing could not be written from the sources found. Please try again.",
                retryable=True,
            )

        yield AgentEvent(
            RESEARCH_READY,
            {
                "company_name": company_name,
                "sections": sections,
                "section_sources": section_sources,
                "warnings": warnings,
            },
        )

    # --- Phase 1: research ---------------------------------------------------

    async def _research_phase(
        self, company_name: str, evidence: EvidenceCorpus
    ) -> AsyncIterator[AgentEvent]:
        messages = build_research_messages(company_name)
        toolbox = SearchToolbox(self._search, max_searches=self._settings.agent_max_searches)

        yield AgentEvent(
            STAGE, {"stage": "planning", "message": f"Planning research for {company_name}"}
        )

        for round_index in range(self._settings.agent_max_tool_rounds):
            searches_run = self._settings.agent_max_searches - toolbox.remaining
            must_search = searches_run < min(
                _MIN_RESEARCH_SEARCHES, self._settings.agent_max_searches
            )
            request = ChatRequest(
                messages=messages,
                model=self._settings.groq_planner_model,
                tools=TOOL_SCHEMAS,
                # The planner has nothing to answer from until it has gathered
                # a useful spread of evidence across the five briefing areas.
                tool_choice="required" if must_search else "auto",
                temperature=0.3,
                max_tokens=1200,
                extra=_model_options(self._settings.groq_planner_model),
            )

            tool_calls = []
            async for part in self._llm.stream_chat(request):
                if isinstance(part, ToolCallsReady):
                    tool_calls = part.tool_calls
                elif isinstance(part, StreamFinished) and part.reason == "length":
                    logger.warning("Planner hit the token limit in round %d", round_index + 1)

            if not tool_calls:
                break

            if round_index == 0:
                yield AgentEvent(
                    STAGE,
                    {
                        "stage": "searching",
                        "message": "Searching the web",
                        "planned_searches": len(tool_calls),
                    },
                )

            for call in tool_calls:
                arguments = call.parsed_arguments()
                yield AgentEvent(
                    TOOL_CALL,
                    {
                        "id": call.id,
                        "tool": call.name,
                        "query": " ".join(str(arguments.get("query", "")).split()),
                    },
                )

            executions = await toolbox.execute_all(tool_calls)

            for execution in executions:
                added = evidence.add(execution.results, query=execution.query)
                yield AgentEvent(
                    TOOL_RESULT,
                    {
                        "id": execution.call_id,
                        "tool": execution.tool,
                        "query": execution.query,
                        "result_count": len(execution.results),
                        "new_sources": added,
                        "elapsed_ms": execution.elapsed_ms,
                        "error": execution.error,
                        "top_results": [
                            {"title": result.title, "url": result.url}
                            for result in execution.results[:3]
                        ],
                    },
                )

            messages.append(_assistant_tool_call_message(tool_calls))
            messages.extend(execution.to_tool_message() for execution in executions)

            if toolbox.remaining <= 0:
                break

    # --- Phase 2: synthesis --------------------------------------------------

    async def _synthesis_phase(
        self, company_name: str, evidence: EvidenceCorpus
    ) -> AsyncIterator[AgentEvent]:
        """Stream several sections at once while keeping each section's order.

        Events from concurrent sections interleave, which is fine because every
        event names its section. A queue is used rather than `asyncio.gather`
        so that deltas reach the client as they are produced instead of after
        the slowest section finishes.
        """
        queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue()
        semaphore = asyncio.Semaphore(self._settings.agent_section_concurrency)

        async def worker(section: SectionKey, index: int) -> None:
            try:
                async with semaphore:
                    async for event in self._stream_section(
                        company_name=company_name,
                        section=section,
                        index=index,
                        evidence=evidence,
                    ):
                        await queue.put(event)
            except asyncio.CancelledError:
                raise
            except AgentError as exc:
                await queue.put(_section_failure(section, exc.user_message, exc.retryable))
            except Exception:  # noqa: BLE001 - one section must not sink the briefing
                logger.exception("Section %s failed unexpectedly", section)
                await queue.put(
                    _section_failure(
                        section, f"{SECTION_LABELS[section]} could not be completed.", True
                    )
                )
            finally:
                await queue.put(_SECTION_DONE)

        tasks = [
            asyncio.create_task(worker(section, index), name=f"section:{section}")
            for index, section in enumerate(SECTION_ORDER, start=1)
        ]

        remaining = len(tasks)
        try:
            while remaining:
                item = await queue.get()
                if item is _SECTION_DONE:
                    remaining -= 1
                    continue
                yield item  # type: ignore[misc]
        finally:
            # Covers both normal completion and the caller cancelling us
            # mid-stream: no section task outlives this generator.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _stream_section(
        self,
        *,
        company_name: str,
        section: SectionKey,
        index: int,
        evidence: EvidenceCorpus,
    ) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(
            SECTION_STARTED,
            {
                "section": section,
                "label": SECTION_LABELS[section],
                "index": index,
                "total": len(SECTION_ORDER),
            },
        )

        request = ChatRequest(
            messages=build_section_messages(
                company_name=company_name, section=section, evidence=evidence
            ),
            model=self._settings.groq_model,
            json_mode=True,
            temperature=0.1,
            max_tokens=1400,
            extra=_model_options(self._settings.groq_model),
        )

        buffer = ""
        last_partial: dict[str, Any] | None = None
        truncated = False

        async for part in self._llm.stream_chat(request):
            if isinstance(part, TextDelta):
                buffer += part.text
                partial = parse_partial(buffer)
                # Only push when the repaired object actually changed, so a
                # burst of tokens inside one string does not spam the client.
                if partial is not None and partial != last_partial:
                    last_partial = partial
                    yield AgentEvent(
                        SECTION_DELTA,
                        {"section": section, "partial": partial, "received": len(buffer)},
                    )
            elif isinstance(part, StreamFinished) and part.reason == "length":
                truncated = True

        raw = parse_strict(buffer)
        if raw is None:
            raise InvalidResponseError(
                f"{SECTION_LABELS[section]} came back unreadable.", retryable=True
            )

        try:
            validated = SECTION_MODELS[section].model_validate(raw)
        except ValidationError as exc:
            logger.warning("Validation failed for section %s: %s", section, exc)
            raise InvalidResponseError(
                f"{SECTION_LABELS[section]} came back in an unexpected shape.", retryable=True
            ) from exc

        payload = validated.model_dump(mode="json")
        citations = _collect_citations(payload)

        yield AgentEvent(
            SECTION_COMPLETED,
            {
                "section": section,
                "data": payload.get(section),
                "sources": evidence.sources_for(citations),
                "truncated": truncated,
            },
        )


def _assistant_tool_call_message(tool_calls: list[Any]) -> dict[str, Any]:
    """Replay the model's own tool calls so the next round has the full history."""
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments or "{}"},
            }
            for call in tool_calls
        ],
    }


def _model_options(model: str) -> dict[str, Any]:
    """Keep GPT-OSS reasoning inside the response budgets used by this app."""
    if model.startswith("openai/gpt-oss-"):
        return {"reasoning_effort": "low"}
    return {}


def _section_failure(section: SectionKey, message: str, retryable: bool) -> AgentEvent:
    return AgentEvent(
        SECTION_FAILED,
        {
            "section": section,
            "label": SECTION_LABELS[section],
            "message": f"{SECTION_LABELS[section]} is unavailable: {message}",
            "retryable": retryable,
        },
    )


def _collect_citations(payload: dict[str, Any]) -> list[int]:
    """Gather section-level and per-item citation numbers, in order."""
    citations: list[int] = [int(value) for value in payload.get("citations", []) if _is_index(value)]
    for value in payload.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and _is_index(item.get("citation")):
                    citations.append(int(item["citation"]))
    seen: set[int] = set()
    ordered: list[int] = []
    for citation in citations:
        if citation not in seen:
            seen.add(citation)
            ordered.append(citation)
    return ordered


def _is_index(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
