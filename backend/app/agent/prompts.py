"""Prompt construction.

Two distinct prompts, because the two phases want opposite things from the
model:

1. Research phase - tools on, JSON mode off. The model's only job is to choose
   good search queries. It is explicitly told not to answer from memory.
2. Synthesis phase - tools off, JSON mode on, one call per section. The model
   sees only the numbered evidence and must cite it. Separate calls mean one
   malformed section cannot destroy the other four, and each section gets a
   prompt tuned to what a sales rep actually needs from it.
"""

from __future__ import annotations

from datetime import date

from app.agent.evidence import EvidenceCorpus
from app.schemas import SectionKey

RESEARCH_SYSTEM_PROMPT = """You are the research planner for a sales-briefing tool.

You do not know anything about this company. Your training data is stale and \
must not be used as a source. The only way to learn anything is to call the \
search tools.

Plan searches that cover all five briefing sections:
1. what the company does - industry, products, customers, market position
2. current leadership - CEO, CTO, CFO, CIO, CISO and equivalent
3. recent news - acquisitions, funding, earnings, launches, partnerships, layoffs, leadership changes
4. financials - revenue, employee count, market cap, year-over-year growth
5. risks - regulatory scrutiny, security incidents, litigation, competitive or financial pressure

Rules:
- Issue several focused searches at once rather than one broad one.
- Use news_search for anything time-sensitive; use web_search for everything else.
- Include the company name in every query, and disambiguate it if the name is generic.
- When the results already cover all five sections, reply with the single word DONE and no tool calls.
- Never write the briefing yourself. Your entire output is tool calls, or DONE."""


SYNTHESIS_SYSTEM_PROMPT = """You write one section of a pre-meeting sales briefing.

Today is {today}.

You are given numbered search results. They are your only permitted source of \
fact. You have no other knowledge of this company.

Hard rules:
- Every fact must be supported by the numbered evidence. Cite the numbers you used.
- If the evidence does not support a field, return null for it or leave the array empty. \
An empty section is correct and useful. An invented one destroys the rep's credibility \
in front of the customer.
- Never estimate, extrapolate, or infer a number that is not stated in the evidence.
- Do not mention the evidence, the search, or yourself. Write for a busy salesperson \
who has 2 minutes before the call.
- Reply with a single JSON object matching the requested shape. No markdown, no prose \
outside the JSON."""


SECTION_INSTRUCTIONS: dict[SectionKey, str] = {
    "overview": """Write the COMPANY OVERVIEW for {company}.

Shape:
{{"overview": string|null, "citations": [int]}}

"overview" is 60-100 words of continuous prose covering: the industry, the core \
product or service, who buys it, and how the company is positioned against \
alternatives. It reads like a colleague briefing you in a lift, not like an \
encyclopaedia entry. No bullet points, no marketing adjectives, no company \
boilerplate. Return null only if the evidence does not identify this company at all.""",
    "key_people": """List the KEY PEOPLE at {company}.

Shape:
{{"key_people": [{{"name": string, "title": string}}], "citations": [int]}}

Include current C-suite and senior leaders a sales rep might meet or be routed \
to: CEO, CTO, CFO, COO, CIO, CISO, Chief Revenue/Product Officer, and VPs of \
relevant functions. Use the exact title in the evidence. Order by seniority, \
most senior first. Maximum 8 people. Exclude board members who hold no \
executive role, and anyone the evidence shows has left. If a person's current \
title is not stated in the evidence, leave them out rather than guessing.""",
    "news": """Summarise the RECENT NEWS about {company}.

Shape:
{{"news": [{{"headline": string, "summary": string, "date": "YYYY-MM-DD"|null, "citation": int}}], "citations": [int]}}

Return 3-4 items, most recent first, drawn only from evidence published within \
the last 12 months. Prioritise material events: acquisitions, funding rounds, \
earnings, product launches, major partnerships, layoffs, leadership changes, \
regulatory actions. "summary" is one sentence explaining why it matters in a \
sales conversation. Set "date" from the evidence's publication date; use null \
if it is not stated. "citation" is the single evidence number the item came \
from. Return fewer items, or an empty array, rather than padding with stale or \
generic coverage.""",
    "financials": """Extract the FINANCIAL HIGHLIGHTS for {company}.

Shape:
{{"financials": {{"revenue": string|null, "employee_count": string|null, "market_cap": string|null, "yoy_growth": string|null}}, "citations": [int]}}

Each value is a short string exactly as supported by the evidence, including \
currency, magnitude and period - for example "$4.2B (FY2025)" or "~8,000 \
(2025)". Use null for anything the evidence does not state. Private companies \
have no market cap: that is a null, not a guess. Never derive one figure from \
another and never carry a number across years.""",
    "risks": """Identify the RISK FACTORS for {company}.

Shape:
{{"risks": [{{"title": string, "details": string, "citation": int}}], "citations": [int]}}

Return 2-3 concrete, evidence-backed risks the prospect might raise or be \
sensitive about: regulatory scrutiny, security incidents or breaches, pending \
litigation, competitive pressure, financial instability, key-person or \
restructuring risk. "title" is 2-5 words. "details" is one sentence a rep can \
use to anticipate an objection. "citation" is the evidence number. Do not list \
generic industry risks that apply to every company, and do not invent a third \
risk to reach the count.""",
}


def build_research_messages(company_name: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Research the company: {company_name}\n\n"
                f"Today is {date.today().isoformat()}. Start by searching."
            ),
        },
    ]


def build_section_messages(
    *, company_name: str, section: SectionKey, evidence: EvidenceCorpus
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": SYNTHESIS_SYSTEM_PROMPT.format(today=date.today().isoformat()),
        },
        {
            "role": "user",
            "content": (
                f"SEARCH EVIDENCE FOR {company_name.upper()}\n"
                f"{'=' * 60}\n"
                f"{evidence.render()}\n"
                f"{'=' * 60}\n\n"
                f"{SECTION_INSTRUCTIONS[section].format(company=company_name)}"
            ),
        },
    ]
