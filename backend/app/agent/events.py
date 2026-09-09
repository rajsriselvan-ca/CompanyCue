from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class AgentEvent:
    """One thing worth telling the user about, on its way to the SSE stream."""

    name: str
    data: dict[str, Any] = field(default_factory=dict)


# Event names are part of the public API contract; the frontend switches on them
# and the README documents them.
RESEARCH_STARTED = "research_started"
STAGE = "stage"
TOOL_CALL = "tool_call"
TOOL_RESULT = "tool_result"
SECTION_STARTED = "section_started"
SECTION_DELTA = "section_delta"
SECTION_COMPLETED = "section_completed"
SECTION_FAILED = "section_failed"
RESEARCH_READY = "research_ready"
RESEARCH_COMPLETED = "research_completed"
RESEARCH_FAILED = "research_failed"
