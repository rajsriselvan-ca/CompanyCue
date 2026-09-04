from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from app.repository import ReportRepository
from app.schemas import HealthResponse, Report, ReportSummary, ResearchRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def encode_sse(*, event: str, data: dict[str, object], event_id: int) -> str:
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok", gemini_configured=request.app.state.settings.gemini_api_key is not None
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
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: UUID, request: Request) -> Response:
    async with request.app.state.database.session_factory() as session:
        deleted = await ReportRepository(session).delete(str(report_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/research")
async def research(payload: ResearchRequest, request: Request) -> StreamingResponse:
    registry = request.app.state.research_registry
    if not await registry.acquire(payload.company_name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Research is already running for this company",
        )

    async def event_stream() -> AsyncIterator[str]:
        event_id = 0
        try:
            async with request.app.state.database.session_factory() as session:
                repository = ReportRepository(session)
                async for research_event in request.app.state.research_service.stream(
                    company_name=payload.company_name,
                    repository=repository,
                    is_disconnected=request.is_disconnected,
                ):
                    event_id += 1
                    yield encode_sse(
                        event=research_event.name,
                        data=research_event.data,
                        event_id=event_id,
                    )
        except Exception:
            logger.exception("Unhandled research stream failure")
            event_id += 1
            yield encode_sse(
                event="research_failed",
                data={
                    "code": "internal_error",
                    "message": "The research stream stopped unexpectedly. Please try again.",
                    "retryable": True,
                },
                event_id=event_id,
            )
        finally:
            await registry.release(payload.company_name)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
