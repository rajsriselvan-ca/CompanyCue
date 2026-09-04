from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.schemas import (
    FinancialsSection,
    KeyPeopleSection,
    NewsSection,
    OverviewSection,
    RisksSection,
    SectionKey,
    Source,
)
from app.services.provider import (
    InvalidProviderResponseError,
    ProviderConfigurationError,
    ProviderEvent,
    ProviderProgress,
    ProviderQuotaError,
    ProviderResult,
    ResearchProviderError,
    UnresearchableCompanyError,
)

logger = logging.getLogger(__name__)

GROUNDED_SYSTEM_INSTRUCTION = """You are a meticulous sales research analyst. Use Google Search for current, verifiable facts. Never invent names, metrics, events, dates, or risks. Prefer primary company sources, filings, and high-quality reporting. Return only the requested JSON object with no markdown. Use null or an empty array when reliable information is unavailable. Keep the writing concise and useful before a sales call."""

FREE_TIER_SYSTEM_INSTRUCTION = """You are a meticulous sales research analyst operating without live web access. Never imply that information was searched or verified in real time. Never invent names, metrics, events, dates, or risks. Use only facts you are highly confident about, return null or an empty array for time-sensitive or uncertain information, and do not manufacture recent news. Return only the requested JSON object with no markdown. Keep the writing concise and useful before a sales call."""

SECTION_PROMPTS: dict[SectionKey, str] = {
    "overview": """Research {company}. Return {{"overview": string|null, "unresearchable": boolean, "reason": string|null}}. The overview is a 70-110 word briefing covering industry, core products/services, target customers, and market position. Set unresearchable true only when you cannot verify that this is a real, identifiable company.""",
    "key_people": """Research the current leadership of {company}. Return {{"key_people": [{{"name": string, "title": string}}]}}. Include relevant current C-suite and senior leaders only. Verify both name and current title; return an empty array rather than guessing.""",
    "news": """Research the most recent material news about {company}. Return {{"news": [{{"headline": string, "summary": string, "date": "YYYY-MM-DD"|null}}]}}. Return 3-4 items when available, prioritizing acquisitions, earnings, launches, partnerships, layoffs, or leadership changes. Every item must be current and supported by your Google Search results. Do not fill the quota with stale or generic information.""",
    "financials": """Research current financial highlights for {company}. Return {{"financials": {{"revenue": string|null, "employee_count": string|null, "market_cap": string|null, "yoy_growth": string|null}}}}. Include currency and reporting period where relevant. Use null for any metric that is not reliably public; never estimate or fabricate private-company metrics.""",
    "risks": """Research material business risks for {company}. Return {{"risks": [{{"title": string, "details": string}}]}}. Return 2-3 current, evidence-based items such as regulatory scrutiny, security incidents, competitive pressure, litigation, or financial instability. Do not invent speculative risks merely to reach a count.""",
}

SECTION_MODELS: dict[SectionKey, type[BaseModel]] = {
    "overview": OverviewSection,
    "key_people": KeyPeopleSection,
    "news": NewsSection,
    "financials": FinancialsSection,
    "risks": RisksSection,
}


class FullBriefingPayload(BaseModel):
    overview: OverviewSection
    key_people: KeyPeopleSection
    news: NewsSection
    financials: FinancialsSection
    risks: RisksSection
    unresearchable: bool = False
    reason: str | None = None


FREE_TIER_REPORT_PROMPT = """Build a complete sales briefing for {company}. Return one JSON object with this exact nested shape:
{{
  "overview": {{"overview": string|null}},
  "key_people": {{"key_people": [{{"name": string, "title": string}}]}},
  "news": {{"news": []}},
  "financials": {{"financials": {{"revenue": string|null, "employee_count": string|null, "market_cap": string|null, "yoy_growth": string|null}}}},
  "risks": {{"risks": [{{"title": string, "details": string}}]}},
  "unresearchable": boolean,
  "reason": string|null
}}
Use a 70-110 word overview. Include only leadership, financial figures, and risks you are highly confident about. Include the reporting period with financial figures. You have no live web access, so news must be an empty array and uncertain or time-sensitive values must be null or empty. Never invent facts. Set unresearchable true only when you cannot identify a real company with this name."""


class GeminiResearchProvider:
    """Streams provider output and validates it before application use."""

    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemini_model
        self.fallback_model = settings.gemini_fallback_model
        self.google_search_enabled = settings.gemini_google_search_enabled
        self._resolved_model = self.model
        self._free_tier_cache: dict[str, dict[SectionKey, Any]] = {}
        self.api_key = (
            settings.gemini_api_key.get_secret_value()
            if settings.gemini_api_key
            else None
        )

    async def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        if not self.api_key:
            raise ProviderConfigurationError(
                "Live research is not configured. Add GEMINI_API_KEY to the server environment and try again."
            )

        if not self.google_search_enabled:
            async for event in self._stream_free_tier_section(company_name, section):
                yield event
            return

        client = genai.Client(api_key=self.api_key)
        config = self._build_generate_config(section)

        try:
            response_text, sources = "", {}
            while True:
                last_progress = 0
                try:
                    stream = await client.aio.models.generate_content_stream(
                        model=self._resolved_model,
                        contents=self._build_section_prompt(company_name, section),
                        config=config,
                    )
                    async for chunk in stream:
                        text = chunk.text or ""
                        response_text += text
                        self._collect_sources(chunk, sources)
                        if len(response_text) - last_progress >= 80:
                            last_progress = len(response_text)
                            yield ProviderProgress(received_characters=last_progress)
                    break
                except errors.APIError as exc:
                    if self._should_use_fallback(exc):
                        logger.warning(
                            "Gemini model %s is unavailable; switching to configured fallback %s",
                            self._resolved_model,
                            self.fallback_model,
                        )
                        self._resolved_model = self.fallback_model or self._resolved_model
                        response_text, sources = "", {}
                        continue
                    self._raise_provider_error(exc)
        except ResearchProviderError:
            raise
        except Exception as exc:
            raise ResearchProviderError(
                "The live research stream ended unexpectedly. Please try again.",
                retryable=True,
            ) from exc
        finally:
            await client.aio.aclose()

        data = self._parse_and_validate(response_text, section)
        yield ProviderResult(data=data, sources=list(sources.values()))

    async def _stream_free_tier_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]:
        cache_key = " ".join(company_name.casefold().split())
        cached_sections = self._free_tier_cache.get(cache_key)

        if cached_sections is None:
            client = genai.Client(api_key=self.api_key)
            response_text = ""
            last_progress = 0
            try:
                while True:
                    try:
                        stream = await client.aio.models.generate_content_stream(
                            model=self._resolved_model,
                            contents=FREE_TIER_REPORT_PROMPT.format(company=company_name),
                            config=self._build_free_tier_report_config(),
                        )
                        async for chunk in stream:
                            text = chunk.text or ""
                            response_text += text
                            if len(response_text) - last_progress >= 80:
                                last_progress = len(response_text)
                                yield ProviderProgress(
                                    received_characters=last_progress
                                )
                        break
                    except errors.APIError as exc:
                        if self._should_use_fallback(exc):
                            logger.warning(
                                "Gemini model %s is unavailable; switching to configured fallback %s",
                                self._resolved_model,
                                self.fallback_model,
                            )
                            self._resolved_model = (
                                self.fallback_model or self._resolved_model
                            )
                            response_text = ""
                            continue
                        self._raise_provider_error(exc)
            except ResearchProviderError:
                raise
            except Exception as exc:
                raise ResearchProviderError(
                    "The research stream ended unexpectedly. Please try again.",
                    retryable=True,
                ) from exc
            finally:
                await client.aio.aclose()

            cached_sections = self._parse_full_briefing(response_text)
            if len(self._free_tier_cache) >= 32:
                self._free_tier_cache.pop(next(iter(self._free_tier_cache)))
            self._free_tier_cache[cache_key] = cached_sections

        yield ProviderResult(data={section: cached_sections[section]}, sources=[])
        if section == "risks":
            self._free_tier_cache.pop(cache_key, None)

    def _build_generate_config(self, section: SectionKey) -> types.GenerateContentConfig:
        tools = (
            [types.Tool(google_search=types.GoogleSearch())]
            if self.google_search_enabled
            else None
        )
        return types.GenerateContentConfig(
            system_instruction=(
                GROUNDED_SYSTEM_INSTRUCTION
                if self.google_search_enabled
                else FREE_TIER_SYSTEM_INSTRUCTION
            ),
            tools=tools,
            response_mime_type=(
                None if self.google_search_enabled else "application/json"
            ),
            response_schema=(
                None if self.google_search_enabled else SECTION_MODELS[section]
            ),
            temperature=0.1,
            max_output_tokens=2400,
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        )

    @staticmethod
    def _build_free_tier_report_config() -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=FREE_TIER_SYSTEM_INSTRUCTION,
            response_mime_type="application/json",
            response_schema=FullBriefingPayload,
            temperature=0.1,
            max_output_tokens=3200,
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        )

    def _build_section_prompt(self, company_name: str, section: SectionKey) -> str:
        prompt = SECTION_PROMPTS[section].format(company=company_name)
        if self.google_search_enabled:
            return prompt
        return (
            f"{prompt}\n\nFree-tier constraint: you have no live Google Search access. "
            "Do not claim that you searched or verified current information. "
            "For recent news return an empty array. For every other time-sensitive "
            "or uncertain value, return null or an empty array rather than guessing."
        )

    def _should_use_fallback(self, exc: errors.APIError) -> bool:
        return bool(
            getattr(exc, "code", None) == 404
            and self.fallback_model
            and self._resolved_model != self.fallback_model
            and "no longer available" in str(getattr(exc, "message", "")).casefold()
        )

    @staticmethod
    def _raise_provider_error(exc: errors.APIError) -> None:
        code = getattr(exc, "code", None)
        if code in {401, 403}:
            raise ProviderConfigurationError(
                "Gemini rejected the configured API key. Check GEMINI_API_KEY and try again."
            ) from exc
        if code == 404:
            raise ProviderConfigurationError(
                "The configured Gemini model is not available for this API account."
            ) from exc
        if code == 429:
            raise ProviderQuotaError(
                "Gemini's request limit is temporarily busy.", retryable=True
            ) from exc
        raise ResearchProviderError(
            "The live research service could not complete this section. Please try again.",
            retryable=True,
        ) from exc

    @staticmethod
    def _parse_and_validate(response_text: str, section: SectionKey) -> dict[str, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text.strip())
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise InvalidProviderResponseError(
                "Research returned an unreadable response for this section.", retryable=True
            )

        try:
            raw = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise InvalidProviderResponseError(
                "Research returned an unreadable response for this section.", retryable=True
            ) from exc

        if section == "overview" and raw.get("unresearchable") is True:
            raise UnresearchableCompanyError(
                "We could not verify that company. Check the spelling or add a distinguishing word such as its location."
            )

        try:
            validated = SECTION_MODELS[section].model_validate(raw)
        except ValidationError as exc:
            raise InvalidProviderResponseError(
                "Research returned incomplete data for this section.", retryable=True
            ) from exc
        return validated.model_dump(mode="json")

    @staticmethod
    def _parse_full_briefing(response_text: str) -> dict[SectionKey, Any]:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", response_text.strip())
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise InvalidProviderResponseError(
                "Research returned an unreadable response.", retryable=True
            )

        try:
            raw = json.loads(cleaned[start : end + 1])
            validated = FullBriefingPayload.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise InvalidProviderResponseError(
                "Research returned incomplete data. Please try again.", retryable=True
            ) from exc

        if validated.unresearchable:
            raise UnresearchableCompanyError(
                "We could not verify that company. Check the spelling or add a distinguishing word such as its location."
            )

        payload = validated.model_dump(mode="json")
        return {
            "overview": payload["overview"]["overview"],
            "key_people": payload["key_people"]["key_people"],
            "news": payload["news"]["news"],
            "financials": payload["financials"]["financials"],
            "risks": payload["risks"]["risks"],
        }

    @staticmethod
    def _collect_sources(chunk: Any, sources: dict[str, Source]) -> None:
        for candidate in getattr(chunk, "candidates", None) or []:
            metadata = getattr(candidate, "grounding_metadata", None)
            for grounding_chunk in getattr(metadata, "grounding_chunks", None) or []:
                web = getattr(grounding_chunk, "web", None)
                url = getattr(web, "uri", None)
                title = getattr(web, "title", None)
                if isinstance(url, str) and url.startswith(("http://", "https://")):
                    sources[url] = Source(title=title or "Web source", url=url)
