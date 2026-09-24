"""Document processing: extract → mask/audit loop → persist → route.

`process_job` is what the queue worker runs for an uploaded document. `run_pipeline` is the same
flow, synchronous, for the evaluation harness and tests (it raises UploadRejected /
ExtractionFailed like before v2).

Storage modes (`Document.mode`): "mapping" persists the original (layer 1), the extracted text and
the placeholder mapping (layer 2); "destructive" never writes layers 1-2. Both persist the masked
content and edit POSITIONS (layer 3) and PII-safe reports (layer 4). Chat context (layer 5) is built
only for an approved document.
"""
from __future__ import annotations

import logging

from app.anonymization.engine import (
    AnonymizationOutput,
    Engine,
    Overrides,
    iter_units,
)
from app.audit.factory import build_auditor
from app.config import Settings
from app.extraction.base import ExtractionFailed, UploadRejected
from app.models.document import Document, DocumentStatus
from app.pipeline.orchestrator import Orchestrator, PipelineResult
from app.pipeline.terms import effective_terms
from app.review.findings import locate
from app.review.reasons import REVIEW_REASONS
from app.services.ingest import ExtractResult, extract_content, new_document
from app.services.repository import DocumentRepository

logger = logging.getLogger(__name__)


def build_chat_context(repo: DocumentRepository, doc_id: str) -> bool:
    """Create the layer-5 chat context from anonymized content. Returns True on success."""
    anon = repo.get_anonymized(doc_id)
    if anon is None:
        return False
    repo.save_chat_context(doc_id, anon.plain_text)
    return True


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
    """Queue worker entry: never raises; a failure leaves the document FAILED with a reason."""
    doc = repo.get_document(doc_id)
    if doc is None:
        return
    if data is None:
        data = repo.get_original(doc_id)
    if data is None:
        _fail(doc, repo, "processing_interrupted")
        return
    try:
        doc.transition(DocumentStatus.EXTRACTED)  # shown as "extracting"
        repo.save_document(doc)
        extracted = extract_content(data, doc.filename, settings)
        mask_and_route(doc, extracted, data, settings, repo)
    except (UploadRejected, ExtractionFailed):
        _fail(doc, repo, "processing_failed")
    except Exception as e:  # noqa: BLE001 — log the type only, never content
        logger.error("processing failed for %s: %s", doc_id, type(e).__name__)
        _fail(doc, repo, "processing_failed")


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
                              initial_allow_terms=allow, overrides=overrides)
    persist_output(doc, repo, result.output, destructive=destructive)
    record_audit(doc, repo, result)
    route(doc, repo, audit_clean=result.approved, blocking=bool(extracted.reasons))
    return doc


def persist_output(doc: Document, repo: DocumentRepository, output: AnonymizationOutput | None,
                   *, destructive: bool) -> None:
    if output is None:
        return
    repo.save_anonymized(doc.id, output.content)
    if not destructive:
        repo.save_mapping(doc.id, output.mapping)
    repo.save_edits(doc.id, {uid: [e.model_dump() for e in edits]
                             for uid, edits in output.edits.items()})
    doc.masked_count = sum(1 for edits in output.edits.values() for e in edits if e.text)
    doc.revision += 1


def record_audit(doc: Document, repo: DocumentRepository, result: PipelineResult,
                 kept_values: list[str] | None = None) -> None:
    """Store residual positions (never values) and the audit's reasons."""
    output, audit = result.output, result.audit
    doc.audited_revision = doc.revision
    if output is None or audit is None or result.approved:
        repo.save_findings(doc.id, [])
        doc.pending_count = 0
        return
    units = [(uid, text) for uid, _b, _c, text in iter_units(output.content)]
    findings, unlocated = locate(units, audit.raw_terms, kept_values or [])
    repo.save_findings(doc.id, findings)
    doc.pending_count = sum(1 for f in findings if f["status"] == "open")
    doc.add_reason("audit_residual", REVIEW_REASONS["audit_residual"])
    # llm_ok=False covers a call that failed mid-run too, not only an LLM missing at build time
    # (the combined auditor's summary has no "Fail-closed" prefix in that case).
    if result.llm_ok is False or audit.summary.startswith("Fail-closed"):
        doc.add_reason("auditor_unavailable", REVIEW_REASONS["auditor_unavailable"])
    if unlocated:
        doc.add_reason("audit_unlocated",
                       f"Denetim {len(unlocated)} olası kalıntı bildirdi ama metinde yerini "
                       "gösteremedi; lütfen metni gözden geçirin.")


def route(doc: Document, repo: DocumentRepository, *, audit_clean: bool, blocking: bool) -> None:
    """The single routing rule: APPROVED only when the audit is clean, nothing is pending and no
    blocking extraction warning exists. Everything else waits for a human."""
    if audit_clean and not blocking and doc.pending_count == 0:
        doc.transition(DocumentStatus.APPROVED)
        build_chat_context(repo, doc.id)
    else:
        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)


def _fail(doc: Document, repo: DocumentRepository, code: str) -> Document:
    doc.add_reason(code, REVIEW_REASONS[code])
    doc.transition(DocumentStatus.FAILED)
    repo.save_document(doc)
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
