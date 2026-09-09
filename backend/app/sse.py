"""Server-Sent Events framing and the producer/consumer pump.

Two things make this more than a `yield f"data: {json}"` loop:

1. **Framing correctness.** `data:` is line-oriented, so any newline inside a
   payload has to become its own `data:` line or the client silently loses the
   rest of the event. Every event carries a monotonic `id:` and a named
   `event:`, and the stream opens with a `retry:` hint.

2. **Decoupling the producer from the socket.** The agent can spend twenty
   seconds inside one LLM call. If the response body awaited it directly there
   would be nothing to send during that gap, and proxies (and some corporate
   networks) drop an idle connection. So the agent runs in its own task feeding
   a bounded queue, and the body loop emits a heartbeat comment whenever the
   queue stays quiet. The bound gives backpressure: a slow client slows the
   producer instead of growing memory without limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.agent.events import AgentEvent

logger = logging.getLogger(__name__)

QUEUE_MAXSIZE = 64

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    # Tells nginx and friends not to buffer the response into uselessness.
    "X-Accel-Buffering": "no",
}

_STREAM_END = object()


def format_event(*, event: str, data: dict[str, Any], event_id: int) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    # A payload containing a newline must be split across `data:` lines.
    body = "\n".join(f"data: {line}" for line in payload.split("\n"))
    return f"id: {event_id}\nevent: {event}\n{body}\n\n"


def format_comment(text: str = "keep-alive") -> str:
    return f": {text}\n\n"


async def event_stream(
    producer: Callable[[], AsyncIterator[AgentEvent]],
    *,
    heartbeat_seconds: float,
    client_retry_ms: int,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    on_finish: Callable[[], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue(maxsize=QUEUE_MAXSIZE)

    async def pump() -> None:
        try:
            async for event in producer():
                await queue.put(event)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - a bug here must still close the stream
            logger.exception("Research producer crashed")
            await queue.put(
                AgentEvent(
                    "research_failed",
                    {
                        "code": "internal_error",
                        "message": "The research stream stopped unexpectedly. Please try again.",
                        "retryable": True,
                    },
                )
            )
        finally:
            await queue.put(_STREAM_END)

    task = asyncio.create_task(pump(), name="sse-producer")
    event_id = 0

    try:
        yield f"retry: {client_retry_ms}\n\n"
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
            except (asyncio.TimeoutError, TimeoutError):
                # Idle gap: prove the connection is alive, and take the chance
                # to notice a client that went away without a FIN.
                if is_disconnected is not None and await is_disconnected():
                    break
                yield format_comment()
                continue

            if item is _STREAM_END:
                break

            assert isinstance(item, AgentEvent)
            event_id += 1
            yield format_event(event=item.name, data=item.data, event_id=event_id)
    finally:
        # Reached on normal completion and on client disconnect alike (Starlette
        # cancels the body task, which raises through the yield above). Either
        # way the agent task is torn down, closing its upstream connections.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if on_finish is not None:
            await on_finish()
