"""Approve, reject and delete — the final review actions, each under the document's lock.

Approval is fail-closed. A document in review with masked content and no open item is approved
only when a SUCCESSFUL LLM audit covers its current revision (`audited_revision`) AND read exactly
the masked text stored now (`audited_digest`). Otherwise that content is audited first:

  no working LLM                    503 ollama_unreachable, nothing approved
  a residual the audit locates      409 unresolved_items (a finding to decide)
  not clean, nothing left open      409 audit_not_clean: the reasons are now on the document, and
                                    the reviewer's second click approves what they have seen

The audit replaces the findings, so the revision moves on (a stale client is refused). Layer 5
(chat context) is built from the SAME content object that was audited, never re-read after it.
"""
from __future__ import annotations

from app.anonymization.engine import Engine
from app.config import Settings
from app.extraction.base import Block, ExtractedContent
from app.models.document import Document, DocumentStatus, FileKind
from app.models.findings import AuditResult, RiskLevel
from app.pipeline import runner
from app.pipeline.terms import effective_terms
from app.review import audit_terms
from app.review.errors import DecisionError, not_found
from app.review.findings import record_findings
from app.review.payload import load_edits
from app.review.reasons import REVIEW_REASONS
from app.review.store import document_deny_terms, kept_findings, load_document
from app.security.logging import redact
from app.services.locks import LockTimeout, document_lock
from app.services.repository import DocumentRepository
from app.services.user_settings import mask_families

DELETE_WAIT_S = 2.0  # a document locked longer than this is being processed: document_busy
_REJECT_CHARS = 200
_AUDIT_CODES = ("audit_residual", "audit_unlocated", "auditor_unavailable")


def approve(doc_id: str, repo: DocumentRepository, settings: Settings,
            expected_revision: int | None = None) -> Document:
    with document_lock(doc_id):
        doc = load_document(repo, doc_id)
        if doc.status != DocumentStatus.NEEDS_HUMAN_REVIEW:
            raise DecisionError("not_in_review")
        if expected_revision is not None and expected_revision != doc.revision:
            raise DecisionError("stale_revision")
        content = repo.get_anonymized(doc.id)
        if content is None:
            raise DecisionError("no_content")
        if doc.pending_count > 0:
            raise DecisionError("unresolved_items")
        audited = (doc.audited_revision == doc.revision
                   and doc.audited_digest == runner.audit_digest(content))
        if not audited:
            _reaudit(doc, repo, settings, content)
        doc.drop_reasons("changed_after_approval")
        doc.transition(DocumentStatus.APPROVED)
        runner.build_chat_context(repo, doc.id, content)
        repo.save_document(doc)
        return doc


def _reaudit(doc: Document, repo: DocumentRepository, settings: Settings,
             content: ExtractedContent) -> None:
    """LLM-audit the current masked content; raise unless it is clean. Only a successful LLM
    audit counts (it alone sets audited_revision)."""
    audit = runner.build_auditor(settings).audit(content.plain_text)
    if audit.llm_ok is not True:
        doc.add_reason("auditor_unavailable", REVIEW_REASONS["auditor_unavailable"])
        repo.save_document(doc)
        raise DecisionError("ollama_unreachable", 503)
    clean = audit.is_clean_approval(RiskLevel(settings.auditor_risk_approve))
    doc.revision += 1  # the findings (item ids) are replaced next: refuse stale clients first
    repo.save_document(doc)
    doc.drop_reasons(*_AUDIT_CODES)
    _record_reaudit(doc, repo, content, audit, clean)
    # Marked audited only once its findings are stored: a crash in between re-audits next time.
    doc.audited_revision = doc.revision
    doc.audited_digest = runner.audit_digest(content)
    if not clean:
        repo.save_document(doc)
        raise DecisionError("unresolved_items" if doc.pending_count else "audit_not_clean")


def _record_reaudit(doc: Document, repo: DocumentRepository, content: ExtractedContent,
                    audit: AuditResult, clean: bool) -> None:
    terms = [] if clean else audit.raw_terms
    mapping = doc.mode == "mapping"
    kept = kept_findings(repo.get_decisions(doc.id) if mapping else {})
    unlocated = record_findings(doc, repo, content, load_edits(repo, doc.id), terms, kept,
                                residual=not clean)
    if mapping:
        previous = repo.get_audit_terms(doc.id)
        repo.save_audit_terms(doc.id, audit_terms.after_reaudit(previous, terms, unlocated))


def reject(doc_id: str, repo: DocumentRepository, settings: Settings,
           reason: str | None) -> Document:
    with document_lock(doc_id):
        doc = load_document(repo, doc_id)
        if doc.status.processing or doc.status == DocumentStatus.REJECTED:
            raise DecisionError("not_in_review")
        doc.reject_reason = safe_reject_reason(reason, doc, repo, settings)
        doc.transition(DocumentStatus.REJECTED)
        repo.save_document(doc)
        return doc


def safe_reject_reason(reason: str | None, doc: Document, repo: DocumentRepository,
                       settings: Settings) -> str:
    """The reviewer's free text without raw personal values: masked by the engine (names, IDs,
    every deny term of this document), then `redact()` as a pattern backstop, capped."""
    text = " ".join((reason or "").split())[:_REJECT_CHARS * 4]
    if not text:
        return ""
    deny, allow = effective_terms(settings)
    content = ExtractedContent(kind=FileKind.docx, blocks=[Block(block_id="reason", text=text)])
    masked = Engine().anonymize(content, doc.language, extra_allow_terms=allow,
                                extra_deny_terms=deny + document_deny_terms(repo, doc),
                                deny_families=mask_families(settings)).content.plain_text
    return redact(masked)[:_REJECT_CHARS]


def delete_document(doc_id: str, repo: DocumentRepository) -> None:
    """Delete every layer. Refused (document_busy) while the worker extracts, masks or audits it,
    or while another action holds it longer than DELETE_WAIT_S."""
    try:
        with document_lock(doc_id, timeout=DELETE_WAIT_S):
            doc = repo.get_document(doc_id)
            if doc is None:
                raise not_found()
            if doc.status.busy:
                raise DecisionError("document_busy")
            repo.delete(doc_id, secure=True)
    except LockTimeout as e:
        raise DecisionError("document_busy") from e
