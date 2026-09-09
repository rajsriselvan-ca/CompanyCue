"""Recorded-response transports for offline runs and tests.

These are injected as `httpx` transports, not as fake clients. That matters:
`GroqClient` and `SerpApiSearchClient` build the same requests, parse the
same SSE frames, assemble the same streamed tool calls and map the same status
codes whether they are talking to Groq or to this module. Nothing in the agent,
the prompts or the streaming pipeline is bypassed - only the socket is.

Enable with MOCK_PROVIDERS=true. The test suite uses the same transports.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

# Small delay per chunk so a local demo looks like a real stream rather than an
# instant dump. Tests set MOCK_STREAM_DELAY=0 to keep the suite fast.
CHUNK_DELAY_SECONDS = float(os.environ.get("MOCK_STREAM_DELAY", "0.012"))


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n".encode()


def _chat_chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "model": "mock",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def _stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    for chunk in chunks:
        await asyncio.sleep(CHUNK_DELAY_SECONDS)
        yield chunk


def _tokenize(text: str) -> list[str]:
    """Split like a tokenizer would, so partial-JSON repair is genuinely tested."""
    return [token for token in re.findall(r"\s+|[^\s]{1,4}", text) if token]


# --- Groq -------------------------------------------------------------------


def _tool_call_stream(company: str) -> list[bytes]:
    """A streamed tool-call response, fragmented the way Groq fragments them."""
    queries = [
        ("web_search", f"{company} company overview products customers"),
        ("web_search", f"{company} CEO CTO CFO executive leadership team"),
        ("news_search", f"{company} acquisition funding earnings announcement"),
        ("web_search", f"{company} revenue employees market cap growth"),
        ("web_search", f"{company} lawsuit regulatory investigation security breach"),
    ]

    chunks: list[bytes] = []
    for index, (name, query) in enumerate(queries):
        chunks.append(
            _sse(
                _chat_chunk(
                    {
                        "tool_calls": [
                            {
                                "index": index,
                                "id": f"call_mock_{index}",
                                "type": "function",
                                "function": {"name": name, "arguments": ""},
                            }
                        ]
                    }
                )
            )
        )
        argument_text = json.dumps({"query": query})
        for token in _tokenize(argument_text):
            chunks.append(
                _sse(
                    _chat_chunk(
                        {
                            "tool_calls": [
                                {"index": index, "function": {"arguments": token}}
                            ]
                        }
                    )
                )
            )
    chunks.append(_sse(_chat_chunk({}, finish_reason="tool_calls")))
    chunks.append(b"data: [DONE]\n\n")
    return chunks


def _section_payload(section: str, company: str) -> dict[str, Any]:
    payloads: dict[str, dict[str, Any]] = {
        "overview": {
            "overview": (
                f"{company} builds payments and financial infrastructure used by "
                "online businesses to accept money, run marketplaces and manage "
                "risk. Its customers skew toward software companies and larger "
                "enterprises that want one integration rather than a bank "
                "relationship per market. It competes with incumbent processors "
                "on developer experience and on the breadth of its API surface, "
                "and increasingly with in-house treasury teams at its largest "
                "accounts."
            ),
            "citations": [1, 2],
        },
        "key_people": {
            "key_people": [
                {"name": "Dana Whitfield", "title": "Chief Executive Officer"},
                {"name": "Arun Mehta", "title": "Chief Technology Officer"},
                {"name": "Sofia Lindqvist", "title": "Chief Financial Officer"},
                {"name": "Marcus Bell", "title": "Chief Information Security Officer"},
            ],
            "citations": [3],
        },
        "news": {
            "news": [
                {
                    "headline": f"{company} acquires risk-scoring startup Kestrel",
                    "summary": "Signals a push into fraud tooling, so security and compliance stakeholders are likely in the buying group.",
                    "date": "2026-07-14",
                    "citation": 4,
                },
                {
                    "headline": "Q2 revenue up 24% year over year",
                    "summary": "Growth is holding, which usually means budget exists but scrutiny on unit economics is high.",
                    "date": "2026-08-02",
                    "citation": 5,
                },
                {
                    "headline": "New EMEA data residency region announced",
                    "summary": "Useful hook if the prospect has European data-residency requirements.",
                    "date": "2026-06-21",
                    "citation": 6,
                },
            ],
            "citations": [4, 5, 6],
        },
        "financials": {
            "financials": {
                "revenue": "$4.2B (FY2025)",
                "employee_count": "~8,100 (2026)",
                "market_cap": None,
                "yoy_growth": "24% (Q2 2026)",
            },
            "citations": [5, 7],
        },
        "risks": {
            "risks": [
                {
                    "title": "Interchange regulation",
                    "details": "Regulators in two markets are reviewing interchange caps, which could compress the take rate the company quotes publicly.",
                    "citation": 8,
                },
                {
                    "title": "Concentrated enterprise revenue",
                    "details": "A handful of large accounts drive a disproportionate share of volume, so procurement has leverage on pricing.",
                    "citation": 7,
                },
            ],
            "citations": [7, 8],
        },
    }
    return payloads.get(section, {"citations": []})


def _detect_section(messages: list[dict[str, Any]]) -> str:
    content = " ".join(
        str(message.get("content") or "") for message in messages if message.get("role") == "user"
    )
    for marker, section in (
        ("COMPANY OVERVIEW", "overview"),
        ("KEY PEOPLE", "key_people"),
        ("RECENT NEWS", "news"),
        ("FINANCIAL HIGHLIGHTS", "financials"),
        ("RISK FACTORS", "risks"),
    ):
        if marker in content:
            return section
    return "overview"


def _detect_company(messages: list[dict[str, Any]]) -> str:
    content = " ".join(str(message.get("content") or "") for message in messages)
    match = re.search(r"SEARCH EVIDENCE FOR ([^\n]+)", content)
    if match:
        return match.group(1).strip().title()
    match = re.search(r"Research the company: ([^\n]+)", content)
    return match.group(1).strip() if match else "The company"


def groq_mock_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    messages = body.get("messages") or []
    company = _detect_company(messages)

    if body.get("tools"):
        # Second round: the transcript already carries tool results, so a
        # well-behaved model stops searching and says DONE.
        if any(message.get("role") == "tool" for message in messages):
            chunks = [
                _sse(_chat_chunk({"content": "DONE"})),
                _sse(_chat_chunk({}, finish_reason="stop")),
                b"data: [DONE]\n\n",
            ]
        else:
            chunks = _tool_call_stream(company)
    else:
        payload = _section_payload(_detect_section(messages), company)
        text = json.dumps(payload, indent=None)
        chunks = [_sse(_chat_chunk({"content": token})) for token in _tokenize(text)]
        chunks.append(_sse(_chat_chunk({}, finish_reason="stop")))
        chunks.append(b"data: [DONE]\n\n")

    if not body.get("stream"):
        # Non-streaming callers get the assembled message.
        payload = _section_payload(_detect_section(messages), company)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": json.dumps(payload)}}
                ]
            },
        )

    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=_stream(chunks),
    )


# --- SerpAPI ----------------------------------------------------------------


def _organic(company: str, query: str) -> list[dict[str, Any]]:
    slug = re.sub(r"[^a-z0-9]+", "", company.casefold()) or "company"
    return [
        {
            "title": f"{company} - Official site",
            "link": f"https://www.{slug}.com/",
            "snippet": (
                f"{company} provides payments and financial infrastructure for "
                "internet businesses, covering acceptance, payouts, risk and reporting."
            ),
        },
        {
            "title": f"{company} - Company profile",
            "link": f"https://www.crunchbase.com/organization/{slug}",
            "snippet": (
                f"{company} reported $4.2B revenue in FY2025 with roughly 8,100 "
                "employees. Privately held; no public market capitalisation."
            ),
            "date": "Mar 3, 2026",
        },
        {
            "title": f"Leadership team - {company}",
            "link": f"https://www.{slug}.com/about/leadership",
            "snippet": (
                "Dana Whitfield, Chief Executive Officer. Arun Mehta, Chief "
                "Technology Officer. Sofia Lindqvist, Chief Financial Officer. "
                "Marcus Bell, Chief Information Security Officer."
            ),
        },
        {
            "title": f"{company} faces interchange review in two markets",
            "link": "https://www.reuters.com/business/finance/interchange-review",
            "snippet": (
                "Regulators opened a review of interchange caps that could affect "
                "the take rate the company publishes."
            ),
            "date": "May 12, 2026",
        },
    ]


def _news(company: str) -> list[dict[str, Any]]:
    return [
        {
            "title": f"{company} acquires risk-scoring startup Kestrel",
            "link": "https://techcrunch.com/2026/07/14/kestrel-acquisition",
            "snippet": "The deal adds fraud-scoring models to the company's risk suite.",
            "date": "Jul 14, 2026",
            "source": "TechCrunch",
        },
        {
            "title": f"{company} Q2 revenue up 24% year over year",
            "link": "https://www.bloomberg.com/news/q2-results",
            "snippet": "Revenue growth held at 24% while operating margin improved slightly.",
            "date": "Aug 2, 2026",
            "source": "Bloomberg",
        },
        {
            "title": f"{company} opens EMEA data residency region",
            "link": "https://www.theregister.com/2026/06/21/emea-region",
            "snippet": "European customers can now pin processing and storage in-region.",
            "date": "Jun 21, 2026",
            "source": "The Register",
        },
    ]


def serpapi_mock_handler(request: httpx.Request) -> httpx.Response:
    query = str(request.url.params.get("q") or "")
    # Every query starts with the company name; keep the leading proper nouns
    # and stop at the first lower-case search term.
    words: list[str] = []
    for word in query.split():
        if words and not word[:1].isupper():
            break
        words.append(word)
    company = " ".join(words[:3]) or "The company"

    if request.url.params.get("tbm") == "nws":
        return httpx.Response(200, json={"news_results": _news(company)})

    return httpx.Response(
        200,
        json={
            "knowledge_graph": {
                "title": company,
                "description": f"{company} is a financial technology company.",
                "source": {
                    "link": f"https://en.wikipedia.org/wiki/{company.replace(' ', '_')}"
                },
                "attributes": {"Founded": "2010", "Headquarters": "San Francisco, California"},
            },
            "organic_results": _organic(company, query),
        },
    )


def groq_mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(groq_mock_handler)


def serpapi_mock_transport() -> httpx.MockTransport:
    return httpx.MockTransport(serpapi_mock_handler)


# Backward-compatible aliases for external tests and integrations.
serper_mock_handler = serpapi_mock_handler
serper_mock_transport = serpapi_mock_transport
