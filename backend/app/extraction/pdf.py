"""PDF extraction via PyMuPDF (fitz). Text + best-effort tables, in true page reading order.

Image-only / scanned pages carry no text layer, so their PII would be invisible to anonymization
(this was the "Türk Telekom baked into a slide image" leak). When a page's text layer is sparse
(< _MIN_TEXT_PER_PAGE chars) we OCR it (Tesseract, tur+eng) and use the OCR'd text, which then
flows through the normal anonymize + audit loop. If a page needs OCR but Tesseract is unavailable
or errors, we do NOT emit partial text: an `OCR_UNAVAILABLE` warning is recorded and `ingest`
routes the document to human review (fail-closed).

Codex Phase-2 review: text blocks are merged per page and sorted by (y, x) so mid-page tables keep
their position (H4); each block carries its bbox. Table-finder failures are sanitized warnings (L3).
"""
from __future__ import annotations

import os
import shutil

import fitz  # PyMuPDF

from app.extraction.base import OCR_UNAVAILABLE, Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind

# PyMuPDF reads Tesseract's tessdata via TESSDATA_PREFIX at OCR-call time (not import). Point it at
# Homebrew's location ONLY when unset AND that dir exists — otherwise leave it alone so Tesseract
# uses its own default (Linux / Intel Mac / custom installs) instead of a pinned nonexistent path.
_DEFAULT_TESSDATA = "/opt/homebrew/share/tessdata"
if not os.environ.get("TESSDATA_PREFIX") and os.path.isdir(_DEFAULT_TESSDATA):
    os.environ["TESSDATA_PREFIX"] = _DEFAULT_TESSDATA

_OCR_LANG = "tur+eng"
_OCR_DPI = 200
_MIN_TEXT_PER_PAGE = 50  # below this a page is treated as image/scanned and OCR'd


def _tesseract_available() -> bool:
    return bool(shutil.which("tesseract"))


def _significant_raster(page, min_coverage: float = 0.15) -> bool:
    """True if images cover a meaningful fraction of the page — evidence of scanned/image content.

    Used so OCR (and thus fail-closed human review when Tesseract is missing) is triggered by
    actual raster content, not merely by a page having little text (a complete one-line PDF must
    not be forced into review).
    """
    try:
        infos = page.get_image_info()
    except Exception:  # noqa: BLE001
        return bool(page.get_images())  # fallback: any image present at all
    page_area = abs(page.rect.width * page.rect.height) or 1.0
    covered = 0.0
    for im in infos:
        bb = im.get("bbox")
        if bb:
            r = fitz.Rect(bb)
            covered += abs(r.width * r.height)
    return (covered / page_area) >= min_coverage


def _inside(inner: tuple, outer: tuple) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    return ox0 <= cx <= ox1 and oy0 <= cy <= oy1


class PdfExtractor:
    kind = FileKind.pdf

    def _ocr_textpage(self, page, warnings: list[str]):
        """OCR one sparse/image page → a TextPage, or None (recording a fail-closed warning)."""
        if not _tesseract_available():
            if OCR_UNAVAILABLE not in warnings:
                warnings.append(OCR_UNAVAILABLE)
            return None
        try:
            return page.get_textpage_ocr(language=_OCR_LANG, dpi=_OCR_DPI, full=True)
        except Exception:  # noqa: BLE001 — any OCR failure fails closed, never fake text
            if OCR_UNAVAILABLE not in warnings:
                warnings.append(OCR_UNAVAILABLE)
            return None

    def extract(self, data: bytes, filename: str) -> ExtractedContent:
        doc = fitz.open(stream=data, filetype="pdf")
        blocks: list[Block] = []
        warnings: list[str] = []
        bid = 0
        try:
            for pno in range(doc.page_count):
                page = doc[pno]
                ocr_tp = None
                if len(page.get_text().strip()) < _MIN_TEXT_PER_PAGE and _significant_raster(page):
                    ocr_tp = self._ocr_textpage(page, warnings)
                page_items: list[tuple[float, float, Block]] = []
                table_bboxes: list[tuple] = []
                if ocr_tp is None:  # only detect tables on a native text layer (unreliable on OCR)
                    try:
                        found = page.find_tables()
                        tables = list(found.tables) if found else []
                    except Exception:  # noqa: BLE001 — best-effort
                        tables = []
                        warnings.append(f"table detection failed on page {pno + 1}")
                    for t in tables:
                        cells = [
                            TableCell(row=r, col=c, text=(val or "").strip())
                            for r, row in enumerate(t.extract())
                            for c, val in enumerate(row)
                        ]
                        if cells:
                            bb = tuple(t.bbox)
                            page_items.append((bb[1], bb[0], Block(
                                block_id="", type=BlockType.table, cells=cells, page=pno + 1,
                                bbox=list(bb), location=f"page {pno + 1} table")))
                            table_bboxes.append(bb)
                text_blocks = (
                    page.get_text("blocks", textpage=ocr_tp) if ocr_tp is not None
                    else page.get_text("blocks")
                )
                loc = f"page {pno + 1} (ocr)" if ocr_tp is not None else f"page {pno + 1}"
                for b in text_blocks:
                    x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                    text = (text or "").strip()
                    if not text or any(_inside((x0, y0, x1, y1), bb) for bb in table_bboxes):
                        continue
                    page_items.append((y0, x0, Block(
                        block_id="", type=BlockType.paragraph, text=text, page=pno + 1,
                        bbox=[x0, y0, x1, y1], location=loc)))
                page_items.sort(key=lambda it: (it[0], it[1]))  # reading order
                for _, _, blk in page_items:
                    bid += 1
                    blk.block_id = f"p{pno + 1}-b{bid}"
                    blocks.append(blk)
            meta = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
        finally:
            doc.close()
        return ExtractedContent(kind=FileKind.pdf, blocks=blocks, metadata=meta, warnings=warnings)
