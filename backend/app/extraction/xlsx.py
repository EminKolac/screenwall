"""XLSX extraction via openpyxl. Each sheet becomes one table block with typed cells carrying
row/col indices and the A1 address. Cell count is capped during extraction (Codex H8) so a huge/
sparse workbook cannot exhaust memory; truncation is surfaced as a sanitized warning."""
from __future__ import annotations

import io

import openpyxl

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind

_MAX_CELLS = 200_000


class XlsxExtractor:
    kind = FileKind.xlsx

    def extract(self, data: bytes, filename: str) -> ExtractedContent:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        blocks: list[Block] = []
        warnings: list[str] = []
        count = 0
        truncated = False
        try:
            for ws in wb.worksheets:
                if truncated:
                    break
                cells: list[TableCell] = []
                for row in ws.iter_rows():
                    if truncated:
                        break
                    for cell in row:
                        if cell.value is None:
                            continue
                        if count >= _MAX_CELLS:
                            truncated = True
                            break
                        cells.append(TableCell(
                            row=cell.row - 1, col=cell.column - 1,
                            text=str(cell.value), address=cell.coordinate))
                        count += 1
                if cells:
                    blocks.append(Block(
                        block_id=f"sheet-{ws.title}", type=BlockType.table,
                        cells=cells, sheet=ws.title, location=f"sheet {ws.title}"))
            meta = {"sheets": ",".join(wb.sheetnames)}
        finally:
            wb.close()
        if truncated:
            warnings.append(f"workbook truncated at {_MAX_CELLS} cells")
        return ExtractedContent(kind=FileKind.xlsx, blocks=blocks, metadata=meta, warnings=warnings)
