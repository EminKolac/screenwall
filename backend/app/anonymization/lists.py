"""Term lists: always-mask (deny) and never-mask (allow).

Both lists use the same matching rule: case-insensitive and whitespace-flexible, so "500 Startups"
also matches "500 STARTUPS", "500  Startups" and the line-wrapped "500\\nStartups".
"""
from __future__ import annotations

import re

from app.anonymization.spans import EntitySpan


def _term_pattern(term: str) -> str | None:
    parts = term.split()
    if not parts:
        return None
    return r"\s+".join(re.escape(p) for p in parts)


def term_ranges(text: str, terms: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for term in terms:
        pattern = _term_pattern(term)
        if pattern is None:
            continue
        for m in re.finditer(pattern, text, re.IGNORECASE):
            ranges.append((m.start(), m.end()))
    return ranges


def deny_spans(text: str, terms: list[str]) -> list[EntitySpan]:
    """Every occurrence of an always-mask term becomes a SENSITIVE span with full score."""
    return [EntitySpan(start=a, end=b, entity_type="SENSITIVE", score=1.0, source="deny")
            for a, b in term_ranges(text, terms)]


def is_allowed(span: EntitySpan, allow_ranges: list[tuple[int, int]]) -> bool:
    """A span is suppressed when it OVERLAPS any never-mask match (no exact-match requirement,
    so the list does not depend on exactly how NER segmented the phrase)."""
    return any(span.start < b and a < span.end for a, b in allow_ranges)
