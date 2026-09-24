"""The anonymization engine (Faz 1).

Presidio stays the recognizer framework (analyzer.py); this module orchestrates the passes:

  1. table pre-masking — values split across neighbouring cells (tables.py)
  2. the reviewer's forced masks — occurrence and document-wide masks (overrides.py)
  3. detection per unit — Presidio en + tr, a line-wrap pass, always-mask terms, never-mask filter,
     orthographic gates, overlap resolution (detection.py)
  4. variant propagation — spelling variants of masked values (propagate.py)

Every pass works on the CURRENT text of a unit exactly as before Faz 1, and each unit's
`EditBuffer` records the replacements in ORIGINAL coordinates, so `AnonymizationOutput.edits` ties
every placeholder to its original range for the review screen. The parity snapshots
(tests/parity) pin the output; never-mask CONTAINMENT (lists.py, review hardening) is an intended
change against the Faz-1 snapshots.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.anonymization import units as unit_naming
from app.anonymization.analyzer import get_analyzer
from app.anonymization.detection import LANGS, Detection
from app.anonymization.lists import contained, term_key, term_ranges
from app.anonymization.overrides import Overrides, apply_forced, keep_in_current
from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.propagate import VariantPools, find_variants
from app.anonymization.resolve import resolve_spans
from app.anonymization.spans import EditBuffer, EntitySpan, MaskEdit
from app.anonymization.tables import premask_table
from app.anonymization.types import family
from app.anonymization.units import cell_id, iter_units
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import Language

__all__ = [
    "AnonymizationEngine", "AnonymizationOutput", "Engine", "EntitySpan", "MaskEdit",
    "Overrides", "resolve_spans", "get_privacy_filter", "iter_units",
]


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
                  overrides: Overrides | None = None,
                  deny_families: dict[str, str] | None = None) -> AnonymizationOutput:
        raise NotImplementedError


@dataclass
class _Run:
    """State of one anonymize() call."""
    detection: Detection
    overrides: Overrides = field(default_factory=Overrides)
    mapper: PlaceholderMapper = field(default_factory=PlaceholderMapper)
    pools: VariantPools = field(default_factory=VariantPools)
    units: list[tuple[str, EditBuffer]] = field(default_factory=list)
    unit_ids: set[str] = field(default_factory=set)
    by_source: dict[str, int] = field(default_factory=dict)
    total: int = 0

    def reserve(self, base: str) -> str:
        return unit_naming.reserve_unit_id(self.unit_ids, base)  # shared with iter_units

    def keep(self, uid: str, buf: EditBuffer) -> list[tuple[int, int]]:
        return keep_in_current(buf, self.overrides.keep_ranges.get(uid, []))

    def count(self, category: str, n: int = 1) -> None:
        if n:
            self.by_source[category] = self.by_source.get(category, 0) + n
            self.total += n


def _clean(terms: list[str] | None) -> list[str]:
    return [t.strip() for t in (terms or []) if t and t.strip()]


def _source_category(source: str) -> str:
    return "presidio" if source in LANGS else (source or "presidio")


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
                  overrides: Overrides | None = None,
                  deny_families: dict[str, str] | None = None) -> AnonymizationOutput:
        """`deny_families`: the family of a globally masked term (keyed by term, any spelling);
        other always-mask terms become SENSITIVE."""
        ov = overrides or Overrides()
        run = _Run(detection=self._detection(extra_deny_terms, extra_allow_terms, deny_families,
                                             keep_terms=ov.keep_terms), overrides=ov)
        layout: list[tuple[Block, list[tuple[object, EditBuffer]] | EditBuffer]] = []
        for block in content.blocks:
            if block.type == BlockType.table:
                layout.append((block, self._mask_table(block, run)))
            else:
                uid = run.reserve(block.block_id)
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
        return self._detection(extra_deny_terms, extra_allow_terms).spans(text, cached=False)

    # ---------------------------------------------------------------- masking passes

    def _detection(self, deny: list[str] | None, allow: list[str] | None,
                   families: dict[str, str] | None = None, keep_terms=()) -> Detection:
        """An explicit always-mask term beats an IDENTICAL never-mask entry (a global mask of a
        word the seeded allow-list holds would otherwise be dropped silently); the reviewer's
        document keeps are added after that, so a document keep still beats a global mask."""
        deny = _clean(deny)
        deny_keys = {term_key(t) for t in deny}
        allow = [t for t in _clean(allow) if term_key(t) not in deny_keys]
        return Detection(analyzer=get_analyzer(), detector=get_privacy_filter(),
                         threshold=self.threshold, deny=deny,
                         allow=allow + _clean(list(keep_terms)),
                         deny_families=dict(families or {}))

    def _mask_table(self, block: Block, run: _Run) -> list[tuple[object, EditBuffer]]:
        uids = [run.reserve(cell_id(block, c.row, c.col)) for c in block.cells]
        keep: dict[tuple[int, int], list[tuple[int, int]]] = {}
        for cell, uid in zip(block.cells, uids, strict=True):
            keep.setdefault((cell.row, cell.col), []).extend(
                run.overrides.keep_ranges.get(uid, []))
        premask = premask_table(block, lambda text, cached: run.detection.spans(text,
                                                                                cached=cached),
                                run.mapper, keep)
        cells: list[tuple[object, EditBuffer]] = []
        for cell, uid in zip(block.cells, uids, strict=True):
            buf = EditBuffer(cell.text)
            for start, end, replacement, entity_type in premask.get((cell.row, cell.col), []):
                buf.apply_original(start, end, replacement, entity_type, "adjacency")
            self._mask_unit(buf, run, uid)
            run.units.append((uid, buf))
            cells.append((cell, buf))
        return cells

    def _mask_unit(self, buf: EditBuffer, run: _Run, uid: str) -> None:
        run.count("user", apply_forced(buf, run.overrides, uid, run.mapper))
        src = buf.text()
        kept = run.detection.spans(src, cached=True)
        keep = run.keep(uid, buf)
        if keep:  # "leave this occurrence unmasked": what lies inside it stays
            kept = [s for s in kept if not contained(s.start, s.end, keep, src)]
        for s in sorted(kept, key=lambda s: -s.start):  # right to left keeps offsets valid
            token = run.mapper.placeholder_for(family(s.entity_type), src[s.start:s.end])
            buf.apply(s.start, s.end, token, s.entity_type, s.source)
        for s in kept:
            run.count(_source_category(s.source))
        run.pools.collect(src, kept)

    def _propagate(self, run: _Run) -> None:
        surfaces = run.pools.surfaces()
        if not surfaces:
            return
        for uid, buf in run.units:
            text = buf.text()
            hits = find_variants(text, surfaces)
            # The reviewer's keeps (this occurrence, or this term in the document) hold here too.
            keep = run.keep(uid, buf) + term_ranges(text, run.overrides.keep_terms)
            if keep:
                hits = [h for h in hits if not contained(h[0], h[1], keep, text)]
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
