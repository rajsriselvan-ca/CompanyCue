"""Streaming Groq chat-completions client.

Written against the raw HTTP API rather than a vendor SDK so that the parts a
reviewer cares about - request construction, the SSE wire format, streamed
tool-call assembly, and error mapping - are visible and testable. Groq speaks
the OpenAI chat-completions dialect, so this client also works unchanged
against any OpenAI-compatible endpoint by changing `base_url` and `model`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from app.agent.errors import (
    ConfigurationError,
    InvalidResponseError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.agent.transport import (
    RETRYABLE_STATUS,
    build_async_client,
    parse_retry_after,
    with_retries,
)

logger = logging.getLogger(__name__)

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ToolCall:
    """A tool invocation the model asked for, reassembled from stream deltas."""

    id: str
    name: str
    arguments: str  # raw JSON text; validated by the dispatcher, not here

    def parsed_arguments(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.arguments or "{}")
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


# --- Stream parts -------------------------------------------------------------
# The client yields these as they arrive so callers can render tokens live.


@dataclass(slots=True)
class TextDelta:
    text: str


@dataclass(slots=True)
class ToolCallsReady:
    tool_calls: list[ToolCall]


@dataclass(slots=True)
class StreamFinished:
    reason: str | None
    usage: dict[str, Any] | None = None


StreamPart = TextDelta | ToolCallsReady | StreamFinished


@dataclass
class _ToolCallBuffer:
    """Groq streams tool calls as fragments keyed by index; we stitch them back."""

    id: str = ""
    name: str = ""
    arguments: str = ""

    def merge(self, fragment: dict[str, Any]) -> None:
        if fragment.get("id"):
            self.id = fragment["id"]
        function = fragment.get("function") or {}
        if function.get("name"):
            self.name += function["name"]
        if function.get("arguments"):
            self.arguments += function["arguments"]


@dataclass(slots=True)
class ChatRequest:
    messages: list[dict[str, Any]]
    model: str
    temperature: float = 0.2
    max_tokens: int = 1600
    tools: Sequence[dict[str, Any]] | None = None
    tool_choice: str | None = None
    # Groq rejects response_format together with tools, so callers pick one:
    # tool-calling for the search phase, JSON mode for the synthesis phase.
    json_mode: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_payload(self, *, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": stream,
            **self.extra,
        }
        if self.tools:
            payload["tools"] = list(self.tools)
            payload["tool_choice"] = self.tool_choice or "auto"
        elif self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload


class GroqClient:
    """Thin, fully-async Groq client with retries and streamed tool calls."""

    provider_name = "Groq"

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        connect_timeout: float,
        read_timeout: float,
        max_retries: int,
        retry_base_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        # A mock transport still needs a syntactically valid Authorization header.
        token = api_key or ("mock-key" if transport is not None else None)
        if not token:
            raise ConfigurationError(
                "Live research is not configured. Set GROQ_API_KEY in the server "
                "environment, or run with MOCK_PROVIDERS=true."
            )
        self._client = build_async_client(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Public API ----------------------------------------------------------

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[StreamPart]:
        """Yield stream parts as the model produces them.

        The connection is established under the retry policy; once the first
        byte of the body is read, failures propagate rather than replaying a
        request whose output the caller has already partly consumed.
        """

        stream_cm, response = await self._open_stream(request)

        buffers: dict[int, _ToolCallBuffer] = {}
        finish_reason: str | None = None
        usage: dict[str, Any] | None = None

        try:
            async for line in response.aiter_lines():
                event = _parse_sse_data_line(line)
                if event is _DONE:
                    break
                if event is None:
                    continue

                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]

                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield TextDelta(content)
                    for fragment in delta.get("tool_calls") or []:
                        index = int(fragment.get("index", 0))
                        buffers.setdefault(index, _ToolCallBuffer()).merge(fragment)
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(
                "The research stream was interrupted. Please try again.", retryable=True
            ) from exc
        finally:
            await stream_cm.__aexit__(None, None, None)

        if buffers:
            yield ToolCallsReady(
                [
                    ToolCall(id=buffer.id or f"call_{index}", name=buffer.name, arguments=buffer.arguments)
                    for index, buffer in sorted(buffers.items())
                    if buffer.name
                ]
            )

        yield StreamFinished(reason=finish_reason, usage=usage)

    async def _open_stream(
        self, request: ChatRequest
    ) -> tuple[Any, httpx.Response]:
        """Open the streaming response under the retry policy.

        Returns the still-open context manager alongside the response so the
        caller closes the connection exactly once, in its own `finally`.
        """

        async def attempt() -> tuple[Any, httpx.Response]:
            stream_cm = self._client.stream(
                "POST", "/chat/completions", json=request.to_payload(stream=True)
            )
            response = await stream_cm.__aenter__()
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", "replace")
                await stream_cm.__aexit__(None, None, None)
                self._raise_for_status(response, body)
            return stream_cm, response

        return await with_retries(
            attempt,
            max_retries=self._max_retries,
            base_delay=self._retry_base_seconds,
            provider=self.provider_name,
        )

    async def complete_json(self, request: ChatRequest) -> dict[str, Any]:
        """Non-streaming JSON call, for steps with nothing to show the user."""

        async def send() -> httpx.Response:
            response = await self._client.post(
                "/chat/completions", json=request.to_payload(stream=False)
            )
            if response.status_code >= 400:
                self._raise_for_status(response, response.text)
            return response

        response = await with_retries(
            send,
            max_retries=self._max_retries,
            base_delay=self._retry_base_seconds,
            provider=self.provider_name,
        )
        try:
            message = response.json()["choices"][0]["message"]
        except (KeyError, IndexError, ValueError) as exc:
            raise InvalidResponseError(
                "The research model returned an unreadable response.", retryable=True
            ) from exc
        return message

    # --- Errors --------------------------------------------------------------

    def _raise_for_status(self, response: httpx.Response, body: str) -> None:
        status = response.status_code
        detail = _extract_error_message(body)

        if status in {401, 403}:
            raise ConfigurationError(
                "The research provider rejected the configured API key. Check GROQ_API_KEY."
            )
        if status == 404:
            raise ConfigurationError(
                "The configured research model is not available to this account. "
                "Check GROQ_MODEL."
            )
        if status == 429:
            raise RateLimitError(
                "The research provider is rate limiting requests. CompanyCue will retry shortly.",
                retry_after=parse_retry_after(response),
            )
        if status == 400 and "context" in detail.lower():
            raise InvalidResponseError(
                "There was too much source material for one request. Try a more specific company name."
            )
        if status in RETRYABLE_STATUS or status >= 500:
            raise ProviderUnavailableError(
                "The research provider is temporarily unavailable. Please try again.",
                retryable=True,
            )
        logger.error("Unexpected %s from %s: %s", status, self.provider_name, detail[:400])
        raise ProviderUnavailableError(
            "The research provider could not complete this request.", retryable=True
        )


# --- SSE line parsing ---------------------------------------------------------

_DONE = object()


def _parse_sse_data_line(line: str) -> dict[str, Any] | object | None:
    """Decode one line of an OpenAI-style SSE body.

    Returns the parsed object, the `_DONE` sentinel, or None for keep-alive
    comments, blank separators and unparseable payloads.
    """
    if not line or line.startswith(":"):
        return None
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload:
        return None
    if payload == "[DONE]":
        return _DONE
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        logger.debug("Skipping unparseable stream chunk: %r", payload[:200])
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_error_message(body: str) -> str:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body or ""
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or "")
    return str(error or "")
