from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas import SectionKey, Source


class ResearchProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.user_message = message
        self.retryable = retryable


class ProviderConfigurationError(ResearchProviderError):
    pass


class ProviderQuotaError(ResearchProviderError):
    pass


class UnresearchableCompanyError(ResearchProviderError):
    pass


class InvalidProviderResponseError(ResearchProviderError):
    pass


@dataclass(frozen=True)
class ProviderProgress:
    received_characters: int


@dataclass(frozen=True)
class ProviderResult:
    data: dict[str, Any]
    sources: list[Source]


ProviderEvent = ProviderProgress | ProviderResult


class ResearchProvider(Protocol):
    def stream_section(
        self, company_name: str, section: SectionKey
    ) -> AsyncIterator[ProviderEvent]: ...
