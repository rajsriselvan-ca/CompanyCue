"""The evidence corpus: everything search found, numbered so the model can cite it.

Sections are written only from this corpus. Numbering is what lets a one-line
claim in the briefing be traced back to the URL it came from, and it is also
the cheapest guard against fabrication: a claim the model cannot attach a
number to is a claim we can drop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

from app.agent.search import SearchResult

# Keeps the synthesis prompt inside a sane token budget on the free tier.
MAX_SNIPPET_CHARS = 320
MAX_EVIDENCE_ITEMS = 24


def canonical_url(url: str) -> str:
    """A dedupe key, not a working URL.

    Scheme, `www.`, the query string and a trailing slash are all dropped:
    http and https versions of the same article, or the same page reached with
    different tracking parameters, must collapse to one numbered source.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("", host, path, "", ""))


@dataclass(slots=True)
class EvidenceItem:
    index: int
    result: SearchResult
    queries: list[str] = field(default_factory=list)

    def render(self) -> str:
        snippet = self.result.snippet[:MAX_SNIPPET_CHARS]
        date = f" (published {self.result.published})" if self.result.published else ""
        publisher = f" - {self.result.source}" if self.result.source else ""
        return f"[{self.index}]{publisher} {self.result.title}{date}\n{self.result.url}\n{snippet}"


class EvidenceCorpus:
    def __init__(self, *, max_items: int = MAX_EVIDENCE_ITEMS) -> None:
        self._items: list[EvidenceItem] = []
        self._by_url: dict[str, EvidenceItem] = {}
        self._max_items = max_items

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)

    @property
    def items(self) -> list[EvidenceItem]:
        return list(self._items)

    def add(self, results: list[SearchResult], *, query: str) -> int:
        """Add results, skipping duplicates. Returns how many were new."""
        added = 0
        for result in results:
            if not result.url or not (result.snippet or result.title):
                continue
            key = canonical_url(result.url)
            existing = self._by_url.get(key)
            if existing is not None:
                if query not in existing.queries:
                    existing.queries.append(query)
                continue
            if len(self._items) >= self._max_items:
                break
            item = EvidenceItem(index=len(self._items) + 1, result=result, queries=[query])
            self._items.append(item)
            self._by_url[key] = item
            added += 1
        return added

    def get(self, index: int) -> EvidenceItem | None:
        if 1 <= index <= len(self._items):
            return self._items[index - 1]
        return None

    def render(self) -> str:
        return "\n\n".join(item.render() for item in self._items)

    def sources_for(self, citations: list[int]) -> list[dict[str, str | None]]:
        """Map cited indices back to source links, in order, without duplicates."""
        seen: set[str] = set()
        sources: list[dict[str, str | None]] = []
        for index in citations:
            item = self.get(index)
            if item is None:
                continue
            key = canonical_url(item.result.url)
            if key in seen:
                continue
            seen.add(key)
            sources.append(item.result.as_source())
        return sources
