from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.repository import ReportRepository
from app.schemas import HealthResponse, Report, ReportSummary, ResearchRequest
from app.sse import SSE_HEADERS, event_stream

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        llm_provider=f"groq:{settings.groq_model}",
        search_provider="serpapi",
        live_providers_configured=settings.live_providers_configured,
        mock_mode=settings.mock_providers,
    )


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(request: Request) -> list[ReportSummary]:
    async with request.app.state.database.session_factory() as session:
        return await ReportRepository(session).list()


@router.get("/reports/{report_id}", response_model=Report)
async def get_report(report_id: UUID, request: Request) -> Report:
    async with request.app.state.database.session_factory() as session:
        report = await ReportRepository(session).get(str(report_id))
    if report is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: UUID, request: Request) -> Response:
    async with request.app.state.database.session_factory() as session:
        deleted = await ReportRepository(session).delete(str(report_id))
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/research")
async def research(payload: ResearchRequest, request: Request) -> StreamingResponse:
    """Start a research run and stream it back as Server-Sent Events.

    POST rather than GET because the browser's `EventSource` cannot send a
    body; the frontend reads the response stream directly, which also gives it
    a real `AbortController` for cancellation.
    """
    registry = request.app.state.research_registry
    company_name = payload.company_name

    # Claimed before the response starts so a duplicate gets a clean 409 rather
    # than a stream that immediately errors.
    if not await registry.acquire(company_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A briefing for {company_name} is already being generated.",
        )

    settings = request.app.state.settings
    service = request.app.state.research_service

    return StreamingResponse(
        event_stream(
            lambda: service.stream(company_name),
            heartbeat_seconds=settings.sse_heartbeat_seconds,
            client_retry_ms=settings.sse_client_retry_ms,
            is_disconnected=request.is_disconnected,
            on_finish=lambda: registry.release(company_name),
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
