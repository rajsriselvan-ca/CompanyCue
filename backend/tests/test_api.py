from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import SectionKey, Source
from app.services.provider import (
    ProviderEvent,
    ProviderProgress,
    ProviderQuotaError,
    ProviderResult,
    ResearchProviderError,
)


SECTION_DATA: dict[SectionKey, dict[str, Any]] = {
    "overview": {"overview": "Test Company builds verified testing tools."},
    "key_people": {"key_people": [{"name": "Test Person", "title": "CEO"}]},
    "news": {
        "news": [
            {
                "headline": "Test Company releases a test product",
                "summary": "A deterministic fixture used only by the automated test suite.",
                "date": "2026-09-01",
            }
        ]
    },
    "financials": {
        "financials": {
            "revenue": None,
            "employee_count": None,
            "market_cap": None,
            "yoy_growth": None,
        }
    },
    "risks": {
        "risks": [
            {
                "title": "Fixture risk",
                "details": "This deterministic item verifies rendering and persistence behavior.",
            }
        ]
    },
}


class FakeResearchProvider:
    def __init__(self, failing_section: SectionKey | None = None) -> None:
        self.failing_section = failing_section

    async def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        if section == self.failing_section:
            raise ResearchProviderError("The test provider could not load this section.", retryable=True)
        yield ProviderProgress(received_characters=120)
        yield ProviderResult(
            data=SECTION_DATA[section],
            sources=[Source(title=f"{company_name} source", url="https://example.com/source")],
        )


class QuotaLimitedProvider:
    def __init__(self) -> None:
        self.calls: list[SectionKey] = []

    async def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        self.calls.append(section)
        raise ProviderQuotaError("The configured test key has no available quota.")
        yield  # pragma: no cover - keeps this method an async generator


class RetryOnceProvider(FakeResearchProvider):
    def __init__(self) -> None:
        super().__init__()
        self.attempts: dict[SectionKey, int] = {}

    async def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        self.attempts[section] = self.attempts.get(section, 0) + 1
        if section == "overview" and self.attempts[section] == 1:
            raise ProviderQuotaError("Temporary test limit.", retryable=True)
        async for event in super().stream_section(company_name, section):
            yield event


class LateQuotaProvider(FakeResearchProvider):
    async def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        if section == "financials":
            raise ProviderQuotaError("Temporary test limit.", retryable=True)
        async for event in super().stream_section(company_name, section):
            yield event


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    parsed: list[tuple[str, dict[str, Any]]] = []
    for block in body.strip().split("\n\n"):
        fields = dict(
            line.split(": ", 1)
            for line in block.splitlines()
            if ": " in line
        )
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


@pytest.fixture
def client(tmp_path: Any) -> TestClient:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'briefd-test.db'}",
        gemini_api_key=None,
    )
    with TestClient(create_app(settings=settings, provider=FakeResearchProvider())) as test_client:
        yield test_client


def test_health_reports_provider_configuration(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "gemini_configured": False}


def test_research_streams_in_order_and_persists_report(client: TestClient) -> None:
    response = client.post("/api/research", json={"company_name": "Test Company"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "research_started"
    assert names[-1] == "research_completed"
    assert [data["section"] for name, data in events if name == "section_completed"] == [
        "overview",
        "key_people",
        "news",
        "financials",
        "risks",
    ]

    report = events[-1][1]["report"]
    history = client.get("/api/reports")
    assert history.status_code == 200
    assert history.json()[0]["company_name"] == "Test Company"

    stored = client.get(f"/api/reports/{report['id']}")
    assert stored.status_code == 200
    assert stored.json()["financials"]["market_cap"] is None


def test_partial_section_failure_is_visible_and_saved(tmp_path: Any) -> None:
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'partial.db'}")
    app = create_app(settings=settings, provider=FakeResearchProvider(failing_section="news"))

    with TestClient(app) as test_client:
        response = test_client.post("/api/research", json={"company_name": "Test Company"})
        events = parse_sse(response.text)
        names = [name for name, _ in events]

        assert "section_failed" in names
        assert names[-1] == "research_completed"
        report = events[-1][1]["report"]
        assert report["news"] is None
        assert report["warnings"] == [
            "Recent news is unavailable: The test provider could not load this section."
        ]


def test_quota_failure_stops_without_repeating_all_sections(tmp_path: Any) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'quota.db'}",
        gemini_quota_max_retries=0,
    )
    provider = QuotaLimitedProvider()

    with TestClient(create_app(settings=settings, provider=provider)) as test_client:
        events = parse_sse(
            test_client.post("/api/research", json={"company_name": "Test Company"}).text
        )

    assert [name for name, _ in events] == [
        "research_started",
        "section_started",
        "research_failed",
    ]
    assert events[-1][1]["code"] == "rate_limited"
    assert provider.calls == ["overview"]


def test_temporary_quota_limit_retries_and_completes(tmp_path: Any) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'retry.db'}",
        gemini_quota_max_retries=1,
        gemini_quota_retry_base_seconds=0,
    )
    provider = RetryOnceProvider()

    with TestClient(create_app(settings=settings, provider=provider)) as test_client:
        events = parse_sse(
            test_client.post("/api/research", json={"company_name": "Test Company"}).text
        )

    names = [name for name, _ in events]
    assert "section_retrying" in names
    assert names[-1] == "research_completed"
    assert provider.attempts["overview"] == 2


def test_late_quota_limit_saves_partial_report_without_global_error(tmp_path: Any) -> None:
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'late-quota.db'}",
        gemini_quota_max_retries=0,
    )

    with TestClient(
        create_app(settings=settings, provider=LateQuotaProvider())
    ) as test_client:
        events = parse_sse(
            test_client.post("/api/research", json={"company_name": "Test Company"}).text
        )

    names = [name for name, _ in events]
    assert "research_failed" not in names
    assert names[-1] == "research_completed"
    report = events[-1][1]["report"]
    assert report["overview"] == SECTION_DATA["overview"]["overview"]
    assert report["financials"] is None
    assert report["risks"] is None
    assert len(report["warnings"]) == 2


@pytest.mark.parametrize(
    "company_name",
    ["x", "https://example.com", "hello@example.com", "1111"],
)
def test_invalid_company_input_returns_422(client: TestClient, company_name: str) -> None:
    response = client.post("/api/research", json={"company_name": company_name})

    assert response.status_code == 422


def test_report_delete_uses_expected_status_codes(client: TestClient) -> None:
    streamed = parse_sse(
        client.post("/api/research", json={"company_name": "Test Company"}).text
    )
    report_id = streamed[-1][1]["report"]["id"]

    assert client.delete(f"/api/reports/{report_id}").status_code == 204
    assert client.get(f"/api/reports/{report_id}").status_code == 404
    assert client.delete(f"/api/reports/{report_id}").status_code == 404
