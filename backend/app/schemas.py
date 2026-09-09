from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SectionKey = Literal["overview", "key_people", "news", "financials", "risks"]

SECTION_ORDER: tuple[SectionKey, ...] = (
    "overview",
    "key_people",
    "news",
    "financials",
    "risks",
)

SECTION_LABELS: dict[SectionKey, str] = {
    "overview": "Company overview",
    "key_people": "Key people",
    "news": "Recent news",
    "financials": "Financial highlights",
    "risks": "Risk factors",
}


class Source(BaseModel):
    title: str
    url: str
    published: str | None = None


# --- Per-section payloads the model must return -------------------------------
# Each section is validated on its own so one malformed section cannot take the
# whole briefing down.


class OverviewSection(BaseModel):
    overview: str | None = None
    citations: list[int] = Field(default_factory=list)


class Person(BaseModel):
    name: str
    title: str


class KeyPeopleSection(BaseModel):
    key_people: list[Person] = Field(default_factory=list, max_length=8)
    citations: list[int] = Field(default_factory=list)


class NewsItem(BaseModel):
    headline: str
    summary: str
    date: str | None = None
    citation: int | None = None


class NewsSection(BaseModel):
    news: list[NewsItem] = Field(default_factory=list, max_length=4)
    citations: list[int] = Field(default_factory=list)


class FinancialHighlights(BaseModel):
    revenue: str | None = None
    employee_count: str | None = None
    market_cap: str | None = None
    yoy_growth: str | None = None


class FinancialsSection(BaseModel):
    financials: FinancialHighlights = Field(default_factory=FinancialHighlights)
    citations: list[int] = Field(default_factory=list)


class RiskItem(BaseModel):
    title: str
    details: str
    citation: int | None = None


class RisksSection(BaseModel):
    risks: list[RiskItem] = Field(default_factory=list, max_length=3)
    citations: list[int] = Field(default_factory=list)


SECTION_MODELS: dict[SectionKey, type[BaseModel]] = {
    "overview": OverviewSection,
    "key_people": KeyPeopleSection,
    "news": NewsSection,
    "financials": FinancialsSection,
    "risks": RisksSection,
}


# --- Stored + transported report ---------------------------------------------


def _assume_utc(value: datetime) -> datetime:
    """SQLite has no timezone type, so timestamps come back naive.

    Left alone they serialise without an offset and the browser reads them as
    local time - a briefing generated a minute ago shows as hours away. They
    are always written in UTC, so that is what we restore.
    """
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class ReportSummary(BaseModel):
    id: UUID
    company_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    _utc_created_at = field_validator("created_at")(_assume_utc)


class Report(BaseModel):
    id: UUID
    company_name: str
    created_at: datetime
    overview: str | None = None
    key_people: list[Person] | None = None
    news: list[NewsItem] | None = None
    financials: FinancialHighlights | None = None
    risks: list[RiskItem] | None = None
    section_sources: dict[str, list[Source]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)

    _utc_created_at = field_validator("created_at")(_assume_utc)


CompanyName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)
]


class ResearchRequest(BaseModel):
    company_name: CompanyName

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        if re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("Company name contains unsupported characters")
        if value.startswith(("http://", "https://")) or "@" in value:
            raise ValueError("Enter a company name, not a URL or email address")
        if len(re.findall(r"[A-Za-z0-9]", value)) < 2:
            raise ValueError("Enter a recognizable company name")
        if re.fullmatch(r"(.)\1{3,}", value, re.IGNORECASE):
            raise ValueError("Enter a recognizable company name")
        return " ".join(value.split())


class HealthResponse(BaseModel):
    status: Literal["ok"]
    llm_provider: str
    search_provider: str
    live_providers_configured: bool
    mock_mode: bool
