"""SSE framing and the producer pump."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from app.agent.events import AgentEvent
from app.sse import event_stream, format_event


def test_framing_carries_id_event_and_data():
    frame = format_event(event="section_started", data={"section": "news"}, event_id=7)
    assert frame == 'id: 7\nevent: section_started\ndata: {"section":"news"}\n\n'


def test_a_newline_inside_a_value_survives_the_round_trip():
    """A raw newline in `data:` would truncate the event at the client.

    Every frame must decode back to exactly what was sent, whatever the
    section text contains.
    """
    payload = {"text": "line one\nline two", "quote": 'he said "hi"'}
    frame = format_event(event="section_delta", data=payload, event_id=3)

    data_lines = [
        line.removeprefix("data: ") for line in frame.split("\n") if line.startswith("data: ")
    ]
    assert json.loads("\n".join(data_lines)) == payload
    assert frame.endswith("\n\n")  # the blank line that terminates a frame


async def drain(stream: AsyncIterator[str], limit: int) -> list[str]:
    chunks: list[str] = []
    async for chunk in stream:
        chunks.append(chunk)
        if len(chunks) >= limit:
            break
    return chunks


async def test_opens_with_a_retry_hint_then_streams_events():
    async def producer() -> AsyncIterator[AgentEvent]:
        yield AgentEvent("a", {"n": 1})
        yield AgentEvent("b", {"n": 2})

    chunks = [
        chunk
        async for chunk in event_stream(
            producer, heartbeat_seconds=5, client_retry_ms=3000
        )
    ]

    assert chunks[0] == "retry: 3000\n\n"
    assert "id: 1\nevent: a" in chunks[1]
    assert "id: 2\nevent: b" in chunks[2]
    assert len(chunks) == 3  # the stream ends, it does not hang


async def test_emits_a_heartbeat_while_the_producer_is_slow():
    """A twenty-second LLM call must not look like a dead connection."""

    async def producer() -> AsyncIterator[AgentEvent]:
        await asyncio.sleep(0.12)
        yield AgentEvent("done", {})

    chunks = [
        chunk
        async for chunk in event_stream(
            producer, heartbeat_seconds=0.03, client_retry_ms=1000
        )
    ]

    assert chunks.count(": keep-alive\n\n") >= 2
    assert chunks[-1].startswith("id: 1\nevent: done")


async def test_a_crashing_producer_becomes_a_readable_failure_event():
    async def producer() -> AsyncIterator[AgentEvent]:
        yield AgentEvent("stage", {})
        raise RuntimeError("boom")

    chunks = [
        chunk
        async for chunk in event_stream(producer, heartbeat_seconds=5, client_retry_ms=1000)
    ]

    assert "event: research_failed" in chunks[-1]
    assert "internal_error" in chunks[-1]
    assert "boom" not in chunks[-1]  # internals never reach the user


async def test_closing_the_stream_cancels_the_producer():
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def producer() -> AsyncIterator[AgentEvent]:
        try:
            started.set()
            yield AgentEvent("first", {})
            await asyncio.sleep(10)
            yield AgentEvent("never", {})
        except asyncio.CancelledError:
            cancelled.set()
            raise

    stream = event_stream(producer, heartbeat_seconds=5, client_retry_ms=1000)
    await drain(stream, 2)
    await stream.aclose()
    await asyncio.sleep(0.01)

    assert started.is_set()
    assert cancelled.is_set()


async def test_on_finish_runs_even_when_the_client_disconnects():
    released: list[str] = []

    async def producer() -> AsyncIterator[AgentEvent]:
        yield AgentEvent("first", {})
        await asyncio.sleep(10)

    stream = event_stream(
        producer,
        heartbeat_seconds=5,
        client_retry_ms=1000,
        on_finish=lambda: _record(released),
    )
    await drain(stream, 2)
    await stream.aclose()

    assert released == ["released"]


async def _record(sink: list[str]) -> None:
    sink.append("released")
