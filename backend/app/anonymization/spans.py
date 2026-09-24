"""Span and edit data structures.

`EntitySpan` is a detection on some text. `EditBuffer` records every replacement made to one text
unit (a paragraph or a table cell) in ORIGINAL coordinates while the masking passes keep working on
the CURRENT text exactly as before. At the end it yields the masked text plus a list of `MaskEdit`s
that tie each placeholder to its original range — the review screen needs both offsets.
"""
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel


class EntitySpan(BaseModel):
    start: int
    end: int
    entity_type: str
    score: float = 0.0
    source: str = ""  # detector stage / recognizer language (for evidence and calibration)

    @property
    def length(self) -> int:
        return self.end - self.start


class MaskEdit(BaseModel):
    """One replacement in a unit. Carries positions and labels only — never the original value."""
    start: int  # original offsets (Python str indices)
    end: int
    masked_start: int  # offsets in the masked text
    masked_end: int
    text: str  # replacement text: "<PERSON_1>", or "" for a cell-continuation fragment
    entity_type: str
    source: str


@dataclass
class _Edit:
    start: int
    end: int
    text: str
    entity_type: str
    source: str


class EditBuffer:
    """Replacement log for one text unit.

    `apply()` takes coordinates in the CURRENT text (what earlier passes produced) and records the
    replacement against the ORIGINAL text. Edits stay sorted and non-overlapping; an operation that
    overlaps an earlier replacement absorbs it, keeping the rendered text byte-identical to a plain
    string splice.
    """

    def __init__(self, original: str) -> None:
        self.original = original
        self._edits: list[_Edit] = []

    # ---------------------------------------------------------------- rendering

    def text(self) -> str:
        parts: list[str] = []
        cur = 0
        for e in self._edits:
            parts.append(self.original[cur:e.start])
            parts.append(e.text)
            cur = e.end
        parts.append(self.original[cur:])
        return "".join(parts)

    def edits(self) -> list[MaskEdit]:
        out: list[MaskEdit] = []
        cur = 0  # position in the masked text
        prev = 0  # position in the original text
        for e in self._edits:
            cur += e.start - prev
            out.append(MaskEdit(start=e.start, end=e.end, masked_start=cur,
                                masked_end=cur + len(e.text), text=e.text,
                                entity_type=e.entity_type, source=e.source))
            cur += len(e.text)
            prev = e.end
        return out

    # ---------------------------------------------------------------- mutation

    def apply_original(self, start: int, end: int, text: str,
                       entity_type: str, source: str) -> None:
        """Record a replacement given in ORIGINAL coordinates (used for table pre-masking)."""
        self._insert(_Edit(start, end, text, entity_type, source))

    def apply(self, cur_start: int, cur_end: int, text: str, entity_type: str, source: str) -> None:
        """Replace [cur_start, cur_end) of the CURRENT text."""
        segments = list(self._segments())
        hit = [s for s in segments if s[4] is not None and _overlaps(s, cur_start, cur_end)]
        # Original index of the first and last CHARACTER of the range, when they are literal text.
        first = _literal_origin(segments, cur_start)
        last = _literal_origin(segments, cur_end - 1)
        if not hit:
            # No replacement inside the range, so both ends are literal characters.
            self._insert(_Edit(first, last + 1, text, entity_type, source))
            return
        # The operation overlaps earlier replacements: absorb them into one edit whose text
        # reproduces the current-text splice exactly.
        c_start = min(cur_start, hit[0][0])
        c_end = max(cur_end, hit[-1][1])
        current = self.text()
        merged = current[c_start:cur_start] + text + current[cur_end:c_end]
        o_start = min([hit[0][4].start] + ([first] if first is not None else []))
        o_end = max([hit[-1][4].end] + ([last + 1] if last is not None else []))
        self._edits = [e for e in self._edits if all(e is not s[4] for s in hit)]
        self._insert(_Edit(o_start, o_end, merged, entity_type, source))

    # ---------------------------------------------------------------- internals

    def _insert(self, edit: _Edit) -> None:
        for e in self._edits:
            if e.start < edit.end and edit.start < e.end:
                raise ValueError("overlapping edit in original coordinates")
        self._edits.append(edit)
        self._edits.sort(key=lambda e: (e.start, e.end))

    def _segments(self):
        """Yield (cur_start, cur_end, orig_start, orig_end, edit_or_None) over the current text."""
        cur = 0
        orig = 0
        for e in self._edits:
            if e.start > orig:
                yield (cur, cur + e.start - orig, orig, e.start, None)
                cur += e.start - orig
            yield (cur, cur + len(e.text), e.start, e.end, e)
            cur += len(e.text)
            orig = e.end
        yield (cur, cur + len(self.original) - orig, orig, len(self.original), None)


def _overlaps(seg, start: int, end: int) -> bool:
    c0, c1 = seg[0], seg[1]
    if c0 == c1:  # an empty replacement is covered only when strictly inside the range
        return start < c0 < end
    return c0 < end and start < c1


def _literal_origin(segments, pos: int) -> int | None:
    """Original index of the current-text character at `pos`, or None if it is replacement text."""
    for c0, c1, o0, _o1, edit in segments:
        if edit is None and c0 <= pos < c1:
            return o0 + (pos - c0)
    return None
