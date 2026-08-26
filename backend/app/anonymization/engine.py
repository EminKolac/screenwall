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


# Deterministic, format/checksum-validated pattern recognizers. Their spans cover the ENTIRE
# matched value (an IBAN, a phone number) by construction, unlike statistical NER which can emit
# short fragments. Tier 0: always outranks tier 2 on overlap, regardless of score.
_TRUSTED_PATTERN_TYPES = frozenset({
    "TR_IBAN", "TR_TCKN", "TR_GSM", "TR_PHONE",
    "IBAN_CODE", "CREDIT_CARD", "EMAIL_ADDRESS",
    "US_SSN", "UK_PHONE", "IP_ADDRESS", "URL",
})
# spaCy NER guesses — no format validation, uniform 0.85 confidence regardless of correctness
# (see nlp.py). Tier 2: always outranked by tier 0, and by anything else (tier 1) on overlap.
_STATISTICAL_NER_TYPES = frozenset({
    "PERSON", "LOCATION", "ORGANIZATION", "NRP", "DATE_TIME",
})


def _trust_tier(entity_type: str) -> int:
    if entity_type in _TRUSTED_PATTERN_TYPES:
        return 0
    if entity_type in _STATISTICAL_NER_TYPES:
        return 2
    return 1


def resolve_spans(spans: list[EntitySpan]) -> list[EntitySpan]:
    """Deterministically pick non-overlapping spans by PRIORITY, not position.

    Accept highest-value spans first — trust tier first (validated pattern > everything else >
    statistical NER guess), then score desc, then length desc, then earliest start, then
    entity_type for stability — and reject any span overlapping an already-accepted one.

    The trust tier exists because spaCy NER carries no real confidence signal: every hit is
    hard-coded to the same 0.85 score (see nlp.py) whether or not it is correct, and it can emit a
    SHORT FRAGMENT of a longer value (e.g. a "date-shaped" sub-span inside a phone number). Pure
    score ordering let a 0.85 fragment beat a 0.5-0.7 but format/checksum-VALIDATED pattern match
    (TR_GSM, TR_IBAN, TR_TCKN, …), leaving the unmatched middle of the real value unmasked — a
    partial-PII leak, not just a wrong label. Tiering the trusted pattern types ahead of
    statistical NER closes that gap; a high-confidence long entity (e.g. a full IBAN) still wins
    over an earlier-starting lower-value NER span within the same tier, exactly as before.
    """
    ordered = sorted(
        spans,
        key=lambda s: (_trust_tier(s.entity_type), -s.score, -s.length, s.start, s.entity_type),
    )
    accepted: list[EntitySpan] = []
    for s in ordered:
        # KAPSAMA (containment) genişletmesi — ölçümle bulunan bir sızıntının düzeltmesi.
        # Eski sürüm çakışan span'i tamamen atıyordu; bu yüzden KISA ama yüksek skorlu bir
        # tespit, KENDİSİNİ İÇEREN uzun bir span'i bastırıp geri kalanını AÇIKTA bırakıyordu
        # (somut ölçüm: 20 karakterlik tam maskeli bir kişi adı, 0.99 skorlu 4 karakterlik bir
        # parça eklenince 4 karaktere düşüyordu — adın %80'i açığa çıkıyor). Sonuç: yeni bir
        # dedektör EKLEMEK kapsamı DÜŞÜREBİLİYORDU (Privacy Filter açıkken TAB'da doğrudan-
        # tanımlayıcı recall 0.638 → 0.574).
        #
        # Genişletme YALNIZ kapsama durumunda yapılır (kabul edilen span, reddedileni tamamen
        # içinde barındırıyorsa). KOŞULSUZ birleştirme denendi ve BİLEREK reddedildi: kısmi
        # çakışmada da birleştirmek, yanlış pozitif bir NER span'inin gerçek bir IBAN'ın
        # maskesini geriye doğru büyütmesine yol açıyor (regresyon testi
        # `test_resolve_spans_priority_prevents_partial_leak` bunu yakaladı) — yani aşırı-
        # maskelemeyi geri getiriyordu. Kapsama şartı, ölçülen sızıntıyı tam olarak kapatır ve
        # kısmi-çakışma semantiğini olduğu gibi bırakır.
        blocking = [a for a in accepted if not (s.end <= a.start or s.start >= a.end)]
        if not blocking:
            accepted.append(s)
            continue
        for a in blocking:
            # reddedilen `s`, kabul edilen `a`yı tamamen içeriyorsa `a` onun kapsamına genişler
            if s.start <= a.start and s.end >= a.end:
                accepted[accepted.index(a)] = a.model_copy(
                    update={"start": s.start, "end": s.end})
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
    # Masked-span count per detection stage (e.g. {"presidio": N, "privacy_filter": M, "deny": K}).
    by_source: dict[str, int] = Field(default_factory=dict)
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
        extra_allow_terms: list[str] | None = None,
    ) -> AnonymizationOutput:
        # Per-block: use block.language if set, else `language`. For mixed, run EN + TR analyzers
        # and merge spans via resolve_spans before applying deterministic placeholders.
        raise NotImplementedError("Implemented in Phase 3 (Presidio engine).")
