"""Ingest service: validate → extract → detect language. The single function the API calls.

Codex Phase-2 review (H2): empty extraction (scanned/image-only PDFs, etc.) is NOT a success —
it routes to human review. Corrupt files raise `ExtractionFailed` from the dispatcher and
propagate to the API as 422. Persistence to storage layers is wired in Phase 5.
"""
from __future__ import annotations

import uuid

from app.config import Settings
from app.extraction.base import ExtractedContent
from app.extraction.dispatcher import extract
from app.language.detector import detect_content_language
from app.models.document import Document, DocumentStatus, Language


def ingest(data: bytes, filename: str, settings: Settings) -> tuple[Document, ExtractedContent]:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    kind, content = extract(data, filename, max_bytes)  # UploadRejected / ExtractionFailed
    doc = Document(id=uuid.uuid4().hex, filename=filename, kind=kind)

    if not content.plain_text.strip():
        # Parsed, but no usable text (likely scanned/image-only). Fail closed to human review.
        content.warnings.append("no extractable text (possibly scanned/image-only)")
        doc.language = Language.unknown
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        return doc, content

    doc.transition(DocumentStatus.EXTRACTED)
    doc.language = detect_content_language(content)
    return doc, content
