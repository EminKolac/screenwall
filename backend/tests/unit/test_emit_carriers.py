"""Round-trip tests for evaluation.corpus_bist10.emit_carriers: content written into a pdf/docx/
xlsx carrier must be recoverable by the app's own extractor — these carriers stand in for real
BIST documents in the balanced Part-B corpus, so they must be genuinely readable, not just
well-formed bytes."""
from __future__ import annotations

import pytest

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.extraction.dispatcher import extract
from app.models.document import FileKind
from evaluation.corpus_bist10.emit_carriers import emit, render_content_docx, render_content_xlsx

_MAX = 20 * 1024 * 1024


def _sample_content() -> ExtractedContent:
    return ExtractedContent(kind=FileKind.pdf, blocks=[
        Block(block_id="0", type=BlockType.heading, text="Annual Report Summary"),
        Block(block_id="1", type=BlockType.paragraph, text="Revenue increased in the period."),
        Block(block_id="2", type=BlockType.table, cells=[
            TableCell(row=0, col=0, text="Metric"), TableCell(row=0, col=1, text="Value"),
            TableCell(row=1, col=0, text="Net Income"), TableCell(row=1, col=1, text="1000"),
        ]),
    ])


def test_docx_carrier_roundtrips_heading_paragraph_and_table():
    data = render_content_docx(_sample_content())
    _, extracted = extract(data, "carrier.docx", _MAX)
    text = extracted.plain_text
    assert "Annual Report Summary" in text
    assert "Revenue increased in the period." in text
    assert "Net Income" in text and "1000" in text


def test_xlsx_carrier_roundtrips_heading_paragraph_and_table():
    data = render_content_xlsx(_sample_content())
    _, extracted = extract(data, "carrier.xlsx", _MAX)
    text = extracted.plain_text
    assert "Annual Report Summary" in text
    assert "Revenue increased in the period." in text
    assert "Net Income" in text and "1000" in text


def test_pdf_carrier_is_valid_and_extractable():
    data = emit(_sample_content(), "pdf")
    assert data.startswith(b"%PDF")
    _, extracted = extract(data, "carrier.pdf", _MAX)
    assert "Annual Report Summary" in extracted.plain_text


def test_emit_dispatches_all_three_formats():
    content = _sample_content()
    for fmt, magic in (("pdf", b"%PDF"), ("docx", b"PK"), ("xlsx", b"PK")):
        assert emit(content, fmt).startswith(magic)


def test_emit_rejects_unsupported_format():
    with pytest.raises(ValueError, match="unsupported carrier format"):
        emit(_sample_content(), "doc")


def test_docx_carrier_handles_empty_content():
    data = render_content_docx(ExtractedContent(kind=FileKind.pdf, blocks=[]))
    assert data.startswith(b"PK")  # still a valid (empty) docx, no crash


def test_xlsx_carrier_handles_empty_content():
    data = render_content_xlsx(ExtractedContent(kind=FileKind.pdf, blocks=[]))
    assert data.startswith(b"PK")


def _control_char_content() -> ExtractedContent:
    """Regression: real AKBNK annual reports contain C0 control chars (e.g. \x0b, \x1c) in their
    extracted text — python-docx raises ValueError and openpyxl raises IllegalCharacterError on
    these verbatim, which silently dropped 3/30 sources from a real build_balanced.py run."""
    dirty = "Özkaynak\x0b tutarı\x1c ve\x00 sermaye"
    return ExtractedContent(kind=FileKind.pdf, blocks=[
        Block(block_id="0", type=BlockType.heading, text=dirty),
        Block(block_id="1", type=BlockType.paragraph, text=dirty),
        Block(block_id="2", type=BlockType.table, cells=[
            TableCell(row=0, col=0, text=dirty),
        ]),
    ])


def test_docx_carrier_strips_illegal_xml_control_chars():
    data = render_content_docx(_control_char_content())
    _, extracted = extract(data, "carrier.docx", _MAX)
    assert "Özkaynak tutarı ve sermaye" in extracted.plain_text


def test_xlsx_carrier_strips_illegal_xml_control_chars():
    data = render_content_xlsx(_control_char_content())
    _, extracted = extract(data, "carrier.xlsx", _MAX)
    assert "Özkaynak tutarı ve sermaye" in extracted.plain_text
