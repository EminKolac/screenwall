"""Residual findings: where the auditor's leftovers sit in the masked text.

The auditor returns raw residual strings (never persisted as findings). Here they are turned into
POSITIONS in the masked units — the only thing stored in layer 4. A term is never matched inside a
placeholder. Residuals a reviewer said are not personal data ("keep") are reported as kept instead
of open: by value for a document-wide keep, by ORIGINAL position for a single occurrence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.anonymization.lists import contained, term_key
from app.anonymization.spans import MaskEdit
from app.anonymization.units import iter_units
from app.extraction.base import ExtractedContent
from app.models.document import Document
from app.review.reasons import REVIEW_REASONS, unlocated_reason
from app.services.repository import DocumentRepository

_PLACEHOLDER = re.compile(r"<[A-Z][A-Z_]*_\d+>")


@dataclass(frozen=True)
class KeptFindings:
    """Residuals a reviewer kept: term keys (document scope) and ORIGINAL ranges per unit (one
    occurrence)."""
    values: frozenset[str] = frozenset()
    ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    def covers(self, uid: str, term: str, start: int, end: int) -> bool:
        return term_key(term) in self.values or contained(start, end, self.ranges.get(uid, []))


def locate(units: list[tuple[str, str]], raw_terms: list[str], kept_values=(), *,
           kept: KeptFindings | None = None,
           edits: dict[str, list[MaskEdit]] | None = None) -> tuple[list[dict], list[str]]:
    """Positions of every residual term in the masked units.

    Returns (findings, unlocated_terms). A term the auditor paraphrased cannot be located; the
    caller reports those as a document-level reason instead of a clickable item.
    """
    keep = kept or KeptFindings()
    keep = KeptFindings(keep.values | {term_key(v) for v in kept_values}, keep.ranges)
    findings: list[dict] = []
    unlocated: list[str] = []
    seen: set[tuple[str, int, int]] = set()
    for term in _unique_terms(raw_terms):
        found = False
        for uid, masked in units:
            for start, end in _occurrences(term, masked):
                found = True
                if (uid, start, end) in seen:  # another term already found this very text
                    continue
                seen.add((uid, start, end))
                o_start, o_end = original_range((edits or {}).get(uid, []), start, end)
                findings.append({
                    "id": f"f{len(findings) + 1}", "unit_id": uid,
                    "masked_start": start, "masked_end": end,
                    "code": "audit_residual", "severity": "high",
                    "status": "kept" if keep.covers(uid, term, o_start, o_end) else "open",
                })
        if not found:
            unlocated.append(term)
    return findings, unlocated


def _unique_terms(raw_terms: list[str]) -> list[str]:
    """One term per `term_key` (first spelling): "Ahmet Bey" and "AHMET  BEY" are one finding."""
    by_key: dict[str, str] = {}
    for t in (t.strip() for t in raw_terms if t and t.strip()):
        by_key.setdefault(term_key(t), t)
    return list(by_key.values())


def _occurrences(term: str, masked: str) -> list[tuple[int, int]]:
    """Case-insensitive, whitespace-flexible matches of `term`, never inside a placeholder."""
    pattern = r"\s+".join(re.escape(p) for p in term.split())
    blocked = [(m.start(), m.end()) for m in _PLACEHOLDER.finditer(masked)]
    return [(m.start(), m.end()) for m in re.finditer(pattern, masked, re.IGNORECASE)
            if not any(m.start() < b and a < m.end() for a, b in blocked)]


def record_findings(doc: Document, repo: DocumentRepository, content: ExtractedContent,
                    edits: dict[str, list[MaskEdit]], terms: list[str],
                    kept: KeptFindings | None, *, residual: bool) -> list[str]:
    """Locate `terms` in the masked content; store the findings (positions only), the pending count
    and the reasons. `residual`: a real audit was not clean (reported even when nothing is located).
    Returns the terms that could not be located."""
    units = [(uid, text) for uid, _b, _c, text in iter_units(content)]
    findings, unlocated = locate(units, terms, kept=kept, edits=edits)
    repo.save_findings(doc.id, findings)
    doc.pending_count = sum(1 for f in findings if f["status"] == "open")
    doc.drop_reasons("audit_residual", "audit_unlocated")
    if residual or doc.pending_count:
        doc.add_reason("audit_residual", REVIEW_REASONS["audit_residual"])
    if unlocated:
        doc.add_reason("audit_unlocated", unlocated_reason(len(unlocated)))
    return unlocated


def original_range(edits: list[MaskEdit], start: int, end: int) -> tuple[int, int]:
    """Original offsets of a [start, end) range of literal masked text."""
    return masked_to_original(edits, start), masked_end_to_original(edits, end)


def masked_to_original(edits: list[MaskEdit], pos: int) -> int:
    """Map a masked-text position in literal text back to the original text."""
    shift = 0
    for e in edits:
        if e.masked_end <= pos:
            shift = e.end - e.masked_end
        else:
            break
    return pos + shift


def masked_end_to_original(edits: list[MaskEdit], pos: int) -> int:
    """Map an exclusive END: one past the original of the last literal character. An empty edit
    (a removed split-cell fragment) sitting exactly at `pos` is therefore not swallowed."""
    return pos if pos <= 0 else masked_to_original(edits, pos - 1) + 1


def original_to_masked(edits: list[MaskEdit], pos: int) -> int:
    shift = 0
    for e in edits:
        if e.end <= pos:
            shift = e.masked_end - e.end
        else:
            break
    return pos + shift
