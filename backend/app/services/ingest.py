"""Ingest: validate → extract → detect language, plus the reasons a document needs a human.

Empty extraction (scanned/image-only files) is not a success, and neither is a PARTIAL capture — a
page needed OCR but Tesseract was unavailable, an XLSX hit the cell cap, or a mostly-image page
kept its image text unread. Each of these is a blocking reason: the document goes to review,
never to auto-approval. Corrupt files raise `ExtractionFailed`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.config import Settings
from app.extraction.base import (
    IMAGE_TEXT_UNREAD,
    OCR_UNAVAILABLE,
    WORKBOOK_TRUNCATED,
    ExtractedContent,
)
from app.extraction.dispatcher import extract
from app.language.detector import detect_content_language
from app.models.document import Document, DocumentStatus, FileKind, Language

# Warning prefix → (reason code, sentence shown to the reviewer).
_BLOCKING = {
    OCR_UNAVAILABLE: ("ocr_unavailable", "Taranmış bir sayfa okunamadı (OCR kullanılamadı); "
                                          "belgenin bir bölümü hiç çıkarılmamış olabilir."),
    WORKBOOK_TRUNCATED: ("workbook_truncated",
                         "Çalışma kitabı hücre sınırını aştı; tablonun tamamı okunmadı."),
    IMAGE_TEXT_UNREAD: ("image_text_unread", "Bir sayfanın büyük bölümü görüntü, ama sayfada "
                                              "yeterli metin olduğu için OCR çalışmadı; görüntü "
                                              "içindeki yazı okunmamış olabilir."),
}
_NO_TEXT = ("no_text", "Belgeden hiç metin çıkarılamadı (büyük olasılıkla tamamı görüntü).")


@dataclass
class ExtractResult:
    kind: FileKind
    content: ExtractedContent
    language: Language
    reasons: list[tuple[str, str]] = field(default_factory=list)  # blocking (code, sentence)

    @property
    def has_text(self) -> bool:
        return bool(self.content.plain_text.strip())


def extract_content(data: bytes, filename: str, settings: Settings) -> ExtractResult:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    kind, content = extract(data, filename, max_bytes)  # UploadRejected / ExtractionFailed
    reasons = [pair for prefix, pair in _BLOCKING.items()
               if any(w.startswith(prefix) for w in content.warnings)]
    has_text = bool(content.plain_text.strip())
    if not has_text:
        content.warnings.append("no extractable text (possibly scanned/image-only)")
        reasons.append(_NO_TEXT)
    language = detect_content_language(content) if has_text else Language.unknown
    return ExtractResult(kind=kind, content=content, language=language, reasons=reasons)


def new_document(filename: str, kind: FileKind, mode: str) -> Document:
    doc = Document(id=uuid.uuid4().hex, filename=filename, kind=kind)
    doc.mode = mode  # type: ignore[assignment]
    doc.transition(DocumentStatus.QUEUED)
    return doc


def ingest(data: bytes, filename: str, settings: Settings) -> tuple[Document, ExtractedContent]:
    """Pre-v2 entry point (kept for callers and tests): one call that extracts and classifies."""
    result = extract_content(data, filename, settings)
    doc = Document(id=uuid.uuid4().hex, filename=filename, kind=result.kind)
    doc.language = result.language
    for code, text in result.reasons:
        doc.add_reason(code, text)
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW if result.reasons
                   else DocumentStatus.EXTRACTED)
    return doc, result.content
