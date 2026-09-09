"""HTTP surface: status codes, the SSE contract, persistence, duplicate locking."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.research import ActiveResearchRegistry


@pytest.fixture
def client(settings, runtime):
    # TestClient runs the lifespan, so the database and agent runtime are real.
    with TestClient(create_app(settings=settings, runtime=runtime)) as test_client:
        yield test_client


def parse_sse(text: str) -> list[dict]:
    """Decode a whole SSE body into (event, data) pairs, ignoring heartbeats."""
    events = []
    for block in text.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line.removeprefix("event: ")
            elif line.startswith("data: "):
                data.append(line.removeprefix("data: "))
        if name and data:
            events.append({"event": name, "data": json.loads("\n".join(data))})
    return events


def research(client: TestClient, company: str):
    with client.stream("POST", "/api/research", json={"company_name": company}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache, no-transform"
        return parse_sse(response.read().decode())


def test_health_reports_the_configured_providers(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["search_provider"] == "serpapi"
    assert body["llm_provider"].startswith("groq:")
    assert body["mock_mode"] is True


def test_reports_list_is_empty_before_any_research(client):
    response = client.get("/api/reports")
    assert response.status_code == 200
    assert response.json() == []


def test_research_streams_events_and_saves_the_report(client):
    events = research(client, "Acme Corp")
    names = [event["event"] for event in events]

    assert names[0] == "research_started"
    assert names[-1] == "research_completed"
    assert "tool_call" in names and "section_delta" in names

    report = events[-1]["data"]["report"]
    assert report["company_name"] == "Acme Corp"
    assert report["overview"]
    assert len(report["key_people"]) >= 1

    # It is retrievable afterwards, newest first in the list.
    listed = client.get("/api/reports").json()
    assert [item["company_name"] for item in listed] == ["Acme Corp"]

    fetched = client.get(f"/api/reports/{report['id']}").json()
    assert fetched["id"] == report["id"]
    assert fetched["section_sources"]["overview"]


def test_event_ids_increase_monotonically(client):
    with client.stream("POST", "/api/research", json={"company_name": "Acme Corp"}) as response:
        body = response.read().decode()
    ids = [int(line.removeprefix("id: ")) for line in body.split("\n") if line.startswith("id: ")]
    assert ids == list(range(1, len(ids) + 1))
    assert body.startswith("retry: ")


def test_reports_can_be_deleted(client):
    report = research(client, "Acme Corp")[-1]["data"]["report"]

    assert client.delete(f"/api/reports/{report['id']}").status_code == 204
    assert client.get(f"/api/reports/{report['id']}").status_code == 404
    assert client.delete(f"/api/reports/{report['id']}").status_code == 404
    assert client.get("/api/reports").json() == []


def test_unknown_report_id_is_404_and_a_malformed_one_is_422(client):
    assert client.get("/api/reports/11111111-1111-1111-1111-111111111111").status_code == 404
    assert client.get("/api/reports/not-a-uuid").status_code == 422


@pytest.mark.parametrize(
    "company_name",
    ["", " ", "a", "!!!!", "https://acme.com", "sales@acme.com", "aaaaa", "x" * 200],
)
def test_gibberish_input_is_rejected_with_a_readable_message(client, company_name):
    response = client.post("/api/research", json={"company_name": company_name})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail
    assert "Value error" not in detail


async def test_registry_admits_one_run_per_company_regardless_of_spelling():
    registry = ActiveResearchRegistry()

    assert await registry.acquire("Acme Corp") is True
    assert await registry.acquire("  acme   CORP ") is False  # same company
    assert await registry.acquire("Globex") is True  # different company

    await registry.release("ACME corp")
    assert await registry.acquire("Acme Corp") is True


def test_a_second_run_for_the_same_company_is_rejected_with_409(client):
    """The endpoint refuses before it opens a stream, so the user gets a status
    code rather than a stream that immediately errors.

    Both test transports buffer a streaming response to completion, so the
    in-flight run is simulated by holding the lock the endpoint checks.
    """
    registry = client.app.state.research_registry
    client.portal.call(registry.acquire, "Acme Corp")

    duplicate = client.post("/api/research", json={"company_name": "  acme   CORP "})
    assert duplicate.status_code == 409
    assert "already being generated" in duplicate.json()["detail"]

    # A different company is unaffected.
    other = client.post("/api/research", json={"company_name": "Globex"})
    assert other.status_code == 200


def test_the_lock_is_released_once_the_stream_finishes(client):
    research(client, "Acme Corp")
    registry = client.app.state.research_registry
    assert client.portal.call(registry.acquire, "Acme Corp") is True


def test_a_provider_outage_becomes_a_research_failed_event_not_a_500(client, runtime):
    from app.agent.search import SerpApiSearchClient

    # Point the search client at a transport that always fails.
    broken = SerpApiSearchClient(
        api_key="k",
        base_url="https://serpapi.com",
        results_per_query=6,
        country="us",
        language="en",
        connect_timeout=1.0,
        read_timeout=1.0,
        max_retries=0,
        retry_base_seconds=0.0,
        transport=httpx.MockTransport(lambda _: httpx.Response(503, json={})),
    )
    runtime.agent._search = broken  # noqa: SLF001 - deliberate fault injection

    events = research(client, "Acme Corp")

    assert events[-1]["event"] == "research_failed"
    assert events[-1]["data"]["code"] == "no_evidence"
    assert client.get("/api/reports").json() == []  # nothing half-written was saved


def test_timestamps_are_serialised_with_a_utc_offset(client):
    """SQLite returns naive datetimes; without an offset the browser reads
    them as local time and shows a fresh briefing as hours old."""
    report = research(client, "Acme Corp")[-1]["data"]["report"]
    assert report["created_at"].endswith("Z") or "+00:00" in report["created_at"]

    listed = client.get("/api/reports").json()[0]
    assert listed["created_at"].endswith("Z") or "+00:00" in listed["created_at"]
