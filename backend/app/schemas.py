from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

SectionKey = Literal["overview", "key_people", "news", "financials", "risks"]


class Source(BaseModel):
    title: str
    url: str


class OverviewSection(BaseModel):
    overview: str | None = None


class Person(BaseModel):
    name: str
    title: str


class KeyPeopleSection(BaseModel):
    key_people: list[Person] = Field(default_factory=list)


class NewsItem(BaseModel):
    headline: str
    summary: str
    date: str | None = None


class NewsSection(BaseModel):
    news: list[NewsItem] = Field(default_factory=list, max_length=4)


class FinancialHighlights(BaseModel):
    revenue: str | None = None
    employee_count: str | None = None
    market_cap: str | None = None
    yoy_growth: str | None = None


class FinancialsSection(BaseModel):
    financials: FinancialHighlights = Field(default_factory=FinancialHighlights)


class RiskItem(BaseModel):
    title: str
    details: str


class RisksSection(BaseModel):
    risks: list[RiskItem] = Field(default_factory=list, max_length=3)


class ReportSummary(BaseModel):
    id: UUID
    company_name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


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


CompanyName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]


class ResearchRequest(BaseModel):
    company_name: CompanyName

    @field_validator("company_name")
    @classmethod
    def validate_company_name(cls, value: str) -> str:
        if re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("Company name contains unsupported characters")
        if value.startswith(("http://", "https://")) or "@" in value:
            raise ValueError("Enter a company name, not a URL or email address")
        letters = re.findall(r"[A-Za-z]", value)
        if len(letters) < 2 or re.fullmatch(r"(.)\1{3,}", value, re.IGNORECASE):
            raise ValueError("Enter a recognizable company name")
        return " ".join(value.split())


class HealthResponse(BaseModel):
    status: Literal["ok"]
    gemini_configured: bool
