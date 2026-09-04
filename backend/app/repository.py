from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReportRecord
from app.schemas import Report, ReportSummary


def normalize_company_name(company_name: str) -> str:
    return " ".join(company_name.casefold().split())


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        company_name: str,
        sections: dict[str, Any | None],
        section_sources: dict[str, list[dict[str, str]]],
        warnings: list[str],
    ) -> Report:
        record = ReportRecord(
            company_name=company_name,
            normalized_company_name=normalize_company_name(company_name),
            overview=sections.get("overview"),
            key_people=sections.get("key_people"),
            news=sections.get("news"),
            financials=sections.get("financials"),
            risks=sections.get("risks"),
            section_sources=section_sources,
            warnings=warnings,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return self._to_report(record)

    async def list(self) -> list[ReportSummary]:
        result = await self.session.scalars(
            select(ReportRecord).order_by(ReportRecord.created_at.desc())
        )
        return [ReportSummary.model_validate(record) for record in result.all()]

    async def get(self, report_id: str) -> Report | None:
        record = await self.session.get(ReportRecord, report_id)
        return self._to_report(record) if record else None

    async def delete(self, report_id: str) -> bool:
        result = await self.session.execute(
            delete(ReportRecord).where(ReportRecord.id == report_id)
        )
        await self.session.commit()
        return bool(result.rowcount)

    @staticmethod
    def _to_report(record: ReportRecord) -> Report:
        return Report.model_validate(
            {
                "id": record.id,
                "company_name": record.company_name,
                "created_at": record.created_at,
                "overview": record.overview,
                "key_people": record.key_people,
                "news": record.news,
                "financials": record.financials,
                "risks": record.risks,
                "section_sources": record.section_sources or {},
                "warnings": record.warnings or [],
            }
        )
