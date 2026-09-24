"""Detection on one text: every detector stage plus overlap resolution.

Shared by `Engine.anonymize()` (each unit's CURRENT text) and `Engine.detect()` (scored directly by
the evaluation harness), so the production path and the evaluated path cannot drift apart.

Each text is analysed as BOTH "en" and "tr" regardless of its detected language; the union
maximizes recall. Per-block language routing is a measured Faz 2 experiment, not a refactor.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from app.anonymization.gates import implausible_person_ner, lowercase_initial_ner
from app.anonymization.lists import deny_spans, is_allowed, keep_ranges
from app.anonymization.resolve import resolve_spans
from app.anonymization.spans import EntitySpan
from app.anonymization.types import ADJACENCY_SAFE

# Serialize access to the shared, cached AnalyzerEngine (spaCy pipelines are not thread-safe).
_ANALYZE_LOCK = threading.Lock()
LANGS = ("en", "tr")


@dataclass
class Detection:
    """Detection for one anonymize()/detect() call. The per-call cache is exact: detection depends
    only on the text and on the term lists, which are fixed within one call."""
    analyzer: object
    threshold: float
    deny: list[str]
    allow: list[str]
    deny_families: dict[str, str] = field(default_factory=dict)
    cache: dict[str, list[EntitySpan]] = field(default_factory=dict)

    def spans(self, text: str, *, cached: bool) -> list[EntitySpan]:
        if not text or not text.strip():
            return []
        if cached and text in self.cache:
            return self.cache[text]
        spans = self._analyze(text) + self._linewrap(text)
        spans += deny_spans(text, self.deny, self.deny_families)
        # Never-mask filtering and the orthographic gates run BEFORE resolution: removing a span
        # afterwards could not resurrect a real span it had suppressed through overlap.
        if self.allow:
            ranges = keep_ranges(text, self.allow)
            if ranges:
                spans = [s for s in spans if not is_allowed(s, ranges, text)]
        spans = [s for s in spans
                 if not lowercase_initial_ner(s, text) and not implausible_person_ner(s, text)]
        kept = resolve_spans(spans)
        if cached:
            self.cache[text] = kept
        return kept

    def _analyze(self, text: str) -> list[EntitySpan]:
        spans: list[EntitySpan] = []
        with _ANALYZE_LOCK:
            for lang in LANGS:
                for r in self.analyzer.analyze(text=text, language=lang,
                                               score_threshold=self.threshold):
                    spans.append(EntitySpan(start=r.start, end=r.end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        return spans

    def _linewrap(self, text: str) -> list[EntitySpan]:
        """Second pass on the text with '\\n' removed: a PDF can wrap a URL or key inside one block
        (stress pdf-split_run_pii-07). Only structural types, only spans that really cross a line
        break, and never across sentence punctuation ("açıklama.\\nİkinci" once became a URL)."""
        if "\n" not in text:
            return []
        keep = [i for i, ch in enumerate(text) if ch != "\n"]
        collapsed = "".join(text[i] for i in keep)
        spans: list[EntitySpan] = []
        with _ANALYZE_LOCK:
            for lang in LANGS:
                for r in self.analyzer.analyze(text=collapsed, language=lang,
                                               score_threshold=self.threshold):
                    span = _wrapped(text, keep, r, lang)
                    if span is not None:
                        spans.append(span)
        return spans


def _wrapped(text: str, keep: list[int], r, lang: str) -> EntitySpan | None:
    """The analyzer hit `r` on the collapsed text, mapped back — when it is a structural type
    that really crosses a line break without crossing sentence punctuation."""
    if r.entity_type not in ADJACENCY_SAFE:
        return None
    start, end = keep[r.start], keep[r.end - 1] + 1
    seg = text[start:end]
    if "\n" not in seg:
        return None
    if any(seg[k] == "\n" and k > 0 and seg[k - 1] in ".!?:;," for k in range(len(seg))):
        return None
    return EntitySpan(start=start, end=end, entity_type=r.entity_type, score=r.score, source=lang)
