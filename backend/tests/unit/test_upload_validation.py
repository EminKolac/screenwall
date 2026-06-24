import pytest

from app.extraction.base import UploadRejected, validate_upload
from app.models.document import FileKind


def test_pdf_magic_ok():
    assert validate_upload(b"%PDF-1.7\n%...", "a.pdf", 10_000) == FileKind.pdf


def test_docx_magic_ok(docx_en):
    assert validate_upload(docx_en, "a.docx", 10_000_000) == FileKind.docx


def test_xlsx_magic_ok(xlsx_tr):
    assert validate_upload(xlsx_tr, "a.xlsx", 10_000_000) == FileKind.xlsx


def test_magic_mismatch_rejected():
    with pytest.raises(UploadRejected):
        validate_upload(b"hello world", "a.pdf", 10_000)


def test_bad_extension_rejected():
    with pytest.raises(UploadRejected):
        validate_upload(b"%PDF-1.7", "a.txt", 10_000)


def test_oversize_rejected():
    with pytest.raises(UploadRejected):
        validate_upload(b"%PDF" * 100, "a.pdf", 10)


def test_empty_rejected():
    with pytest.raises(UploadRejected):
        validate_upload(b"", "a.pdf", 10_000)
