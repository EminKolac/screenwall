"""Ingest service: validate → extract → detect language. The single function the API calls.

Codex Phase-2 review (H2): empty extraction (scanned/image-only PDFs, etc.) is NOT a success —
it routes to human review. Corrupt files raise `ExtractionFailed` from the dispatcher and
propagate to the API as 422. Persistence to storage layers is wired in Phase 5.

v1 fail-closed: extraction can only PARTIALLY capture a document — a page needed OCR but Tesseract
was unavailable (`OCR_UNAVAILABLE`), or an XLSX hit the cell cap (`WORKBOOK_TRUNCATED`). Auto-
approving such a document could ship content that was never anonymized/audited, so any blocking
warning also routes to human review.
"""
from __future__ import annotations

import uuid

from app.config import Settings
from app.extraction.base import (
    IMAGE_TEXT_UNREAD,
    OCR_UNAVAILABLE,
    WORKBOOK_TRUNCATED,
    ExtractedContent,
)
from app.extraction.dispatcher import extract
from app.language.detector import detect_content_language
from app.models.document import Document, DocumentStatus, Language

_BLOCKING_WARNINGS = (OCR_UNAVAILABLE, WORKBOOK_TRUNCATED, IMAGE_TEXT_UNREAD)

# Uyarı kodu → gözden geçirene gösterilecek cümle. Kod adları ("ocr_unavailable") arayüzde
# hiçbir şey ifade etmiyordu; belgenin neden beklediğini anlatan tek yer burası.
_REASON_TEXT = {
    OCR_UNAVAILABLE: "Taranmış bir sayfa okunamadı (OCR kullanılamadı) — belgenin bir "
                     "bölümü hiç çıkarılmamış olabilir.",
    WORKBOOK_TRUNCATED: "Çalışma kitabı hücre sınırını aştı — tablonun tamamı okunmadı.",
    IMAGE_TEXT_UNREAD: "Bir sayfanın büyük bölümü görüntü, ama sayfada yeterli metin "
                       "olduğu için OCR çalışmadı — görüntü içindeki yazı okunmamış olabilir.",
}


def _reasons(warnings: list[str], has_text: bool) -> list[str]:
    out = [t for w, t in _REASON_TEXT.items() if any(x.startswith(w) for x in warnings)]
    if not has_text:
        out.append("Belgeden hiç metin çıkarılamadı (büyük olasılıkla tamamı görüntü).")
    return out


def ingest(data: bytes, filename: str, settings: Settings) -> tuple[Document, ExtractedContent]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    kind, content = extract(data, filename, max_bytes)  # UploadRejected / ExtractionFailed
    doc = Document(id=uuid.uuid4().hex, filename=filename, kind=kind)

    has_text = bool(content.plain_text.strip())
    blocking = [w for w in content.warnings if w.startswith(_BLOCKING_WARNINGS)]
    if not has_text:
        # Parsed, but no usable text (likely scanned/image-only).
        content.warnings.append("no extractable text (possibly scanned/image-only)")
    if not has_text or blocking:
        # Absent or only-partial capture must be a human decision, not an auto-approval.
        doc.language = detect_content_language(content) if has_text else Language.unknown
        doc.review_reason = _reasons(content.warnings, has_text)
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        return doc, content

    doc.transition(DocumentStatus.EXTRACTED)
    doc.language = detect_content_language(content)
    return doc, content
