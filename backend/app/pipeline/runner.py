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


def run_pipeline(data: bytes, filename: str, settings: Settings, repo: DocumentRepository) -> Document:
    doc, content = ingest(data, filename, settings)  # UploadRejected / ExtractionFailed propagate
    repo.save_document(doc)
    repo.save_original(doc.id, data, filename)  # layer 1 (local-only)
    repo.save_extracted(doc.id, content)

    if doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW:  # empty/scanned — nothing to anonymize
        return doc

    try:
        result = Orchestrator(PresidioEngine(), build_auditor(settings), settings).run(
            doc, content, doc.language
        )
    except Exception:  # noqa: BLE001 — any pipeline failure fails closed to human review
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        repo.save_document(doc)
        return doc
    if result.anonymized is not None:
        repo.save_anonymized(doc.id, result.anonymized)
        repo.save_mapping(doc.id, result.mapping)
        if result.approved:
            build_chat_context(repo, doc.id)
    repo.save_document(doc)
    return doc
