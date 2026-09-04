from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.gemini import GeminiResearchProvider
from app.services.provider import InvalidProviderResponseError, UnresearchableCompanyError


def test_financial_parser_preserves_unavailable_values_as_null() -> None:
    result = GeminiResearchProvider._parse_and_validate(
        '```json\n{"financials":{"revenue":"$2B (FY2025)","employee_count":null,"market_cap":null,"yoy_growth":"12%"}}\n```',
        "financials",
    )

    assert result["financials"]["revenue"] == "$2B (FY2025)"
    assert result["financials"]["employee_count"] is None
    assert result["financials"]["market_cap"] is None


def test_unresearchable_company_is_a_specific_error() -> None:
    with pytest.raises(UnresearchableCompanyError):
        GeminiResearchProvider._parse_and_validate(
            '{"overview":null,"unresearchable":true,"reason":"No verified entity"}',
            "overview",
        )


def test_malformed_provider_output_is_not_exposed_as_data() -> None:
    with pytest.raises(InvalidProviderResponseError):
        GeminiResearchProvider._parse_and_validate("not-json", "overview")


def test_retired_primary_model_uses_the_configured_fallback_only_for_retirement() -> None:
    provider = GeminiResearchProvider(
        Settings(gemini_model="gemini-2.5-flash", gemini_fallback_model="gemini-3.6-flash")
    )

    retired = SimpleNamespace(code=404, message="This model is no longer available to new users")
    ordinary_not_found = SimpleNamespace(code=404, message="Model was not found")

    assert provider._should_use_fallback(retired) is True  # type: ignore[arg-type]
    assert provider._should_use_fallback(ordinary_not_found) is False  # type: ignore[arg-type]


def test_free_tier_config_does_not_attach_google_search() -> None:
    provider = GeminiResearchProvider(
        Settings(
            gemini_model="gemini-3.7-flash",
            gemini_fallback_model="gemini-3.7-flash",
            gemini_google_search_enabled=False,
        )
    )

    config = provider._build_generate_config("overview")

    assert config.tools is None
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
    assert "without live web access" in str(config.system_instruction)
    assert "recent news return an empty array" in provider._build_section_prompt(
        "Acme", "news"
    )


def test_grounded_config_attaches_google_search_only_when_enabled() -> None:
    provider = GeminiResearchProvider(Settings(gemini_google_search_enabled=True))

    config = provider._build_generate_config("overview")

    assert config.tools is not None
    assert len(config.tools) == 1
    assert config.response_mime_type is None
    assert "Use Google Search" in str(config.system_instruction)


def test_free_tier_full_briefing_is_validated_and_flattened() -> None:
    result = GeminiResearchProvider._parse_full_briefing(
        """{
          "overview": {"overview": "Acme builds reliable widgets."},
          "key_people": {"key_people": [{"name": "Ada Example", "title": "CEO"}]},
          "news": {"news": []},
          "financials": {"financials": {"revenue": null, "employee_count": null, "market_cap": null, "yoy_growth": null}},
          "risks": {"risks": [{"title": "Competition", "details": "A deterministic test risk."}]},
          "unresearchable": false,
          "reason": null
        }"""
    )

    assert result["overview"] == "Acme builds reliable widgets."
    assert result["key_people"] == [{"name": "Ada Example", "title": "CEO"}]
    assert result["news"] == []
    assert result["financials"]["revenue"] is None
    assert result["risks"][0]["title"] == "Competition"

    config = GeminiResearchProvider._build_free_tier_report_config()
    assert config.response_mime_type == "application/json"
    assert config.response_schema is not None
