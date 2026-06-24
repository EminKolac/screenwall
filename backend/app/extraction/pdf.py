"""PDF extraction via PyMuPDF (fitz). Text + best-effort tables, in true page reading order.

Codex Phase-2 review: blocks are merged per page and sorted by (y, x) so mid-page tables keep
their position (H4); each block carries its bbox for later reconstruction. Table-finder failures
are recorded as sanitized warnings on the output, not logged (L3). Image-only/scanned PDFs yield
little text — the ingest layer routes empty extractions to human review (H2).
"""
from __future__ import annotations

import fitz  # PyMuPDF

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind


def _inside(inner: tuple, outer: tuple) -> bool:
    ix0, iy0, ix1, iy1 = inner
    ox0, oy0, ox1, oy1 = outer
    cx, cy = (ix0 + ix1) / 2, (iy0 + iy1) / 2
    return ox0 <= cx <= ox1 and oy0 <= cy <= oy1


class PdfExtractor:
    kind = FileKind.pdf

    def extract(self, data: bytes, filename: str) -> ExtractedContent:
        doc = fitz.open(stream=data, filetype="pdf")
        blocks: list[Block] = []
        warnings: list[str] = []
        bid = 0
        try:
            for pno in range(doc.page_count):
                page = doc[pno]
                page_items: list[tuple[float, float, Block]] = []
                table_bboxes: list[tuple] = []
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
                for b in page.get_text("blocks"):
                    x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
                    text = (text or "").strip()
                    if not text or any(_inside((x0, y0, x1, y1), bb) for bb in table_bboxes):
                        continue
                    page_items.append((y0, x0, Block(
                        block_id="", type=BlockType.paragraph, text=text, page=pno + 1,
                        bbox=[x0, y0, x1, y1], location=f"page {pno + 1}")))
                page_items.sort(key=lambda it: (it[0], it[1]))  # reading order
                for _, _, blk in page_items:
                    bid += 1
                    blk.block_id = f"p{pno + 1}-b{bid}"
                    blocks.append(blk)
            meta = {k: str(v) for k, v in (doc.metadata or {}).items() if v}
        finally:
            doc.close()
        return ExtractedContent(kind=FileKind.pdf, blocks=blocks, metadata=meta, warnings=warnings)
