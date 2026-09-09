"""End-to-end agent behaviour, driven entirely through mocked HTTP transports.

Nothing in the agent, the prompts, the tool loop or the streaming pipeline is
stubbed out - only the socket is - so these tests exercise the same code that
runs against live Groq and SerpAPI.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.agent.agent import ResearchAgent
from app.agent.errors import NoEvidenceError
from app.agent.mocks import groq_mock_handler, serper_mock_handler
from tests.conftest import make_llm, make_search


def build_agent(settings, *, groq=groq_mock_handler, serper=serper_mock_handler):
    return ResearchAgent(
        llm=make_llm(groq),
        search=make_search(serper),
        settings=settings,
    )


async def run(agent, company="Acme Corp"):
    return [event async for event in agent.run(company)]


def by_name(events, name):
    return [event for event in events if event.name == name]


async def test_full_run_searches_then_writes_every_section(settings):
    events = await run(build_agent(settings))
    names = [event.name for event in events]

    assert names[0] == "research_started"
    assert names[-1] == "research_ready"

    # The agent searched before it wrote anything.
    first_search = names.index("tool_call")
    first_write = names.index("section_started")
    assert first_search < first_write

    completed = {event.data["section"] for event in by_name(events, "section_completed")}
    assert completed == {"overview", "key_people", "news", "financials", "risks"}

    ready = events[-1].data
    assert ready["sections"]["overview"].startswith("Acme Corp")
    assert ready["sections"]["financials"]["market_cap"] is None  # never invented
    assert ready["warnings"] == []


async def test_tool_calls_are_reported_with_their_results(settings):
    events = await run(build_agent(settings))

    calls = by_name(events, "tool_call")
    results = by_name(events, "tool_result")

    assert len(calls) == len(results) == 5
    assert {call.data["tool"] for call in calls} == {"web_search", "news_search"}
    assert all(call.data["query"] for call in calls)
    assert sum(result.data["new_sources"] for result in results) > 0
    assert all(result.data["error"] is None for result in results)


async def test_sections_stream_progressively(settings):
    events = await run(build_agent(settings))
    deltas = by_name(events, "section_delta")

    assert deltas, "sections must emit partial content while streaming"

    # Every delta is a usable object, and the overview text only ever grows.
    overview_lengths = [
        len(str(event.data["partial"].get("overview", "")))
        for event in deltas
        if event.data["section"] == "overview"
    ]
    assert overview_lengths == sorted(overview_lengths)
    assert overview_lengths[-1] > 50


async def test_citations_become_section_sources(settings):
    events = await run(build_agent(settings))
    overview = next(
        event for event in by_name(events, "section_completed")
        if event.data["section"] == "overview"
    )
    urls = [source["url"] for source in overview.data["sources"]]
    assert urls, "a cited section must carry the links it was written from"
    assert all(url.startswith("http") for url in urls)


async def test_no_search_results_fails_before_writing_anything(settings):
    """An unresearchable name must not become an invented briefing."""
    agent = build_agent(
        settings, serper=lambda _: httpx.Response(200, json={"organic_results": []})
    )

    with pytest.raises(NoEvidenceError):
        await run(agent, "Zzzqqq Nonexistent Ltd")


async def test_one_broken_section_does_not_sink_the_others(settings):
    """A section whose JSON fails validation is reported and skipped."""

    def groq(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if not body.get("tools") and "RISK FACTORS" in str(body["messages"]):
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    b'data: {"choices":[{"delta":{"content":"not json at all"},'
                    b'"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                ),
            )
        return groq_mock_handler(request)

    events = await run(build_agent(settings, groq=groq))

    failed = by_name(events, "section_failed")
    assert [event.data["section"] for event in failed] == ["risks"]

    ready = events[-1].data
    assert ready["sections"]["risks"] is None
    assert ready["sections"]["overview"] is not None
    assert len(ready["warnings"]) == 1
    assert "Risk factors is unavailable" in ready["warnings"][0]


async def test_search_failure_is_reported_but_research_continues(settings):
    """One failing query should not abort a run that has other evidence."""
    calls = {"count": 0}

    def serper(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 2:
            return httpx.Response(500, json={})
        return serper_mock_handler(request)

    events = await run(build_agent(settings, serper=serper))

    failures = [event for event in by_name(events, "tool_result") if event.data["error"]]
    assert len(failures) == 1
    assert events[-1].name == "research_ready"


async def test_the_search_budget_is_enforced(settings):
    settings.agent_max_searches = 2
    events = await run(build_agent(settings))

    executed = [
        event for event in by_name(events, "tool_result") if event.data["error"] is None
    ]
    assert len(executed) == 2
    budget_messages = [
        event.data["error"] for event in by_name(events, "tool_result") if event.data["error"]
    ]
    assert all("budget" in message for message in budget_messages)


async def test_cancelling_mid_run_stops_the_section_tasks(settings):
    """A client that disconnects must not leave sections running in the background."""
    agent = build_agent(settings)
    generator = agent.run("Acme Corp")

    seen = 0
    async for event in generator:
        seen += 1
        if event.name == "section_delta":
            break
    assert seen > 0

    await generator.aclose()
    # Let any orphaned task get a chance to run; none should exist.
    await asyncio.sleep(0.05)
    leaked = [
        task
        for task in asyncio.all_tasks()
        if (task.get_name() or "").startswith("section:") and not task.done()
    ]
    assert leaked == []
