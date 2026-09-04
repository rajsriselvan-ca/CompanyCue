from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Index, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ReportRecord(Base):
    __tablename__ = "reports"
    __table_args__ = (Index("idx_reports_created_at", "created_at"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    normalized_company_name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    overview: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    key_people: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    news: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    financials: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    risks: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    section_sources: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
