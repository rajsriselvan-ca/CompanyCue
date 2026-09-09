"""Best-effort parsing of a JSON document that is still being streamed.

The model emits section JSON one token at a time. Waiting for the closing brace
before showing anything is what made the previous build feel like a blank
screen: the user watches a spinner, then five blocks appear at once.

Instead we repair the truncated text on every delta - close the open string,
drop the dangling key or comma, close the open containers - and parse the
result. That turns a half-written array of people into a list of the people
written so far, which the UI can render immediately.

Repair is deliberately conservative: anything ambiguous yields None and the UI
simply keeps the previous partial value.
"""

from __future__ import annotations

import json
from typing import Any

_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


def _strip_code_fence(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("```"):
        newline = stripped.find("\n")
        stripped = stripped[newline + 1 :] if newline >= 0 else ""
    if stripped.rstrip().endswith("```"):
        stripped = stripped.rstrip()[:-3]
    return stripped


def complete_json(text: str) -> str | None:
    """Return `text` extended with whatever closers make it valid, or None."""
    source = _strip_code_fence(text)
    start = source.find("{")
    if start < 0:
        return None
    source = source[start:]

    stack: list[str] = []
    in_string = False
    escaped = False

    for char in source:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in _OPEN_TO_CLOSE:
            stack.append(char)
        elif char in {"}", "]"}:
            if stack and _OPEN_TO_CLOSE[stack[-1]] == char:
                stack.pop()
            else:
                return None  # Unbalanced: not something we should guess at.

    repaired = source
    if escaped:
        # A trailing backslash would escape the quote we are about to add.
        repaired = repaired[:-1]
    if in_string:
        repaired += '"'

    repaired = _trim_dangling(repaired)

    for opener in reversed(stack):
        repaired += _OPEN_TO_CLOSE[opener]
    return repaired


def _trim_dangling(text: str) -> str:
    """Remove a trailing comma, colon, or a key with no value yet."""
    trimmed = text.rstrip()
    while trimmed:
        if trimmed[-1] in ",:":
            trimmed = trimmed[:-1].rstrip()
            continue
        # `{"name": "Ada", "title"` -> the key is useless without its value.
        if trimmed[-1] == '"':
            without_key = _drop_valueless_key(trimmed)
            if without_key is not None:
                trimmed = without_key.rstrip()
                continue
        break
    return trimmed


def _drop_valueless_key(text: str) -> str | None:
    """If `text` ends in a complete string that is a key, drop it. Else None."""
    index = len(text) - 2
    while index >= 0:
        if text[index] == '"':
            backslashes = 0
            probe = index - 1
            while probe >= 0 and text[probe] == "\\":
                backslashes += 1
                probe -= 1
            if backslashes % 2 == 0:
                break
        index -= 1
    if index < 0:
        return None
    before = text[:index].rstrip()
    # A string preceded by `{` or `,` and not followed by `:` is a pending key.
    if before.endswith(("{", ",")):
        return before
    return None


def parse_partial(text: str) -> dict[str, Any] | None:
    """Parse a possibly-truncated JSON object. Returns None if unusable."""
    if not text or not text.strip():
        return None
    repaired = complete_json(text)
    if repaired is None:
        return None
    try:
        parsed = json.loads(repaired)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_strict(text: str) -> dict[str, Any] | None:
    """Parse a finished response, tolerating code fences and surrounding prose."""
    source = _strip_code_fence(text)
    start, end = source.find("{"), source.rfind("}")
    if start < 0:
        return None
    if end <= start:
        # No closing brace at all: the model stopped at the token limit.
        return parse_partial(source)
    try:
        parsed = json.loads(source[start : end + 1])
    except json.JSONDecodeError:
        return parse_partial(source)
    return parsed if isinstance(parsed, dict) else None
