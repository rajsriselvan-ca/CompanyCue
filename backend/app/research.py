"""Application service: runs the agent, persists the result, maps failures.

The agent knows how to research. This layer knows about the database, about
duplicate requests, and about turning an exception into an event a user can
read. Keeping them apart is what lets the agent be tested without a database
and the API be tested without a model.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agent import AgentError, AgentEvent, ResearchAgent
from app.agent.events import RESEARCH_COMPLETED, RESEARCH_FAILED, RESEARCH_READY
from app.repository import ReportRepository, normalize_company_name

logger = logging.getLogger(__name__)


class ActiveResearchRegistry:
    """Stops the same company being researched twice at once.

    Scoped to one API process, which is the right scope for a single-process
    local app. A multi-worker deployment would move this to a shared lock; the
    interface would not change.
    """

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
        *,
        agent: ResearchAgent,
        session_factory: async_sessionmaker,
    ) -> None:
        self._agent = agent
        self._session_factory = session_factory

    async def stream(self, company_name: str) -> AsyncIterator[AgentEvent]:
        try:
            async for event in self._agent.run(company_name):
                if event.name != RESEARCH_READY:
                    yield event
                    continue

                report = await self._persist(event)
                yield AgentEvent(
                    RESEARCH_COMPLETED, {"report": report.model_dump(mode="json")}
                )
        except asyncio.CancelledError:
            # The client went away mid-stream. Nothing is persisted; that is
            # deliberate, a half-written briefing is worse than none.
            logger.info("Research for %r cancelled by the client", company_name)
            raise
        except AgentError as exc:
            logger.info("Research for %r failed: %s", company_name, exc)
            yield AgentEvent(
                RESEARCH_FAILED,
                {"code": exc.code, "message": exc.user_message, "retryable": exc.retryable},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected failure researching %r", company_name)
            yield AgentEvent(
                RESEARCH_FAILED,
                {
                    "code": "internal_error",
                    "message": "Something went wrong while building this briefing. Please try again.",
                    "retryable": True,
                },
            )

    async def _persist(self, event: AgentEvent):
        # A short-lived session, opened only once there is something to write,
        # so a slow research run never holds a connection open.
        async with self._session_factory() as session:
            return await ReportRepository(session).create(
                company_name=event.data["company_name"],
                sections=event.data["sections"],
                section_sources=event.data["section_sources"],
                warnings=event.data["warnings"],
            )
