"""Extractor registry + the single entry point used by the ingest service.

Codex Phase-2 review (H2): parser exceptions are wrapped in `ExtractionFailed` (sanitized) so a
corrupt/encrypted-but-valid-magic file fails closed instead of surfacing a 500 with internals.
"""
from __future__ import annotations

from app.extraction.base import ExtractedContent, ExtractionFailed, UploadRejected, validate_upload
from app.extraction.docx import DocxExtractor
from app.extraction.pdf import PdfExtractor
from app.extraction.xlsx import XlsxExtractor
from app.models.document import FileKind

_EXTRACTORS = {
    FileKind.pdf: PdfExtractor(),
    FileKind.docx: DocxExtractor(),
    FileKind.xlsx: XlsxExtractor(),
}


def get_extractor(kind: FileKind):
    return _EXTRACTORS[kind]


def extract(data: bytes, filename: str, max_bytes: int) -> tuple[FileKind, ExtractedContent]:
    kind = validate_upload(data, filename, max_bytes)  # UploadRejected (typed) on bad input
    try:
        content = _EXTRACTORS[kind].extract(data, filename)
    except UploadRejected:
        raise
    except Exception as e:  # noqa: BLE001 — sanitized, fail-closed
        raise ExtractionFailed(f"could not parse {kind.value} file") from e
    return kind, content
