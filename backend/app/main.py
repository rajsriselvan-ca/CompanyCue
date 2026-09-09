from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent import AgentRuntime, build_runtime
from app.api import router
from app.config import Settings
from app.database import Database
from app.research import ActiveResearchRegistry, ResearchService

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def create_app(
    *, settings: Settings | None = None, runtime: AgentRuntime | None = None
) -> FastAPI:
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings.database_url)
        await database.initialize()
        agent_runtime = runtime or build_runtime(resolved_settings)

        app.state.settings = resolved_settings
        app.state.database = database
        app.state.agent_runtime = agent_runtime
        app.state.research_registry = ActiveResearchRegistry()
        app.state.research_service = ResearchService(
            agent=agent_runtime.agent, session_factory=database.session_factory
        )

        if resolved_settings.mock_providers:
            logger.warning("MOCK_PROVIDERS is on: using recorded responses, not live APIs.")
        elif not resolved_settings.live_providers_configured:
            logger.warning(
                "GROQ_API_KEY and/or SERPAPI_API_KEY are unset. Research requests will "
                "return a configuration error until they are supplied."
            )
        try:
            yield
        finally:
            await agent_runtime.aclose()
            await database.dispose()

    app = FastAPI(title=resolved_settings.app_name, version="1.0.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Accept", "Last-Event-ID"],
    )
    app.include_router(router, prefix=resolved_settings.api_prefix)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic's own message is readable once the "Value error, " prefix is
        # dropped; the frontend shows it verbatim next to the search box.
        first = exc.errors()[0] if exc.errors() else {}
        message = str(first.get("msg", "")).removeprefix("Value error, ")
        return JSONResponse(
            status_code=422,
            content={"detail": message or "Check the company name and try again."},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected server error occurred. Please try again."},
        )

    return app


app = create_app()
