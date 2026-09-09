"""SerpAPI client and the evidence corpus built from its results."""

from __future__ import annotations

import json

import httpx
import pytest

from app.agent.errors import ConfigurationError, ProviderUnavailableError, RateLimitError
from app.agent.evidence import EvidenceCorpus, canonical_url
from app.agent.search import SearchResult
from tests.conftest import make_search


async def test_parses_knowledge_panel_and_organic_results():
    body = {
        "knowledge_graph": {
            "title": "Acme",
            "description": "Acme makes widgets.",
            "source": {"link": "https://en.wikipedia.org/wiki/Acme"},
            "attributes": {"Founded": "1999"},
        },
        "organic_results": [
            {
                "title": "Acme - Home",
                "link": "https://acme.com",
                "snippet": "Widgets for everyone",
                "date": "Jan 2, 2026",
            },
            {"title": "No link here", "snippet": "dropped"},
        ],
    }
    client = make_search(lambda _: httpx.Response(200, json=body))

    results = await client.search_web("acme")

    assert [result.title for result in results] == ["Acme", "Acme - Home"]
    assert "Founded: 1999" in results[0].snippet
    assert results[1].published == "Jan 2, 2026"
    await client.aclose()


async def test_news_search_requests_recent_results_only():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request.url.params)
        return httpx.Response(
            200,
            json={
                "news_results": [
                    {
                        "title": "Acme raises $50M",
                        "link": "https://news.example/acme",
                        "snippet": "Series C",
                        "date": "Aug 1, 2026",
                        "source": "Example News",
                    }
                ]
            },
        )

    client = make_search(handler)
    results = await client.search_news("acme funding")

    # The recency filter is what separates "recent news" from "any news".
    assert captured["tbm"] == "nws"
    assert captured["tbs"] == "qdr:y"
    assert results[0].source == "Example News"
    assert results[0].published == "Aug 1, 2026"
    await client.aclose()


@pytest.mark.parametrize(
    ("status", "expected"),
    [(401, ConfigurationError), (429, RateLimitError), (500, ProviderUnavailableError)],
)
async def test_maps_status_codes(status, expected):
    client = make_search(lambda _: httpx.Response(status, json={}))
    with pytest.raises(expected):
        await client.search_web("acme")
    await client.aclose()


async def test_empty_results_are_not_an_error():
    client = make_search(lambda _: httpx.Response(200, json={"organic_results": []}))
    assert await client.search_web("acme") == []
    await client.aclose()


# --- Evidence corpus ---------------------------------------------------------


def result(url: str, title: str = "t", snippet: str = "s") -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


def test_canonical_url_ignores_scheme_www_query_and_trailing_slash():
    assert canonical_url("https://www.acme.com/about/?utm_source=x") == canonical_url(
        "http://acme.com/about"
    )


def test_corpus_numbers_items_and_deduplicates_across_queries():
    corpus = EvidenceCorpus()

    assert corpus.add([result("https://acme.com/a"), result("https://acme.com/b")], query="q1") == 2
    # Same page, different query string and www prefix: not a new source.
    assert corpus.add([result("https://www.acme.com/a?ref=1")], query="q2") == 0

    assert len(corpus) == 2
    assert [item.index for item in corpus.items] == [1, 2]
    assert corpus.items[0].queries == ["q1", "q2"]


def test_corpus_respects_its_cap():
    corpus = EvidenceCorpus(max_items=2)
    corpus.add([result(f"https://acme.com/{index}") for index in range(5)], query="q")
    assert len(corpus) == 2


def test_sources_for_maps_citations_back_to_links_and_drops_unknown_numbers():
    corpus = EvidenceCorpus()
    corpus.add(
        [result("https://acme.com/a", "A"), result("https://acme.com/b", "B")], query="q"
    )

    sources = corpus.sources_for([2, 99, 1, 2])

    assert [source["title"] for source in sources] == ["B", "A"]


def test_render_includes_the_index_the_model_must_cite():
    corpus = EvidenceCorpus()
    corpus.add([result("https://acme.com/a", "Acme home", "Widgets")], query="q")
    rendered = corpus.render()
    assert rendered.startswith("[1]")
    assert "https://acme.com/a" in rendered
