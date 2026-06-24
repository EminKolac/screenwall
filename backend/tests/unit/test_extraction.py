from app.extraction.base import BlockType
from app.extraction.docx import DocxExtractor
from app.extraction.pdf import PdfExtractor
from app.extraction.xlsx import XlsxExtractor
from app.models.document import FileKind


def test_docx_structure(docx_en):
    c = DocxExtractor().extract(docx_en, "a.docx")
    assert c.kind == FileKind.docx
    assert any(b.type == BlockType.heading for b in c.blocks)
    table = next(b for b in c.blocks if b.type == BlockType.table)
    assert any(cell.text == "Name" for cell in table.cells)
    assert all(b.block_id for b in c.blocks)  # stable ids assigned
    assert "England" in c.plain_text and "John Smith" in c.plain_text


def test_xlsx_cells_with_addresses(xlsx_tr):
    c = XlsxExtractor().extract(xlsx_tr, "a.xlsx")
    assert c.blocks and c.blocks[0].type == BlockType.table
    cells = c.blocks[0].cells
    assert any(cell.address == "A1" for cell in cells)
    assert c.blocks[0].sheet
    assert "Ahmet Yılmaz" in c.plain_text


def test_pdf_text(pdf_en):
    c = PdfExtractor().extract(pdf_en, "a.pdf")
    assert c.kind == FileKind.pdf
    assert any(b.page == 1 for b in c.blocks)
    assert "finance team" in c.plain_text
