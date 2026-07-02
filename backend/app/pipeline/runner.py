"""Pipeline runner: ingest → anonymize/audit loop → persist. Used by the upload API.

Chat context (layer 5) is built ONLY on approval, from anonymized content only.
"""
from __future__ import annotations

from app.anonymization.presidio_engine import PresidioEngine
from app.audit.factory import build_auditor
from app.config import Settings
from app.models.document import Document, DocumentStatus
from app.pipeline.orchestrator import Orchestrator
from app.services.ingest import ingest
from app.services.repository import DocumentRepository


def build_chat_context(repo: DocumentRepository, doc_id: str) -> bool:
    """Create the layer-5 chat context from anonymized content. Returns True on success."""
    anon = repo.get_anonymized(doc_id)
    if anon is None:
        return False
    repo.save_chat_context(doc_id, anon.plain_text)
    return True


def run_pipeline(
    data: bytes, filename: str, settings: Settings, repo: DocumentRepository,
    deny_terms: list[str] | None = None,
) -> Document:
    doc, content = ingest(data, filename, settings)  # UploadRejected / ExtractionFailed propagate
    repo.save_document(doc)
    repo.save_original(doc.id, data, filename)  # layer 1 (local-only)
    repo.save_extracted(doc.id, content)

    # Empty/scanned with no usable text → nothing to anonymize; leave it for a human.
    flagged_for_review = doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    if flagged_for_review and not content.plain_text.strip():
        return doc

    # Otherwise anonymize + persist layer 3 EVEN when ingest flagged the doc for review
    # (partial extraction: OCR-unavailable / truncated workbook). This guarantees an approved
    # review still has a downloadable artifact and chat context, instead of a 404.
    effective_deny = settings.deny_list() + list(deny_terms or [])
    try:
        result = Orchestrator(PresidioEngine(), build_auditor(settings), settings).run(
            doc, content, doc.language, initial_deny_terms=effective_deny
        )
    except Exception:  # noqa: BLE001 — any pipeline failure fails closed to human review
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        repo.save_document(doc)
        return doc
    if result.anonymized is not None:
        repo.save_anonymized(doc.id, result.anonymized)
        repo.save_mapping(doc.id, result.mapping)
    if flagged_for_review:
        # A partial extraction stays in human review regardless of the audit verdict (fail-closed);
        # the reviewer approves via the API, which then builds the chat context.
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    elif result.approved:
        build_chat_context(repo, doc.id)
    repo.save_document(doc)
    return doc
