"""Variant propagation — the last masking pass.

A masked value can recur in spellings the regex recognizers miss ("BağdatCaddesiNo145", "BAĞDAT
CADDESI" with an ASCII I, a combining dot). Every masked value's normalized projection is searched
in the masked text of every unit and each hit gets the same placeholder family. Four modes, each
kept because removing it was measured to leak (thoughts/EXPERIMENTS.md):

  any      structural types (TYPES.propagate), unconstrained. Removed → 1 stress leak.
  glued    multi-word PERSON names, only whitespace-free spellings. Removed → 1 stress leak.
  surname  last word (≥4 chars) of a multi-word name, capitalized and word-bounded.
           Removed → 19 critical misses on the holdout.
  company  prefixes of a TR_COMPANY value (≥8 projected chars), capitalized and word-bounded.
           Closed the "Türk Telekom" short-name leak.

Only values found by deterministic recognizers (plus person names) propagate: an early version
propagated everything and a one-off NER false positive ("SÖZLEŞME" as LOCATION) spread to every
"sözleşme" in the document.
"""
from __future__ import annotations

import re
import unicodedata

from app.anonymization.spans import EntitySpan
from app.anonymization.types import PROPAGATION, family

# Existing placeholders are skipped. Kept byte-identical to the pre-Faz-1 pattern for parity; it
# misses families containing an underscore (e.g. <US_BANK_NUMBER_1>) — fixed in Faz 3.
_PLACEHOLDER_RE = re.compile(r"<[A-Z]+_\d+>")
MAX_COMPANY_PREFIX = 24


def norm_projection(text: str) -> tuple[str, list[int]]:
    """Normalized projection of `text` plus a projection-char → original-index map.

    casefold + NFKD, combining marks and ALL whitespace dropped, dotless ı folded to i (search
    only — the text itself never changes). "Bağdat Caddesi No 145", "BağdatCaddesiNo145" and
    "BAĞDAT CADDESI NO 145" all project to the same string.
    """
    proj: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKD", ch.casefold()):
            if unicodedata.combining(c) or c.isspace():
                continue
            proj.append("i" if c == "ı" else c)
            idx.append(i)
    return "".join(proj), idx


def projection_prefixes(value: str, min_len: int = 8) -> list[str]:
    """Shortened spellings of a company name: projection prefixes starting at EVERY word start
    (the TR_COMPANY span may include a leading label word such as "İşveren"), 8..24 chars."""
    out: list[str] = []
    seen: set[str] = set()
    for word in value.split():
        idx = value.find(word)
        proj = norm_projection(value[idx:])[0]
        for k in range(min_len, min(len(proj), MAX_COMPANY_PREFIX) + 1):
            piece = proj[:k]
            if piece not in seen:
                seen.add(piece)
                out.append(piece)
    return out


class VariantPools:
    """Surfaces collected from the masked spans of one document, in collection order."""

    def __init__(self) -> None:
        self.structural: dict[str, str] = {}
        self.person: dict[str, str] = {}
        self.surname: dict[str, str] = {}
        self.company: dict[str, str] = {}

    def collect(self, src_text: str, kept: list[EntitySpan]) -> None:
        for s in kept:
            surface = src_text[s.start:s.end]
            if s.entity_type in PROPAGATION:
                self.structural[surface] = family(s.entity_type)
            if s.entity_type == "TR_COMPANY":
                self.company[surface] = family(s.entity_type)
            elif s.entity_type in ("PERSON", "TR_PERSON_CTX"):
                words = surface.split()
                if len(words) >= 2:
                    self.person[surface] = "PERSON"
                    if len(words[-1]) >= 4:
                        self.surname[words[-1]] = "PERSON"

    def surfaces(self) -> list[tuple[str, str, str]]:
        """(family, needle-or-value, mode) in the historical order: any, glued, surname, company."""
        def long_enough(v: str, n: int) -> bool:
            return len(norm_projection(v)[0]) >= n

        return (
            [(fam, val, "any") for val, fam in self.structural.items() if long_enough(val, 8)]
            + [(fam, val, "glued") for val, fam in self.person.items() if long_enough(val, 8)]
            + [(fam, val, "surname") for val, fam in self.surname.items() if long_enough(val, 4)]
            + [(fam, pref, "company") for val, fam in self.company.items()
               for pref in projection_prefixes(val)]
        )


def _word_bounded(text: str, start: int, end: int) -> bool:
    return not ((start > 0 and text[start - 1].isalpha())
                or (end < len(text) and text[end].isalpha()))


def _accept(text: str, start: int, end: int, mode: str) -> bool:
    occurrence = text[start:end]
    if mode in ("glued", "surname") and any(ch.isspace() for ch in occurrence):
        return False  # a spaced spelling may be ordinary text
    if mode in ("company", "surname"):
        # Capitalized and bounded by non-letters in the ORIGINAL text (the projection drops spaces,
        # so every word looks glued to its neighbour there).
        return occurrence[:1].isupper() and _word_bounded(text, start, end)
    return True


def find_variants(text: str, surfaces: list[tuple[str, str, str]]
                  ) -> list[tuple[int, int, str, str]]:
    """Non-overlapping (start, end, family, mode) hits in `text`, avoiding existing placeholders.
    The caller applies them right to left so earlier offsets stay valid."""
    if not text:
        return []
    proj, idx = norm_projection(text)
    if not proj:
        return []
    placeholders = [(m.start(), m.end()) for m in _PLACEHOLDER_RE.finditer(text)]
    hits: list[tuple[int, int, str, str]] = []
    for fam, val, mode in surfaces:
        needle = norm_projection(val)[0]
        pos = proj.find(needle)
        while pos != -1:
            start, end = idx[pos], idx[pos + len(needle) - 1] + 1
            if _accept(text, start, end, mode) and \
                    not any(start < b and a < end for a, b in placeholders):
                hits.append((start, end, fam, mode))
            pos = proj.find(needle, pos + 1)
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    kept: list[tuple[int, int, str, str]] = []
    for h in hits:
        if all(h[1] <= k[0] or h[0] >= k[1] for k in kept):
            kept.append(h)
    return kept
