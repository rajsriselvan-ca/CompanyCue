from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True)
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )
        if url.startswith("sqlite"):
            self._configure_sqlite()

    def _configure_sqlite(self) -> None:
        @event.listens_for(self.engine.sync_engine, "connect")
        def _pragmas(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL lets the history reads run while a research write is in flight.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    async def initialize(self) -> None:
        from app import models  # noqa: F401  (registers the mapping)

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(text("PRAGMA optimize"))

    async def dispose(self) -> None:
        await self.engine.dispose()
