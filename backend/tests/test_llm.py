"""Behaviour of the Groq client: wire format in, stream parts out."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agent.errors import ConfigurationError, ProviderUnavailableError, RateLimitError
from app.agent.llm import StreamFinished, TextDelta, ToolCallsReady
from tests.conftest import make_llm, simple_request


def sse(*payloads: dict) -> bytes:
    body = b"".join(f"data: {json.dumps(payload)}\n\n".encode() for payload in payloads)
    return body + b"data: [DONE]\n\n"


def chunk(delta: dict, finish: str | None = None) -> dict:
    return {"choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


async def collect(client, request):
    return [part async for part in client.stream_chat(request)]


async def test_streams_text_deltas_in_order():
    body = sse(
        chunk({"content": "Acme "}),
        chunk({"content": "makes "}),
        chunk({"content": "widgets."}),
        chunk({}, finish="stop"),
    )
    client = make_llm(lambda _: httpx.Response(200, content=body))

    parts = await collect(client, simple_request())

    assert [part.text for part in parts if isinstance(part, TextDelta)] == [
        "Acme ",
        "makes ",
        "widgets.",
    ]
    assert isinstance(parts[-1], StreamFinished)
    assert parts[-1].reason == "stop"
    await client.aclose()


async def test_assembles_tool_calls_split_across_chunks():
    """Groq sends a tool call's arguments as many fragments; they must rejoin."""
    body = sse(
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "call_a",
                        "function": {"name": "web_", "arguments": ""},
                    }
                ]
            }
        ),
        chunk({"tool_calls": [{"index": 0, "function": {"name": "search"}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": '{"que'}}]}),
        chunk({"tool_calls": [{"index": 0, "function": {"arguments": 'ry": "acme"}'}}]}),
        chunk(
            {
                "tool_calls": [
                    {
                        "index": 1,
                        "id": "call_b",
                        "function": {"name": "news_search", "arguments": '{"query":"acme news"}'},
                    }
                ]
            }
        ),
        chunk({}, finish="tool_calls"),
    )
    client = make_llm(lambda _: httpx.Response(200, content=body))

    parts = await collect(client, simple_request())
    ready = next(part for part in parts if isinstance(part, ToolCallsReady))

    assert [(call.id, call.name) for call in ready.tool_calls] == [
        ("call_a", "web_search"),
        ("call_b", "news_search"),
    ]
    assert ready.tool_calls[0].parsed_arguments() == {"query": "acme"}
    await client.aclose()


async def test_ignores_comments_and_unparseable_chunks():
    body = (
        b": keep-alive\n\n"
        + f"data: {json.dumps(chunk({'content': 'ok'}))}\n\n".encode()
        + b"data: {not json}\n\n"
        + b"\n"
        + b"data: [DONE]\n\n"
    )
    client = make_llm(lambda _: httpx.Response(200, content=body))

    parts = await collect(client, simple_request())

    assert [part.text for part in parts if isinstance(part, TextDelta)] == ["ok"]
    await client.aclose()


async def test_tools_and_json_mode_are_mutually_exclusive():
    """Groq rejects response_format alongside tools, so we never send both."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, content=sse(chunk({}, finish="stop")))

    client = make_llm(handler)
    await collect(
        client,
        simple_request(tools=[{"type": "function", "function": {"name": "x"}}], json_mode=True),
    )

    assert "tools" in captured
    assert "response_format" not in captured
    await client.aclose()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ConfigurationError),
        (403, ConfigurationError),
        (404, ConfigurationError),
        (429, RateLimitError),
        (503, ProviderUnavailableError),
    ],
)
async def test_maps_status_codes_to_typed_errors(status, expected):
    client = make_llm(
        lambda _: httpx.Response(status, json={"error": {"message": "nope"}})
    )
    with pytest.raises(expected):
        await collect(client, simple_request())
    await client.aclose()


async def test_rate_limit_carries_retry_after_hint():
    client = make_llm(
        lambda _: httpx.Response(429, headers={"retry-after": "7"}, json={"error": {}})
    )
    with pytest.raises(RateLimitError) as caught:
        await collect(client, simple_request())
    assert caught.value.retry_after == 7.0
    await client.aclose()


async def test_retries_a_failed_connection_then_succeeds():
    attempts = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, content=sse(chunk({"content": "recovered"})))

    client = make_llm(handler, max_retries=2)
    parts = await collect(client, simple_request())

    assert attempts["count"] == 2
    assert [part.text for part in parts if isinstance(part, TextDelta)] == ["recovered"]
    await client.aclose()


async def test_missing_key_without_a_transport_is_a_configuration_error():
    with pytest.raises(ConfigurationError):
        make_llm(lambda _: httpx.Response(200), transport=None)
