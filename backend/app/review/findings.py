"""Residual findings: where the auditor's leftovers sit in the masked text.

The auditor returns raw residual strings (never persisted). Here they are turned into POSITIONS in
the masked units — the only thing stored (layer 4). Values a reviewer already said are not
personal data ("keep") are reported as kept instead of open.
"""
from __future__ import annotations

import re

from app.anonymization.spans import MaskEdit


def locate(units: list[tuple[str, str]], raw_terms: list[str], kept_values: list[str]
           ) -> tuple[list[dict], list[str]]:
    """Positions of every residual term in the masked units.

    Returns (findings, unlocated_terms). A term the auditor paraphrased cannot be located; the
    caller reports those as a document-level reason instead of a clickable item.
    """
    kept = {v.casefold() for v in kept_values}
    findings: list[dict] = []
    unlocated: list[str] = []
    for term in dict.fromkeys(t.strip() for t in raw_terms if t and t.strip()):
        pattern = r"\s+".join(re.escape(p) for p in term.split())
        found = False
        for uid, masked in units:
            for m in re.finditer(pattern, masked, re.IGNORECASE):
                found = True
                findings.append({
                    "id": f"f{len(findings) + 1}",
                    "unit_id": uid,
                    "masked_start": m.start(),
                    "masked_end": m.end(),
                    "code": "audit_residual",
                    "severity": "high",
                    "status": "kept" if term.casefold() in kept else "open",
                })
        if not found:
            unlocated.append(term)
    return findings, unlocated


def masked_to_original(edits: list[MaskEdit], pos: int) -> int:
    """Map a masked-text position in literal text back to the original text."""
    shift = 0
    for e in edits:
        if e.masked_end <= pos:
            shift = e.end - e.masked_end
        else:
            break
    return pos + shift


def original_to_masked(edits: list[MaskEdit], pos: int) -> int:
    shift = 0
    for e in edits:
        if e.end <= pos:
            shift = e.masked_end - e.end
        else:
            break
    return pos + shift
