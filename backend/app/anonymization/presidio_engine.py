"""Concrete Presidio anonymization engine (Phase 3).

Runs each block through BOTH language analyzers (en + tr) so English predefined recognizers and
Turkish custom/NER recognizers all contribute regardless of the block's detected language — the
union maximizes recall (the safe direction). Overlapping spans are resolved deterministically
(`resolve_spans`) and replaced with deterministic `<TYPE_n>` placeholders via a shared mapper.
Structure is preserved (paragraph text / table cells edited in place).
"""
from __future__ import annotations

import threading

from app.anonymization.engine import (
    AnonymizationEngine,
    AnonymizationOutput,
    EntitySpan,
    resolve_spans,
)
from app.anonymization.nlp import get_analyzer
from app.anonymization.placeholders import PlaceholderMapper
from app.extraction.base import BlockType, ExtractedContent
from app.models.document import Language

_TYPE_TO_PLACEHOLDER = {
    "PERSON": "PERSON", "EMAIL_ADDRESS": "EMAIL", "PHONE_NUMBER": "PHONE",
    "ORGANIZATION": "ORG", "LOCATION": "LOCATION", "CREDIT_CARD": "CARD",
    "IBAN_CODE": "IBAN", "IP_ADDRESS": "IP", "URL": "URL", "DATE_TIME": "DATE",
    "NRP": "NRP", "US_SSN": "SSN", "US_DRIVER_LICENSE": "DL",
    "TR_TCKN": "TCKN", "TR_VKN": "VKN", "TR_GSM": "PHONE", "TR_PHONE": "PHONE",
    "TR_IBAN": "IBAN", "TR_PLATE": "PLATE", "TR_PASSPORT": "PASSPORT",
    "UK_PHONE": "PHONE", "PASSPORT": "PASSPORT", "DRIVER_LICENSE": "DL", "SENSITIVE": "SENSITIVE",
}


def _ph_type(entity_type: str) -> str:
    return _TYPE_TO_PLACEHOLDER.get(entity_type, entity_type)


# Serialize access to the shared cached AnalyzerEngine across threads/requests.
_ANALYZE_LOCK = threading.Lock()


class PresidioEngine(AnonymizationEngine):
    def __init__(self, score_threshold: float | None = None) -> None:
        self._threshold = score_threshold

    @property
    def threshold(self) -> float:
        if self._threshold is not None:
            return self._threshold
        from app.config import get_settings
        return get_settings().anonymizer_score_threshold

    def anonymize(
        self,
        content: ExtractedContent,
        language: Language,
        *,
        extra_deny_terms: list[str] | None = None,
    ) -> AnonymizationOutput:
        analyzer = get_analyzer()
        mapper = PlaceholderMapper()
        deny = [t.strip() for t in (extra_deny_terms or []) if t and t.strip()]
        total = 0
        new_blocks = []
        for block in content.blocks:
            if block.type == BlockType.table:
                new_cells = []
                for cell in block.cells:
                    text, n = self._anon_text(cell.text, mapper, deny, analyzer)
                    total += n
                    new_cells.append(cell.model_copy(update={"text": text}))
                new_blocks.append(block.model_copy(update={"cells": new_cells}))
            else:
                text, n = self._anon_text(block.text, mapper, deny, analyzer)
                total += n
                new_blocks.append(block.model_copy(update={"text": text}))
        out = content.model_copy(update={"blocks": new_blocks})
        return AnonymizationOutput(
            content=out,
            entity_count=total,
            placeholders_used=mapper.counts(),
            mapping=dict(mapper.mapping),
        )

    def _anon_text(self, text, mapper, deny, analyzer):
        if not text or not text.strip():
            return text, 0
        spans: list[EntitySpan] = []
        # No swallowing: if analysis fails, the exception propagates so the pipeline fails closed
        # (routes to human review) rather than returning under-anonymized text.
        with _ANALYZE_LOCK:
            for lang in ("en", "tr"):
                for r in analyzer.analyze(text=text, language=lang, score_threshold=self.threshold):
                    spans.append(EntitySpan(start=r.start, end=r.end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        for term in deny:
            i = text.find(term)
            while i != -1:
                spans.append(EntitySpan(start=i, end=i + len(term), entity_type="SENSITIVE",
                                        score=1.0, source="deny"))
                i = text.find(term, i + len(term))
        kept = resolve_spans(spans)
        if not kept:
            return text, 0
        out = text
        for s in sorted(kept, key=lambda s: -s.start):  # right-to-left keeps offsets valid
            token = mapper.placeholder_for(_ph_type(s.entity_type), text[s.start:s.end])
            out = out[: s.start] + token + out[s.end:]
        return out, len(kept)
