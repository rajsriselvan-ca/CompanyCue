from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import router
from app.config import Settings
from app.database import Database
from app.services.gemini import GeminiResearchProvider
from app.services.provider import ResearchProvider
from app.services.research import ActiveResearchRegistry, ResearchService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def create_app(
    *, settings: Settings | None = None, provider: ResearchProvider | None = None
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings.database_url)
        await database.initialize()
        app.state.database = database
        app.state.settings = resolved_settings
        app.state.research_registry = ActiveResearchRegistry()
        app.state.research_service = ResearchService(
            provider or GeminiResearchProvider(resolved_settings),
            quota_retry_delays=tuple(
                resolved_settings.gemini_quota_retry_base_seconds * (2**attempt)
                for attempt in range(resolved_settings.gemini_quota_max_retries)
            ),
        )
        yield
        await database.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )
    app.include_router(router, prefix=resolved_settings.api_prefix)

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred. Please try again."},
        )

    return app


app = create_app()
