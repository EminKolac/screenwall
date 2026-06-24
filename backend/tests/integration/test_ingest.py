import pytest

from app.config import get_settings
from app.extraction.base import UploadRejected
from app.models.document import DocumentStatus, Language
from app.services.ingest import ingest


def test_ingest_mixed(docx_mixed):
    doc, content = ingest(docx_mixed, "side.docx", get_settings())
    assert doc.status == DocumentStatus.EXTRACTED
    assert doc.language == Language.mixed
    assert len(content.blocks) > 0


def test_ingest_turkish(docx_tr):
    doc, _ = ingest(docx_tr, "sozlesme.docx", get_settings())
    assert doc.language == Language.tr


def test_ingest_english_pdf(pdf_en):
    doc, content = ingest(pdf_en, "report.pdf", get_settings())
    assert doc.language == Language.en
    assert content.plain_text


def test_ingest_rejects_bad_upload():
    with pytest.raises(UploadRejected):
        ingest(b"not a real file", "x.pdf", get_settings())
