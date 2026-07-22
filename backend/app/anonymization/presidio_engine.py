"""Concrete Presidio anonymization engine (Phase 3).

Runs each block through BOTH language analyzers (en + tr) so English predefined recognizers and
Turkish custom/NER recognizers all contribute regardless of the block's detected language — the
union maximizes recall (the safe direction). Overlapping spans are resolved deterministically
(`resolve_spans`) and replaced with deterministic `<TYPE_n>` placeholders via a shared mapper.
Structure is preserved (paragraph text / table cells edited in place).
"""
from __future__ import annotations

import re
import threading

from app.anonymization.engine import (
    AnonymizationEngine,
    AnonymizationOutput,
    EntitySpan,
    resolve_spans,
)
from app.anonymization.nlp import get_analyzer
from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.privacy_filter import get_privacy_filter
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
    # Families fed by the Privacy Filter label map (privacy_filter._LABEL_MAP folds the model's
    # taxonomy into platform entity types, so both detectors share the same <TYPE_n> families).
    "ACCOUNT": "ACCOUNT", "SECRET": "SECRET", "USERNAME": "USERNAME", "PLATE": "PLATE",
}


def _ph_type(entity_type: str) -> str:
    return _TYPE_TO_PLACEHOLDER.get(entity_type, entity_type)


def _source_cat(source: str) -> str:
    """Group an EntitySpan.source into a detection-stage label for per-stage reporting."""
    return "presidio" if source in ("en", "tr") else (source or "presidio")


def _tally(by_source: dict[str, int], kept: list[EntitySpan]) -> None:
    for s in kept:
        cat = _source_cat(s.source)
        by_source[cat] = by_source.get(cat, 0) + 1


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
        # Stage ② detector: None unless enabled+available; raises if required-but-unavailable so the
        # pipeline fails closed to human review (caught in runner.run_pipeline).
        detector = get_privacy_filter()
        mapper = PlaceholderMapper()
        deny = [t.strip() for t in (extra_deny_terms or []) if t and t.strip()]
        total = 0
        by_source: dict[str, int] = {}
        new_blocks = []
        for block in content.blocks:
            if block.type == BlockType.table:
                new_cells = []
                for cell in block.cells:
                    text, kept = self._anon_text(cell.text, mapper, deny, analyzer, detector)
                    total += len(kept)
                    _tally(by_source, kept)
                    new_cells.append(cell.model_copy(update={"text": text}))
                # Drop the raw sheet name from the anonymized (layer-3) copy — it is un-audited PII;
                # the audited sheet name is carried separately as an anonymized heading block.
                new_blocks.append(block.model_copy(update={"cells": new_cells, "sheet": None}))
            else:
                text, kept = self._anon_text(block.text, mapper, deny, analyzer, detector)
                total += len(kept)
                _tally(by_source, kept)
                new_blocks.append(block.model_copy(update={"text": text}))
        out = content.model_copy(update={"blocks": new_blocks})
        return AnonymizationOutput(
            content=out,
            entity_count=total,
            placeholders_used=mapper.counts(),
            by_source=by_source,
            mapping=dict(mapper.mapping),
        )

    def detect(self, text: str, *, extra_deny_terms: list[str] | None = None) -> list[EntitySpan]:
        """Run all detection stages and return the resolved, non-overlapping spans on the ORIGINAL
        text — WITHOUT applying placeholders. This is the detection half of `anonymize`; the eval
        harness (`evaluation/`) scores THIS so metrics reflect the exact production detection path.
        """
        analyzer = get_analyzer()
        detector = get_privacy_filter()
        deny = [t.strip() for t in (extra_deny_terms or []) if t and t.strip()]
        return self._detect(text, deny, analyzer, detector)

    def _detect(self, text, deny, analyzer, detector) -> list[EntitySpan]:
        """Collect spans from every detection stage and resolve overlaps. Shared by `detect`
        (eval) and `_anon_text` (production) so the two can never drift apart."""
        if not text or not text.strip():
            return []
        spans: list[EntitySpan] = []
        # Stage ① — Presidio (EN+TR). No swallowing: an analysis error propagates so the pipeline
        # fails closed (routes to human review) rather than returning under-anonymized text.
        with _ANALYZE_LOCK:
            for lang in ("en", "tr"):
                for r in analyzer.analyze(text=text, language=lang, score_threshold=self.threshold):
                    spans.append(EntitySpan(start=r.start, end=r.end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        # Project deny-list — case-insensitive + whitespace-flexible ("500 Startups" also masks
        # "500 STARTUPS", "500  Startups", and the line-wrapped "500\nStartups").
        for term in deny:
            parts = term.split()
            if not parts:
                continue
            pattern = r"\s+".join(re.escape(p) for p in parts)
            for m in re.finditer(pattern, text, re.IGNORECASE):
                spans.append(EntitySpan(start=m.start(), end=m.end(), entity_type="SENSITIVE",
                                        score=1.0, source="deny"))
        # Stage ② — OpenAI Privacy Filter (local, contextual). Errors propagate (fail-closed) too.
        if detector is not None:
            spans.extend(detector.detect(text))
        return resolve_spans(spans)

    def _anon_text(self, text, mapper, deny, analyzer, detector):
        kept = self._detect(text, deny, analyzer, detector)
        if not kept:
            return text, []
        out = text
        for s in sorted(kept, key=lambda s: -s.start):  # right-to-left keeps offsets valid
            token = mapper.placeholder_for(_ph_type(s.entity_type), text[s.start:s.end])
            out = out[: s.start] + token + out[s.end:]
        return out, kept
