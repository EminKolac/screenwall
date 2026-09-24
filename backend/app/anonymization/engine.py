"""The anonymization engine (Faz 1).

Presidio stays the recognizer framework (analyzer.py); this module orchestrates the passes:

  1. table pre-masking — values split across neighbouring cells (tables.py)
  2. detection per unit — Presidio en + tr, a line-wrap pass, always-mask terms, never-mask filter,
     orthographic gates, overlap resolution (resolve.py)
  3. variant propagation — spelling variants of masked values (propagate.py)

Every pass works on the CURRENT text of a unit exactly as before Faz 1, and each unit's
`EditBuffer` records the replacements in ORIGINAL coordinates. The masked output is therefore
byte-identical to the pre-Faz-1 engine (tests/parity), and `AnonymizationOutput.edits` ties every
placeholder to its original range for the review screen.

Each text block is analysed as BOTH "en" and "tr" regardless of its detected language; the union
maximizes recall. Per-block language routing is a measured Faz 2 experiment, not a refactor.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.anonymization.analyzer import get_analyzer
from app.anonymization.gates import implausible_person_ner, lowercase_initial_ner
from app.anonymization.lists import deny_spans, is_allowed, term_ranges
from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.propagate import VariantPools, find_variants
from app.anonymization.resolve import resolve_spans
from app.anonymization.spans import EditBuffer, EntitySpan, MaskEdit
from app.anonymization.tables import premask_table
from app.anonymization.types import ADJACENCY_SAFE, family, user_type
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import Language

__all__ = [
    "AnonymizationEngine", "AnonymizationOutput", "Engine", "EntitySpan", "MaskEdit",
    "Overrides", "resolve_spans", "get_privacy_filter",
]

# Serialize access to the shared, cached AnalyzerEngine (spaCy pipelines are not thread-safe).
_ANALYZE_LOCK = threading.Lock()
_LANGS = ("en", "tr")


def get_privacy_filter():
    """Optional local contextual detector (off by default). Module-level so tests can patch it."""
    from app.anonymization.privacy_filter import get_privacy_filter as _get
    return _get()


class AnonymizationOutput(BaseModel):
    content: ExtractedContent  # structure-preserving, anonymized
    entity_count: int = 0
    placeholders_used: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)  # masked spans per detection stage
    # Excluded from model_dump()/JSON so it cannot leak via API responses or logs.
    mapping: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)
    # unit id → replacements with original and masked offsets (positions only, never values).
    # Unit id: block_id for text blocks, "<block_id>:r<row>c<col>" for table cells.
    edits: dict[str, list[MaskEdit]] = Field(default_factory=dict)


class AnonymizationEngine:
    """Interface the pipeline depends on."""

    def anonymize(self, content: ExtractedContent, language: Language, *,
                  extra_deny_terms: list[str] | None = None,
                  extra_allow_terms: list[str] | None = None,
                  overrides: Overrides | None = None) -> AnonymizationOutput:
        raise NotImplementedError


def iter_units(content: ExtractedContent):
    """(unit_id, block, cell_or_None, text) in the exact order and naming the engine uses."""
    taken: set[str] = set()

    def reserve(base: str) -> str:
        uid, n = base, 1
        while uid in taken:
            n += 1
            uid = f"{base}#{n}"
        taken.add(uid)
        return uid

    for block in content.blocks:
        if block.type == BlockType.table:
            for cell in block.cells:
                yield reserve(_cell_id(block, cell.row, cell.col)), block, cell, cell.text
        else:
            yield reserve(block.block_id), block, None, block.text


@dataclass
class Overrides:
    """Human review decisions for one document, applied on top of detection.

    Ranges are in ORIGINAL unit coordinates (unit ids as in AnonymizationOutput.edits). With no
    overrides the engine behaves exactly as without them (parity-tested).
    """
    keep_ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    mask_ranges: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)  # family
    keep_terms: list[str] = field(default_factory=list)  # document-wide never-mask
    mask_terms: dict[str, str] = field(default_factory=dict)  # document-wide term -> family


@dataclass
class _Run:
    """State of one anonymize()/detect() call."""
    analyzer: object
    detector: object
    deny: list[str]
    allow: list[str]
    deny_families: dict[str, str] = field(default_factory=dict)
    overrides: Overrides = field(default_factory=Overrides)
    mapper: PlaceholderMapper = field(default_factory=PlaceholderMapper)
    pools: VariantPools = field(default_factory=VariantPools)
    cache: dict[str, list[EntitySpan]] = field(default_factory=dict)
    units: list[tuple[str, EditBuffer]] = field(default_factory=list)
    unit_ids: set[str] = field(default_factory=set)
    by_source: dict[str, int] = field(default_factory=dict)
    total: int = 0

    def reserve_unit_id(self, unit_id: str) -> str:
        uid, n = unit_id, 1
        while uid in self.unit_ids:  # duplicate cell coordinates get a stable suffix
            n += 1
            uid = f"{unit_id}#{n}"
        self.unit_ids.add(uid)
        return uid

    def keep_in_current(self, uid: str, buf: EditBuffer) -> list[tuple[int, int]]:
        """The unit's keep ranges mapped onto its current text."""
        ranges = (buf.current_range(s, e) for s, e in self.overrides.keep_ranges.get(uid, []))
        return [r for r in ranges if r is not None]


def _clean(terms: list[str] | None) -> list[str]:
    return [t.strip() for t in (terms or []) if t and t.strip()]


def _cell_id(block: Block, row: int, col: int) -> str:
    return f"{block.block_id}:r{row}c{col}"


def _source_category(source: str) -> str:
    return "presidio" if source in _LANGS else (source or "presidio")


class Engine(AnonymizationEngine):
    def __init__(self, score_threshold: float | None = None) -> None:
        self._threshold = score_threshold

    @property
    def threshold(self) -> float:
        if self._threshold is not None:
            return self._threshold
        from app.config import get_settings
        return get_settings().anonymizer_score_threshold

    # ---------------------------------------------------------------- public API

    def anonymize(self, content: ExtractedContent, language: Language, *,
                  extra_deny_terms: list[str] | None = None,
                  extra_allow_terms: list[str] | None = None,
                  overrides: Overrides | None = None) -> AnonymizationOutput:
        ov = overrides or Overrides()
        run = self._new_run([*(extra_deny_terms or []), *ov.mask_terms],
                            [*(extra_allow_terms or []), *ov.keep_terms])
        run.deny_families = dict(ov.mask_terms)
        run.overrides = ov
        layout: list[tuple[Block, list[tuple[object, EditBuffer]] | EditBuffer]] = []
        for block in content.blocks:
            if block.type == BlockType.table:
                layout.append((block, self._mask_table(block, run)))
            else:
                uid = run.reserve_unit_id(block.block_id)
                buf = EditBuffer(block.text)
                self._mask_unit(buf, run, uid)
                run.units.append((uid, buf))
                layout.append((block, buf))
        self._propagate(run)
        blocks = [self._render_block(block, part) for block, part in layout]
        # Extractor metadata (PDF/DOCX author and title, XLSX sheet names) is raw and un-audited;
        # the anonymized copy never carries it, in either storage mode.
        return AnonymizationOutput(
            content=content.model_copy(update={"blocks": blocks, "metadata": {}}),
            entity_count=run.total,
            placeholders_used=run.mapper.counts(),
            by_source=run.by_source,
            mapping=dict(run.mapper.mapping),
            edits={uid: buf.edits() for uid, buf in run.units},
        )

    def detect(self, text: str, *, extra_deny_terms: list[str] | None = None,
               extra_allow_terms: list[str] | None = None) -> list[EntitySpan]:
        """Resolved spans on the ORIGINAL text, without placeholders — the detection half of
        anonymize(), scored directly by the evaluation harness."""
        run = self._new_run(extra_deny_terms, extra_allow_terms)
        return self._detect(text, run, cached=False)

    # ---------------------------------------------------------------- masking passes

    def _new_run(self, deny: list[str] | None, allow: list[str] | None) -> _Run:
        return _Run(analyzer=get_analyzer(), detector=get_privacy_filter(),
                    deny=_clean(deny), allow=_clean(allow))

    def _mask_table(self, block: Block, run: _Run) -> list[tuple[object, EditBuffer]]:
        premask = premask_table(
            block, lambda text, cached: self._detect(text, run, cached=cached), run.mapper)
        cells: list[tuple[object, EditBuffer]] = []
        for cell in block.cells:
            uid = run.reserve_unit_id(_cell_id(block, cell.row, cell.col))
            buf = EditBuffer(cell.text)
            for start, end, replacement, entity_type in premask.get((cell.row, cell.col), []):
                buf.apply_original(start, end, replacement, entity_type, "adjacency")
            self._mask_unit(buf, run, uid)
            run.units.append((uid, buf))
            cells.append((cell, buf))
        return cells

    def _apply_forced(self, buf: EditBuffer, run: _Run, uid: str) -> None:
        """A reviewer's "mask this occurrence" lands before detection, like a pre-mask."""
        for start, end, fam in run.overrides.mask_ranges.get(uid, []):
            if start >= end or end > len(buf.original) or buf.overlaps_edit(start, end):
                continue
            token = run.mapper.placeholder_for(fam, buf.original[start:end])
            buf.apply_original(start, end, token, user_type(fam), "user")

    def _mask_unit(self, buf: EditBuffer, run: _Run, uid: str) -> None:
        self._apply_forced(buf, run, uid)
        src = buf.text()
        kept = self._detect(src, run, cached=True)
        keep = run.keep_in_current(uid, buf)
        if keep:  # "leave this occurrence unmasked"
            kept = [s for s in kept if not any(s.start < b and a < s.end for a, b in keep)]
        for s in sorted(kept, key=lambda s: -s.start):  # right to left keeps offsets valid
            token = run.mapper.placeholder_for(family(s.entity_type), src[s.start:s.end])
            buf.apply(s.start, s.end, token, s.entity_type, s.source)
        run.total += len(kept)
        for s in kept:
            cat = _source_category(s.source)
            run.by_source[cat] = run.by_source.get(cat, 0) + 1
        run.pools.collect(src, kept)

    def _propagate(self, run: _Run) -> None:
        surfaces = run.pools.surfaces()
        if not surfaces:
            return
        for uid, buf in run.units:
            text = buf.text()
            hits = find_variants(text, surfaces)
            keep = run.keep_in_current(uid, buf)
            if keep:
                hits = [h for h in hits if not any(h[0] < b and a < h[1] for a, b in keep)]
            for start, end, fam, mode in sorted(hits, key=lambda h: -h[0]):
                token = run.mapper.placeholder_for(fam, text[start:end])
                buf.apply(start, end, token, fam, f"propagation:{mode}")

    @staticmethod
    def _render_block(block: Block, part) -> Block:
        if isinstance(part, EditBuffer):
            return block.model_copy(update={"text": part.text()})
        cells = [cell.model_copy(update={"text": buf.text()}) for cell, buf in part]
        # The raw sheet name is un-audited; the audited name travels as a heading block.
        return block.model_copy(update={"cells": cells, "sheet": None})

    # ---------------------------------------------------------------- detection

    def _detect(self, text: str, run: _Run, *, cached: bool) -> list[EntitySpan]:
        """All detection stages + overlap resolution. Shared by anonymize() and detect() so the
        production path and the evaluated path cannot drift apart. The per-document cache is exact:
        detection depends only on the text and the two term lists, fixed within one call."""
        if not text or not text.strip():
            return []
        if cached and text in run.cache:
            return run.cache[text]
        spans = self._analyze(text, run) + self._linewrap(text, run)
        spans += deny_spans(text, run.deny, run.deny_families)
        if run.detector is not None:
            spans.extend(run.detector.detect(text))
        # Never-mask filtering and the orthographic gates run BEFORE resolution: removing a span
        # afterwards could not resurrect a real span it had suppressed through overlap.
        if run.allow:
            ranges = term_ranges(text, run.allow)
            if ranges:
                spans = [s for s in spans if not is_allowed(s, ranges)]
        spans = [s for s in spans
                 if not lowercase_initial_ner(s, text) and not implausible_person_ner(s, text)]
        kept = resolve_spans(spans)
        if cached:
            run.cache[text] = kept
        return kept

    def _analyze(self, text: str, run: _Run) -> list[EntitySpan]:
        spans: list[EntitySpan] = []
        with _ANALYZE_LOCK:
            for lang in _LANGS:
                for r in run.analyzer.analyze(text=text, language=lang,
                                              score_threshold=self.threshold):
                    spans.append(EntitySpan(start=r.start, end=r.end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        return spans

    def _linewrap(self, text: str, run: _Run) -> list[EntitySpan]:
        """Second pass on the text with '\\n' removed: a PDF can wrap a URL or key inside one block
        (stress pdf-split_run_pii-07). Only structural types, only spans that really cross a line
        break, and never across sentence punctuation ("açıklama.\\nİkinci" once became a URL)."""
        if "\n" not in text:
            return []
        keep = [i for i, ch in enumerate(text) if ch != "\n"]
        collapsed = "".join(text[i] for i in keep)
        spans: list[EntitySpan] = []
        with _ANALYZE_LOCK:
            for lang in _LANGS:
                for r in run.analyzer.analyze(text=collapsed, language=lang,
                                              score_threshold=self.threshold):
                    if r.entity_type not in ADJACENCY_SAFE:
                        continue
                    start, end = keep[r.start], keep[r.end - 1] + 1
                    seg = text[start:end]
                    if "\n" not in seg:
                        continue
                    if any(seg[k] == "\n" and k > 0 and seg[k - 1] in ".!?:;,"
                           for k in range(len(seg))):
                        continue
                    spans.append(EntitySpan(start=start, end=end, entity_type=r.entity_type,
                                            score=r.score, source=lang))
        return spans
