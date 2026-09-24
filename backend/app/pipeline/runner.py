"""Document processing: extract → mask/audit loop → persist → route.

`process_job` is what the queue worker runs for an uploaded document. `run_pipeline` is the same
flow, synchronous, for the evaluation harness and tests (it raises UploadRejected /
ExtractionFailed like before v2).

Storage modes (`Document.mode`): "mapping" persists the original (layer 1), the extracted text, the
placeholder mapping and the auditor's residual terms (layer 2); "destructive" never writes layers
1-2. Both persist the masked content and edit POSITIONS (layer 3) and PII-safe reports (layer 4).
Chat context (layer 5) is built only for an approved document.

Routing is fail-closed: only a SUCCESSFUL LLM audit (llm_ok True) that is clean, with nothing
pending and no blocking extraction reason, approves. The deterministic heuristic alone never
approves anything.
"""
from __future__ import annotations

import hashlib
import logging

from app.anonymization.engine import AnonymizationOutput, Engine, Overrides
from app.audit.factory import build_auditor
from app.config import Settings
from app.extraction.base import ExtractedContent, ExtractionFailed, UploadRejected
from app.models.document import Document, DocumentStatus
from app.pipeline.orchestrator import Orchestrator, PipelineResult
from app.pipeline.terms import effective_terms
from app.review import audit_terms
from app.review.findings import record_findings
from app.review.reasons import REVIEW_REASONS
from app.services.ingest import ExtractResult, extract_content, new_document
from app.services.locks import document_lock
from app.services.repository import DocumentRepository
from app.services.user_settings import mask_families
from app.services.user_settings import readable as user_settings_readable

__all__ = ["audit_digest", "build_auditor", "build_chat_context", "mask_and_route",
           "note_settings", "persist_output", "process_job", "record_audit", "route",
           "run_pipeline", "write_output"]

logger = logging.getLogger(__name__)


def build_chat_context(repo: DocumentRepository, doc_id: str, content: ExtractedContent) -> None:
    """Layer 5 from exactly the masked content that was audited (never re-read afterwards)."""
    repo.save_chat_context(doc_id, content.plain_text)


def run_pipeline(data: bytes, filename: str, settings: Settings, repo: DocumentRepository,
                 deny_terms: list[str] | None = None, mode: str | None = None) -> Document:
    extracted = extract_content(data, filename, settings)  # rejections propagate (pre-v2 contract)
    doc = new_document(filename, extracted.kind, mode or settings.anonymization_mode)
    repo.save_document(doc)
    if doc.mode != "destructive":
        repo.save_original(doc.id, data, filename)
    try:
        return mask_and_route(doc, extracted, data, settings, repo, extra_deny=deny_terms)
    except Exception:  # noqa: BLE001 — any failure fails closed; never an approval
        return _fail(doc, repo, "processing_failed")


def process_job(doc_id: str, data: bytes | None, settings: Settings,
                repo: DocumentRepository) -> None:
    """Queue worker entry: never raises; a failure leaves the document FAILED with a reason.

    The whole run holds the document's lock, and the document is read inside it: a document
    deleted meanwhile is skipped (nothing is written, so no folder comes back), and one that is no
    longer queued — a double submit, an approved document — is not processed again."""
    with document_lock(doc_id):
        try:
            doc = repo.get_document(doc_id)
        except Exception as e:  # noqa: BLE001 — an unreadable document cannot be marked FAILED
            logger.error("unreadable document %s: %s", doc_id, type(e).__name__)
            return
        if doc is None or not doc.status.processing:
            return
        try:
            _process(doc, data, settings, repo)
        except (UploadRejected, ExtractionFailed):
            _fail(doc, repo, "processing_failed")
        except Exception as e:  # noqa: BLE001 — log the type only, never content
            logger.error("processing failed for %s: %s", doc_id, type(e).__name__)
            _fail(doc, repo, "processing_failed")


def _process(doc: Document, data: bytes | None, settings: Settings,
             repo: DocumentRepository) -> None:
    if data is None:
        data = repo.get_original(doc.id)
    if data is None:
        _fail(doc, repo, "processing_interrupted")
        return
    doc.transition(DocumentStatus.EXTRACTED)  # shown as "extracting"
    repo.save_document(doc)
    extracted = extract_content(data, doc.filename, settings)
    mask_and_route(doc, extracted, data, settings, repo)


def mask_and_route(doc: Document, extracted: ExtractResult, data: bytes, settings: Settings,
                   repo: DocumentRepository, *, extra_deny: list[str] | None = None,
                   overrides: Overrides | None = None) -> Document:
    destructive = doc.mode == "destructive"
    doc.language = extracted.language
    doc.page_count = _page_count(doc, data)
    for code, text in extracted.reasons:
        doc.add_reason(code, text)
    if not destructive:
        repo.save_extracted(doc.id, extracted.content)
    if not extracted.has_text:
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        repo.save_document(doc)
        return doc

    deny, allow = effective_terms(settings)
    orchestrator = Orchestrator(Engine(), build_auditor(settings), settings,
                                on_status=repo.save_document)
    result = orchestrator.run(doc, extracted.content, extracted.language,
                              initial_deny_terms=deny + list(extra_deny or []),
                              initial_allow_terms=allow, overrides=overrides,
                              deny_families=mask_families(settings))
    persist_output(doc, repo, result.output, destructive=destructive)
    unlocated = record_audit(doc, repo, result)
    if not destructive:
        final = [] if result.approved or result.audit is None else result.audit.raw_terms
        repo.save_audit_terms(doc.id, audit_terms.after_pipeline(result.repair_terms, final,
                                                                 unlocated))
    unread = note_settings(doc, settings)
    route(doc, repo, result, blocking=bool(extracted.reasons) or unread)
    return doc


def note_settings(doc: Document, settings: Settings) -> bool:
    """Whether the user's term lists could NOT be read (then the always-mask list was not
    applied): a blocking reason, so such a document is never approved without a human."""
    if user_settings_readable(settings):
        doc.drop_reasons("settings_unreadable")
        return False
    doc.add_reason("settings_unreadable", REVIEW_REASONS["settings_unreadable"])
    return True


def audit_digest(content: ExtractedContent) -> str:
    """Fingerprint of the masked text an LLM audit covered (Document.audited_digest)."""
    return hashlib.sha256(content.plain_text.encode("utf-8")).hexdigest()


def persist_output(doc: Document, repo: DocumentRepository, output: AnonymizationOutput | None,
                   *, destructive: bool) -> None:
    """A new revision of the masked content: bump the revision, then write it."""
    if output is None:
        return
    doc.revision += 1
    write_output(doc, repo, output, destructive=destructive)


def write_output(doc: Document, repo: DocumentRepository, output: AnonymizationOutput, *,
                 destructive: bool) -> None:
    """Layer 3 (masked content, edit positions) and, in mapping mode, the layer-2 mapping."""
    repo.save_anonymized(doc.id, output.content)
    if not destructive:
        repo.save_mapping(doc.id, output.mapping)
    repo.save_edits(doc.id, {uid: [e.model_dump() for e in edits]
                             for uid, edits in output.edits.items()})
    doc.masked_count = sum(1 for edits in output.edits.values() for e in edits if e.text)


def record_audit(doc: Document, repo: DocumentRepository, result: PipelineResult) -> list[str]:
    """Store the final audit's residual positions (never values) and reasons; returns the terms it
    could not locate. Only a SUCCESSFUL LLM audit marks the revision (and text) as audited."""
    output, audit = result.output, result.audit
    if result.llm_ok is True and output is not None:
        doc.audited_revision = doc.revision
        doc.audited_digest = audit_digest(output.content)
    if output is None or audit is None or result.approved:
        repo.save_findings(doc.id, [])
        doc.pending_count = 0
        return []
    return record_findings(doc, repo, output.content, output.edits, audit.raw_terms, None,
                           residual=True)


def route(doc: Document, repo: DocumentRepository, result: PipelineResult, *,
          blocking: bool) -> None:
    """The single routing rule: APPROVED only when a working LLM audited it (llm_ok True), the
    audit is clean, nothing is pending and no blocking extraction warning exists. Everything else
    waits for a human, with `auditor_unavailable` whenever the LLM did not deliver."""
    if result.llm_ok is not True:
        doc.add_reason("auditor_unavailable", REVIEW_REASONS["auditor_unavailable"])
    if (result.llm_ok is True and result.approved and not blocking and doc.pending_count == 0
            and result.output is not None):
        doc.transition(DocumentStatus.APPROVED)
        build_chat_context(repo, doc.id, result.output.content)
    else:
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)


def _fail(doc: Document, repo: DocumentRepository, code: str) -> Document:
    doc.add_reason(code, REVIEW_REASONS[code])
    doc.transition(DocumentStatus.FAILED)
    try:
        repo.save_document(doc)
    except OSError as e:  # the worker must not die; the document stays as last stored
        logger.error("could not store FAILED for %s: %s", doc.id, type(e).__name__)
    return doc


def _page_count(doc: Document, data: bytes) -> int | None:
    if doc.kind.value != "pdf":
        return None
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as pdf:
            return pdf.page_count
    except Exception:  # noqa: BLE001 — a count is cosmetic; extraction already validated the file
        return None
