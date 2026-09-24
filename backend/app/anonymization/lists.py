"""Term lists: always-mask (deny) and never-mask (allow).

Both lists use the same matching rule: case-insensitive and whitespace-flexible, so "500 Startups"
also matches "500 STARTUPS", "500  Startups" and the line-wrapped "500\\nStartups". Terms are
compared with the same normalization everywhere (`term_key`).

A never-mask (or kept) term suppresses a detected span only when the span lies FULLY inside one of
its occurrences (`is_allowed`). Overlap is not enough: keeping "Barış" (a false LOCATION) must not
reveal the person "Barış Demir" next to it.
"""
from __future__ import annotations

import re
import unicodedata

from app.anonymization.spans import EntitySpan
from app.anonymization.types import user_type


def term_key(term: str) -> str:
    """Case- and whitespace-normalized comparison key. Turkish dotted/dotless i fold to "i", as
    the case-insensitive term search already treats them ("KUZEY  grubu" == "Kuzey Grubu")."""
    folded = unicodedata.normalize("NFKC", term).casefold()
    return " ".join(folded.replace("i̇", "i").replace("ı", "i").split())


def contained(start: int, end: int, ranges, text: str | None = None) -> bool:
    """Does [start, end) lie fully inside one of `ranges`? With `text`, whitespace at the edges of
    the range is ignored."""
    if text is not None:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
    return any(a <= start and end <= b for a, b in ranges)


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


def deny_spans(text: str, terms: list[str],
               families: dict[str, str] | None = None) -> list[EntitySpan]:
    """Every occurrence of an always-mask term becomes a full-score span. A term masked globally
    from the review screen keeps the family the reviewer chose ("USER:<FAMILY>", which outranks
    everything); other terms stay SENSITIVE. Families are looked up by `term_key`. (A reviewer's
    document-wide masks are forced ranges instead: engine Overrides.mask_terms.)"""
    by_key = {term_key(t): fam for t, fam in (families or {}).items()}
    spans: list[EntitySpan] = []
    for term in terms:
        fam = by_key.get(term_key(term))
        entity_type = user_type(fam) if fam else "SENSITIVE"
        spans.extend(EntitySpan(start=a, end=b, entity_type=entity_type, score=1.0, source="deny")
                     for a, b in term_ranges(text, [term]))
    return spans


def is_allowed(span: EntitySpan, allow_ranges: list[tuple[int, int]], text: str) -> bool:
    """A span is suppressed only when it lies FULLY inside a never-mask occurrence (edge
    whitespace ignored). A longer span that merely overlaps the term stays: the term vouches for
    itself, not for its neighbours."""
    return contained(span.start, span.end, allow_ranges, text)
