"""Table row pre-masking: values split across neighbouring cells.

OOXML split runs cut a value in the middle ("0532 764" | "21 09"), so no detector fires on either
cell alone (GoldBench stress `split_run_pii`). Two passes per row, both limited to structural types
(TYPES.adjacency_safe) because joining cells creates synthetic context that fools statistical NER:

1. Runs of 2+ adjacent cells that are clean on their own are joined WITHOUT a separator and
   re-detected; only spans that cross a cell boundary are kept. The first cell carries the
   placeholder, the other cells lose their fragment. (Joining a cell that already holds PII once
   turned "0532 764 21 09" + "42" into a US_SSN — measured, regression-tested.)
2. Truncated edge: a structural span ending exactly at a cell's end may extend into the next clean
   cell, but only as the SAME type from the SAME start (stress xlsx-split_run_pii-00).

Returns edits in ORIGINAL cell coordinates; the engine applies them to each cell's EditBuffer.
"""
from __future__ import annotations

from collections.abc import Callable

from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.spans import EntitySpan
from app.anonymization.types import ADJACENCY_SAFE, family
from app.extraction.base import Block

CellEdit = tuple[int, int, str, str]  # (start, end, replacement, entity_type)
Detect = Callable[[str, bool], list[EntitySpan]]  # (text, use_cache) -> resolved spans


def premask_table(block: Block, detect: Detect, mapper: PlaceholderMapper
                  ) -> dict[tuple[int, int], list[CellEdit]]:
    by_row: dict[int, list] = {}
    for cell in block.cells:
        by_row.setdefault(cell.row, []).append(cell)
    edits: dict[tuple[int, int], list[CellEdit]] = {}
    for row_cells in by_row.values():
        ordered = sorted(row_cells, key=lambda c: c.col)
        per_cell = premask_row([c.text for c in ordered], detect, mapper)
        for cell, cell_edits in zip(ordered, per_cell, strict=True):
            edits[(cell.row, cell.col)] = cell_edits
    return edits


def premask_row(texts: list[str], detect: Detect, mapper: PlaceholderMapper
                ) -> list[list[CellEdit]]:
    edits: list[list[CellEdit]] = [[] for _ in texts]
    if len(texts) < 2:
        return edits
    clean = [not (t.strip() and detect(t, True)) for t in texts]
    i, n = 0, len(texts)
    while i < n:
        if not clean[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and clean[j + 1]:
            j += 1
        if j > i:
            _merge_run(texts, edits, i, j, detect, mapper)
        i = j + 1
    for k in range(n - 1):
        if clean[k] or not clean[k + 1] or edits[k] or edits[k + 1]:
            continue
        _extend_truncated_edge(texts, edits, k, detect, mapper)
    return edits


def _merge_run(texts: list[str], edits: list[list[CellEdit]], i: int, j: int,
               detect: Detect, mapper: PlaceholderMapper) -> None:
    offsets: list[tuple[int, int]] = []
    pos = 0
    for k in range(i, j + 1):
        offsets.append((pos, pos + len(texts[k])))
        pos += len(texts[k])
    joined = "".join(texts[i:j + 1])
    for s in detect(joined, False):
        first = next((k for k, (a, b) in enumerate(offsets) if a <= s.start < b), None)
        last = next((k for k, (a, b) in enumerate(offsets) if a < s.end <= b), None)
        if first is None or last is None or first == last:
            continue
        if s.entity_type not in ADJACENCY_SAFE:
            continue
        token = mapper.placeholder_for(family(s.entity_type), joined[s.start:s.end])
        for k in range(first, last + 1):
            a, b = offsets[k]
            lo, hi = max(s.start, a) - a, min(s.end, b) - a
            if lo < hi:
                edits[i + k].append((lo, hi, token if k == first else "", s.entity_type))


def _extend_truncated_edge(texts: list[str], edits: list[list[CellEdit]], k: int,
                           detect: Detect, mapper: PlaceholderMapper) -> None:
    left = texts[k]
    edge = [s for s in detect(left, True)
            if s.entity_type in ADJACENCY_SAFE and s.end == len(left)]
    if len(edge) != 1:
        return
    e0 = edge[0]
    joined = left + texts[k + 1]
    for s in detect(joined, False):
        if s.entity_type == e0.entity_type and s.start == e0.start and s.end > len(left):
            token = mapper.placeholder_for(family(s.entity_type), joined[s.start:s.end])
            edits[k].append((s.start, len(left), token, s.entity_type))
            edits[k + 1].append((0, s.end - len(left), "", s.entity_type))
            return
