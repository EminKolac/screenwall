"""Anonymization engine interface (Presidio orchestration).

Concrete implementation lands in Phase 3: per-language Presidio AnalyzerEngine (EN spaCy +
TR transformers NER) + custom TR/EN recognizers, applied block-by-block with a shared
`PlaceholderMapper`. `extra_deny_terms` lets the iteration loop feed back items the auditor
still flagged.

Codex Phase-1 review:
- `EntitySpan` + `resolve_spans` give a deterministic overlap-resolution contract so partial /
  nested matches replace stably (HIGH).
- The placeholder mapping is a separate sensitive artifact excluded from serialization so it
  can never be returned by an API, logged, or forwarded to a provider (HIGH).
- Mixed documents route per block: `block.language` overrides the document default (HIGH).
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.extraction.base import ExtractedContent
from app.models.document import Language


class EntitySpan(BaseModel):
    start: int
    end: int
    entity_type: str
    score: float = 0.0
    source: str = ""  # recognizer name (for debugging / calibration)

    @property
    def length(self) -> int:
        return self.end - self.start


def resolve_spans(spans: list[EntitySpan]) -> list[EntitySpan]:
    """Deterministically pick non-overlapping spans by PRIORITY, not position.

    Accept highest-value spans first (score desc, then length desc, then earliest start, then
    entity_type for stability); reject any span overlapping an already-accepted one. This ensures
    a high-confidence long entity (e.g. a full IBAN, score 1.0) wins over an earlier-starting
    lower-value NER span that only partially overlaps it — preventing partial-PII leaks.
    """
    ordered = sorted(spans, key=lambda s: (-s.score, -s.length, s.start, s.entity_type))
    accepted: list[EntitySpan] = []
    for s in ordered:
        if all(s.end <= a.start or s.start >= a.end for a in accepted):
            accepted.append(s)
    accepted.sort(key=lambda s: s.start)
    return accepted


class SensitiveMapping(BaseModel):
    """Placeholder↔original map. Persisted ONLY to storage layer 2. Never returned by anonymization
    APIs (excluded from serialization) and never logged."""
    model_config = {"extra": "forbid"}
    pairs: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)


class AnonymizationOutput(BaseModel):
    content: ExtractedContent                 # structure-preserving, anonymized
    entity_count: int = 0
    placeholders_used: dict[str, int] = Field(default_factory=dict)
    # Excluded from model_dump()/JSON so it cannot leak via API responses or logs.
    mapping: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)


class AnonymizationEngine:
    """Phase-3 implementation target. Declared here so the pipeline depends on the interface."""

    def anonymize(
        self,
        content: ExtractedContent,
        language: Language,
        *,
        extra_deny_terms: list[str] | None = None,
    ) -> AnonymizationOutput:
        # Per-block: use block.language if set, else `language`. For mixed, run EN + TR analyzers
        # and merge spans via resolve_spans before applying deterministic placeholders.
        raise NotImplementedError("Implemented in Phase 3 (Presidio engine).")
