"""Deterministic overlap resolution between detections."""
from __future__ import annotations

from app.anonymization.spans import EntitySpan
from app.anonymization.types import tier


def resolve_spans(spans: list[EntitySpan]) -> list[EntitySpan]:
    """Pick non-overlapping spans by PRIORITY, not position.

    Order: trust tier (validated pattern > everything else > statistical NER guess), then score
    desc, length desc, earliest start, entity type. spaCy gives every NER hit the same 0.85 and can
    emit a fragment of a longer value, so pure score ordering once let a 0.85 fragment beat a
    checksum-validated pattern and leave the middle of a phone number unmasked; the tier closes it.

    Containment expansion (measured leak fix): when a rejected span fully CONTAINS an accepted one,
    the accepted span grows to cover it, so a short high-score fragment can no longer shrink a long
    name to 4 characters. Only containment expands — expanding on partial overlap was tried and
    rejected (a false-positive NER span grew a real IBAN's mask backwards; see
    test_resolve_spans_priority_prevents_partial_leak).
    """
    ordered = sorted(
        spans, key=lambda s: (tier(s.entity_type), -s.score, -s.length, s.start, s.entity_type))
    accepted: list[EntitySpan] = []
    for s in ordered:
        blocking = [a for a in accepted if not (s.end <= a.start or s.start >= a.end)]
        if not blocking:
            accepted.append(s)
            continue
        for a in blocking:
            if s.start <= a.start and s.end >= a.end:
                accepted[accepted.index(a)] = a.model_copy(update={"start": s.start, "end": s.end})
    accepted.sort(key=lambda s: s.start)
    return accepted
