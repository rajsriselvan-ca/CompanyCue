from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from app.agent.errors import ProviderUnavailableError, RateLimitError

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def parse_retry_after(response: httpx.Response) -> float | None:
    """Honour the server's own backoff hint when it gives one."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None  # HTTP-date form; our own backoff is a fine substitute.


def backoff_delay(attempt: int, base: float) -> float:
    """Exponential backoff with full jitter, so retries do not synchronise."""
    return random.uniform(0, base * (2**attempt))


async def with_retries(
    operation: Callable[[], Awaitable[T]],
    *,
    max_retries: int,
    base_delay: float,
    provider: str,
) -> T:
    """Run `operation`, retrying transport faults and retryable status codes.

    Only used for requests we can safely replay from the start. A streaming
    response that has already emitted bytes is never retried here - the caller
    would have to reconcile a partial body, and silently restarting a half-read
    stream is how duplicated content reaches users.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except RateLimitError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            delay = exc.retry_after if exc.retry_after is not None else backoff_delay(attempt, base_delay)
        except ProviderUnavailableError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise
            delay = backoff_delay(attempt, base_delay)
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= max_retries:
                raise ProviderUnavailableError(
                    f"{provider} could not be reached. Please try again.", retryable=True
                ) from exc
            delay = backoff_delay(attempt, base_delay)

        logger.warning(
            "%s attempt %d/%d failed (%s); retrying in %.2fs",
            provider,
            attempt + 1,
            max_retries + 1,
            type(last_error).__name__,
            delay,
        )
        await asyncio.sleep(delay)

    # Unreachable: the loop either returns or raises.
    raise ProviderUnavailableError(f"{provider} could not be reached.", retryable=True)


def build_async_client(
    *,
    base_url: str,
    headers: dict[str, str],
    connect_timeout: float,
    read_timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(
            connect=connect_timeout, read=read_timeout, write=connect_timeout, pool=connect_timeout
        ),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        transport=transport,
    )
