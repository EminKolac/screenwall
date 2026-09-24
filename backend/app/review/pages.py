"""PDF page images and marks for the review screen (mapping mode only).

Page images are rendered from the stored original on demand and never cached on disk. Marks are
found by searching each span's original surface on its page; rects are normalized to 0..1 so the
frontend overlay is resolution-independent. Text that only exists through OCR has no text layer
to search, so such pages show the image without marks (the text view still has them).
"""
from __future__ import annotations

_MAX_SIDE = 1600
_MAX_SCALE = 1.5


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


def page_marks(pdf_bytes: bytes, index: int, payload: dict) -> dict:
    import fitz  # PyMuPDF

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        if not 1 <= index <= pdf.page_count:
            raise PageNotFound
        page = pdf[index - 1]
        width, height = page.rect.width, page.rect.height
        units = {u["id"]: u for u in payload["units"] if u["page"] == index and u["original"]}
        marks = []
        for ref, kind, unit_id, start, end in _targets(payload):
            unit = units.get(unit_id)
            if unit is None:
                continue
            rects = _search(page, unit["original"][start:end])
            if rects:
                marks.append({"ref": ref, "kind": kind, "rects": [
                    [round(r.x0 / width, 5), round(r.y0 / height, 5),
                     round(r.x1 / width, 5), round(r.y1 / height, 5)] for r in rects]})
        return {"index": index, "width": round(width, 2), "height": round(height, 2),
                "marks": marks}


def _targets(payload: dict):
    for s in payload["spans"]:
        yield s["id"], s["state"], s["unit_id"], s["start"], s["end"]
    for item in payload["items"]:
        if item["status"] == "open":
            yield item["id"], item["kind"], item["unit_id"], item["start"], item["end"]


def _search(page, surface: str) -> list:
    """Rects of a surface on the page; a value wrapped over lines is searched line by line."""
    rects = []
    for part in (p.strip() for p in surface.splitlines()):
        if len(part) >= 2:
            rects.extend(page.search_for(part))
    return rects
