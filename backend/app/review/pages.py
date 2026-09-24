"""PDF page images and marks for the review screen (mapping mode only).

Page images are rendered from the stored original on demand and never cached on disk. Marks are
found in the page's own character stream, WHOLE WORDS only ("Ali" never lights up inside
"Alibaba"); rects are normalized to 0..1 so the frontend overlay is resolution-independent.

Which occurrence — best effort. A value can occur several times on a page while a span means one
of them. With the extracted block's geometry (`bboxes`), only matches inside the span's block
count, and the span's rank among the whole-word occurrences of its block's units (a paragraph, or
every cell of a table, in extraction order) picks the match. When the counts disagree (the text
layer and the extraction read the block differently), every match in the block is marked rather
than a guessed one. Text that only exists through OCR has no text layer, so such pages show the
image without marks (the text view still has them).
"""
from __future__ import annotations

import re

_MAX_SIDE = 1600
_MAX_SCALE = 1.5
_SLACK = 1.0  # points: a match counts as inside a block when its centre is within this margin

Rect = tuple[float, float, float, float]


class PageNotFound(Exception):
    pass


def render_page(pdf_bytes: bytes, index: int) -> bytes:
    import fitz  # PyMuPDF

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if not 1 <= index <= pdf.page_count:
            raise PageNotFound
        page = pdf[index - 1]
        scale = min(_MAX_SCALE, _MAX_SIDE / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pix.tobytes("png")


def page_marks(pdf_bytes: bytes, index: int, payload: dict,
               bboxes: dict[str, list[float] | None] | None = None) -> dict:
    """`bboxes`: block id → [x0, y0, x1, y1] of the extracted PDF blocks (layer 2)."""
    import fitz  # PyMuPDF

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if not 1 <= index <= pdf.page_count:
            raise PageNotFound
        page = pdf[index - 1]
        width, height = page.rect.width, page.rect.height
        finder = _Finder(_char_stream(page),
                         [u for u in payload["units"] if u["page"] == index and u["original"]],
                         bboxes or {})
        marks = []
        for ref, kind, unit_id, start, end in _targets(payload):
            rects = finder.rects(unit_id, start, end)
            if rects:
                marks.append({"ref": ref, "kind": kind, "rects": [
                    [round(x0 / width, 5), round(y0 / height, 5),
                     round(x1 / width, 5), round(y1 / height, 5)] for x0, y0, x1, y1 in rects]})
        return {"index": index, "width": round(width, 2), "height": round(height, 2),
                "marks": marks}


def _targets(payload: dict):
    for s in payload["spans"]:
        yield s["id"], s["state"], s["unit_id"], s["start"], s["end"]
    for item in payload["items"]:
        if item["status"] == "open":
            yield item["id"], item["kind"], item["unit_id"], item["start"], item["end"]


def _char_stream(page) -> tuple[str, list[Rect | None]]:
    """The page's text layer as one string plus each character's box (None for the line breaks
    added between lines)."""
    chars: list[str] = []
    boxes: list[Rect | None] = []
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for ch in span.get("chars", []):
                    chars.append(ch["c"])
                    boxes.append(tuple(ch["bbox"]))
            chars.append("\n")
            boxes.append(None)
    return "".join(chars), boxes


def _whole_words(surface: str) -> re.Pattern[str] | None:
    parts = surface.split()
    if not parts or len("".join(parts)) < 2:
        return None
    body = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


class _Finder:
    """Whole-word matches of span surfaces on one page, narrowed to the referenced occurrence."""

    def __init__(self, stream: tuple[str, list[Rect | None]], units: list[dict],
                 bboxes: dict[str, list[float] | None]) -> None:
        self.text, self.boxes = stream
        self.units = units
        self.by_id = {u["id"]: u for u in units}
        self.bboxes = bboxes

    def rects(self, unit_id: str, start: int, end: int) -> list[Rect]:
        unit = self.by_id.get(unit_id)
        pattern = _whole_words(unit["original"][start:end]) if unit else None
        if pattern is None:
            return []
        bbox = self.bboxes.get(unit["block_id"])
        matches = [_line_rects(self.boxes, m.start(), m.end())
                   for m in pattern.finditer(self.text)]
        if bbox:
            matches = [m for m in matches if m and all(_inside(r, bbox) for r in m)]
        group = [u for u in self.units if u["block_id"] == unit["block_id"]] if bbox else self.units
        rank, total = _rank(group, unit_id, start, pattern)
        chosen = [matches[rank]] if rank is not None and total == len(matches) else matches
        return [r for m in chosen for r in m]


def _rank(group: list[dict], unit_id: str, start: int,
          pattern: re.Pattern[str]) -> tuple[int | None, int]:
    """The span's position among the whole-word occurrences in `group`, and their total."""
    seen, rank = 0, None
    for u in group:
        starts = [m.start() for m in pattern.finditer(u["original"])]
        if u["id"] == unit_id and start in starts:
            rank = seen + starts.index(start)
        seen += len(starts)
    return rank, seen


def _line_rects(boxes: list[Rect | None], start: int, end: int) -> list[Rect]:
    """One rect per text line covered by the characters [start, end)."""
    rects: list[Rect] = []
    cur: Rect | None = None
    for b in boxes[start:end]:
        if b is None:
            if cur:
                rects.append(cur)
            cur = None
            continue
        cur = b if cur is None else (min(cur[0], b[0]), min(cur[1], b[1]),
                                     max(cur[2], b[2]), max(cur[3], b[3]))
    if cur:
        rects.append(cur)
    return rects


def _inside(rect: Rect, bbox: list[float]) -> bool:
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    return (bbox[0] - _SLACK <= cx <= bbox[2] + _SLACK
            and bbox[1] - _SLACK <= cy <= bbox[3] + _SLACK)
