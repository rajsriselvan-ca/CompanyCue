from __future__ import annotations

import pytest

from app.services.research import ActiveResearchRegistry


@pytest.mark.asyncio
async def test_registry_blocks_duplicate_company_names_until_release() -> None:
    registry = ActiveResearchRegistry()

    assert await registry.acquire("Acme Corp") is True
    assert await registry.acquire("  ACME   CORP ") is False

    await registry.release("acme corp")
    assert await registry.acquire("Acme Corp") is True
