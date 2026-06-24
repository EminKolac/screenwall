"""DOCX extraction via python-docx. Preserves document order (paragraphs + tables), detects
headings by style, and captures typed table cells + core-property metadata."""
from __future__ import annotations

import io

import docx as pydocx
from docx.document import Document as _Doc
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind


def _iter_block_items(parent):
    parent_elm = parent.element.body if isinstance(parent, _Doc) else parent._tc
    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


class DocxExtractor:
    kind = FileKind.docx

    def extract(self, data: bytes, filename: str) -> ExtractedContent:
        d = pydocx.Document(io.BytesIO(data))
        blocks: list[Block] = []
        bid = 0
        for item in _iter_block_items(d):
            if isinstance(item, Paragraph):
                text = item.text.strip()
                if not text:
                    continue
                bid += 1
                style = (item.style.name if item.style else "") or ""
                btype = (
                    BlockType.heading
                    if style.startswith(("Heading", "Title"))
                    else BlockType.paragraph
                )
                blocks.append(
                    Block(block_id=f"p{bid}", type=btype, text=text, location=f"para {bid}")
                )
            else:  # Table
                bid += 1
                cells: list[TableCell] = []
                for r, row in enumerate(item.rows):
                    for c, cell in enumerate(row.cells):
                        cells.append(TableCell(row=r, col=c, text=cell.text.strip()))
                blocks.append(
                    Block(block_id=f"tbl{bid}", type=BlockType.table, cells=cells, location=f"table {bid}")
                )
        cp = d.core_properties
        meta = {k: v for k, v in {"author": cp.author or "", "title": cp.title or ""}.items() if v}
        return ExtractedContent(kind=FileKind.docx, blocks=blocks, metadata=meta)
