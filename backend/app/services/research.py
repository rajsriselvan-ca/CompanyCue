from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.repository import ReportRepository, normalize_company_name
from app.schemas import SectionKey
from app.services.provider import (
    ProviderConfigurationError,
    ProviderProgress,
    ProviderQuotaError,
    ProviderResult,
    ResearchProvider,
    ResearchProviderError,
    UnresearchableCompanyError,
)

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


@dataclass(frozen=True)
class ResearchEvent:
    name: str
    data: dict[str, Any]


class ActiveResearchRegistry:
    """Prevents duplicate in-flight research in this API process."""

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._lock = asyncio.Lock()

    async def acquire(self, company_name: str) -> bool:
        key = normalize_company_name(company_name)
        async with self._lock:
            if key in self._active:
                return False
            self._active.add(key)
            return True

    async def release(self, company_name: str) -> None:
        async with self._lock:
            self._active.discard(normalize_company_name(company_name))


class ResearchService:
    def __init__(
        self,
        provider: ResearchProvider,
        *,
        quota_retry_delays: tuple[float, ...] = (10.0, 20.0),
    ) -> None:
        self.provider = provider
        self.quota_retry_delays = quota_retry_delays

    async def stream(
        self,
        *,
        company_name: str,
        repository: ReportRepository,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[ResearchEvent]:
        yield ResearchEvent(
            "research_started",
            {"company_name": company_name, "total_sections": len(SECTION_ORDER)},
        )

        sections: dict[str, Any | None] = {
            section: None for section in SECTION_ORDER
        }
        section_sources: dict[str, list[dict[str, str]]] = {}
        warnings: list[str] = []
        completed_sections = 0

        stop_after_section = False
        for index, section in enumerate(SECTION_ORDER, start=1):
            if await is_disconnected():
                return

            yield ResearchEvent(
                "section_started",
                {
                    "section": section,
                    "label": SECTION_LABELS[section],
                    "index": index,
                    "total": len(SECTION_ORDER),
                },
            )

            try:
                for attempt in range(len(self.quota_retry_delays) + 1):
                    try:
                        async for provider_event in self.provider.stream_section(
                            company_name, section
                        ):
                            if await is_disconnected():
                                return
                            if isinstance(provider_event, ProviderProgress):
                                yield ResearchEvent(
                                    "section_progress",
                                    {
                                        "section": section,
                                        "received_characters": provider_event.received_characters,
                                    },
                                )
                            elif isinstance(provider_event, ProviderResult):
                                section_data = provider_event.data.get(section)
                                sections[section] = section_data
                                section_sources[section] = [
                                    source.model_dump(mode="json")
                                    for source in provider_event.sources
                                ]
                                completed_sections += 1
                                yield ResearchEvent(
                                    "section_completed",
                                    {
                                        "section": section,
                                        "data": section_data,
                                        "sources": section_sources[section],
                                    },
                                )
                        break
                    except ProviderQuotaError:
                        if attempt >= len(self.quota_retry_delays):
                            raise
                        delay = self.quota_retry_delays[attempt]
                        yield ResearchEvent(
                            "section_retrying",
                            {
                                "section": section,
                                "attempt": attempt + 1,
                                "delay_seconds": delay,
                                "message": "Free-tier capacity is busy. Briefd is waiting and will retry automatically.",
                            },
                        )
                        await asyncio.sleep(delay)
                        if await is_disconnected():
                            return
            except UnresearchableCompanyError as exc:
                yield ResearchEvent(
                    "research_failed",
                    {
                        "code": "invalid_input",
                        "message": exc.user_message,
                        "retryable": False,
                    },
                )
                return
            except ProviderConfigurationError as exc:
                yield ResearchEvent(
                    "research_failed",
                    {
                        "code": "configuration_error",
                        "message": exc.user_message,
                        "retryable": False,
                    },
                )
                return
            except ProviderQuotaError as exc:
                if completed_sections == 0:
                    yield ResearchEvent(
                        "research_failed",
                        {
                            "code": "rate_limited",
                            "message": "Gemini's free-tier request limit is still busy after automatic retries. Wait about a minute and try again.",
                            "retryable": True,
                        },
                    )
                    return

                remaining_sections = SECTION_ORDER[index - 1 :]
                for unavailable_section in remaining_sections:
                    warning = (
                        f"{SECTION_LABELS[unavailable_section]} is unavailable: "
                        "Gemini's free-tier limit was reached after automatic retries."
                    )
                    warnings.append(warning)
                    yield ResearchEvent(
                        "section_failed",
                        {
                            "section": unavailable_section,
                            "message": warning,
                            "retryable": exc.retryable,
                        },
                    )
                stop_after_section = True
            except ResearchProviderError as exc:
                warning = f"{SECTION_LABELS[section]} is unavailable: {exc.user_message}"
                warnings.append(warning)
                yield ResearchEvent(
                    "section_failed",
                    {
                        "section": section,
                        "message": warning,
                        "retryable": exc.retryable,
                    },
                )

            if stop_after_section:
                break

        if completed_sections == 0:
            yield ResearchEvent(
                "research_failed",
                {
                    "code": "provider_error",
                    "message": "Research could not be completed right now. Please try again shortly.",
                    "retryable": True,
                },
            )
            return

        if await is_disconnected():
            return

        report = await repository.create(
            company_name=company_name,
            sections=sections,
            section_sources=section_sources,
            warnings=warnings,
        )
        yield ResearchEvent(
            "research_completed", {"report": report.model_dump(mode="json")}
        )
