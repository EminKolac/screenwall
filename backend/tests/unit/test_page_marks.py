"""PDF page marks (review hardening C15): whole words only, and the occurrence the span means.

Before, marks came from a plain substring search: "Ali" also lit up inside "Alibaba", and a value
that occurs twice on a page marked both occurrences for a span that refers to one.
"""
from __future__ import annotations

import re

from app.extraction.dispatcher import extract
from app.review.pages import page_marks
from tests.conftest import make_pdf


def _setup(line: str, value: str, nth: int):
    pdf = make_pdf([line])
    _kind, content = extract(pdf, "t.pdf", 10**8)
    block = next(b for b in content.blocks if value in b.text)
    starts = [m.start() for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", block.text)]
    start = starts[nth]
    unit = {"id": block.block_id, "block_id": block.block_id, "page": 1, "table": None,
            "original": block.text, "masked": block.text}
    payload = {"units": [unit], "items": [], "spans": [
        {"id": "s1", "state": "masked", "unit_id": block.block_id,
         "start": start, "end": start + len(value)}]}
    return pdf, payload, {b.block_id: b.bbox for b in content.blocks}


def _rects(marks: dict) -> list[list[float]]:
    return [r for m in marks["marks"] for r in m["rects"]]


def test_marks_match_whole_words_only() -> None:
    pdf, payload, bboxes = _setup("Alibaba bought shares and Ali signed.", "Ali", 0)
    rects = _rects(page_marks(pdf, 1, payload, bboxes))
    assert len(rects) == 1
    assert rects[0][0] > 0.3  # the standalone word, far right of "Alibaba" at the line start


def test_marks_whole_words_without_block_geometry_too() -> None:
    pdf, payload, _bboxes = _setup("Alibaba bought shares and Ali signed.", "Ali", 0)
    assert len(_rects(page_marks(pdf, 1, payload))) == 1


def test_only_the_referenced_occurrence_is_marked() -> None:
    pdf, first, bboxes = _setup("Ali met Ali at the office.", "Ali", 0)
    _pdf, second, _b = _setup("Ali met Ali at the office.", "Ali", 1)
    one, two = _rects(page_marks(pdf, 1, first, bboxes)), _rects(page_marks(pdf, 1, second, bboxes))
    assert len(one) == 1 and len(two) == 1
    assert one[0][0] < two[0][0]
