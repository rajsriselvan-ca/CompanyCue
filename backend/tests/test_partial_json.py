"""The repair rules behind progressive rendering.

Each case is a real prefix of a streamed section response, cut where a
tokenizer would plausibly cut it.
"""

from __future__ import annotations

import pytest

from app.agent.partial_json import parse_partial, parse_strict


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ('{"overview": "Acme make', {"overview": "Acme make"}),
        ('{"overview": "Acme makes widgets."', {"overview": "Acme makes widgets."}),
        ('{"overview": "Acme.", ', {"overview": "Acme."}),
        ('{"overview": "Acme.", "citations"', {"overview": "Acme."}),
        ('{"overview": "Acme.", "citations":', {"overview": "Acme."}),
        ('{"overview": "Acme.", "citations": [1, 2', {"overview": "Acme.", "citations": [1, 2]}),
        # A half-written person keeps the fields it has: the name appears in the
        # UI as soon as it is streamed, and the title fills in a moment later.
        (
            '{"key_people": [{"name": "Ada", "title": "CEO"}, {"name": "Grace"',
            {"key_people": [{"name": "Ada", "title": "CEO"}, {"name": "Grace"}]},
        ),
        (
            '{"key_people": [{"name": "Ada", "title": "CE',
            {"key_people": [{"name": "Ada", "title": "CE"}]},
        ),
        (
            '{"financials": {"revenue": "$4.2B", "market_cap": nul',
            None,  # `nul` is not yet a value we can trust; wait for more.
        ),
    ],
)
def test_repairs_truncated_objects(prefix, expected):
    assert parse_partial(prefix) == expected


def test_a_partial_grows_monotonically_through_a_stream():
    """The whole point: each delta yields at least as much as the one before."""
    full = '{"key_people": [{"name": "Ada Lovelace", "title": "Chief Executive Officer"}]}'
    people_seen = 0
    for length in range(1, len(full) + 1):
        parsed = parse_partial(full[:length])
        if parsed is None:
            continue
        people = parsed.get("key_people", [])
        assert isinstance(people, list)
        assert len(people) >= people_seen
        people_seen = len(people)
    assert people_seen == 1


def test_escaped_quotes_do_not_confuse_the_repair():
    assert parse_partial('{"overview": "He said \\"hi') == {"overview": 'He said "hi'}


def test_trailing_backslash_is_dropped_rather_than_escaping_our_own_quote():
    assert parse_partial('{"overview": "path\\') == {"overview": "path"}


def test_unbalanced_closer_is_rejected_instead_of_guessed():
    assert parse_partial('{"a": 1}}') is None


def test_ignores_text_before_the_object():
    assert parse_partial('Sure! {"overview": "Acme"') == {"overview": "Acme"}


def test_strict_parse_handles_code_fences():
    assert parse_strict('```json\n{"overview": "Acme"}\n```') == {"overview": "Acme"}


def test_strict_parse_falls_back_to_repair_when_the_model_hits_the_token_limit():
    assert parse_strict('{"overview": "Acme makes wid') == {"overview": "Acme makes wid"}


def test_returns_none_for_non_objects():
    assert parse_partial("[1, 2, 3]") is None
    assert parse_partial("") is None
    assert parse_partial("   ") is None
