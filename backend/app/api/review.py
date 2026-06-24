"""Human-review API — pending queue + approve / reject / manual redaction.

Codex review: approval re-audits the current anonymized artifact (recorded as an iteration) before
building the layer-5 chat context; manual redaction invalidates any existing chat context and
de-approves until a clean re-approval.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.anonymization.presidio_engine import PresidioEngine
from app.audit.factory import build_auditor
from app.config import get_settings
from app.models.document import DocumentStatus, IterationRecord
from app.pipeline.runner import build_chat_context
from app.services.deps import get_repository

router = APIRouter(prefix="/api/review", tags=["review"])


class RedactionRequest(BaseModel):
    terms: list[str]


@router.get("/pending")
def pending() -> dict:
    repo = get_repository()
    return {
        "documents": [
            {"id": d.id, "filename": d.filename, "language": d.language.value,
             "status": d.status.value, "iterations": len(d.iterations)}
            for d in repo.list_documents()
            if d.status == DocumentStatus.NEEDS_HUMAN_REVIEW
        ]
    }


@router.post("/{doc_id}/approve")
def approve(doc_id: str) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    anon = repo.get_anonymized(doc_id)
    audit = None
    if anon is not None:  # re-audit the artifact being approved (transparency trail)
        audit = build_auditor(get_settings()).audit(anon.plain_text)
        doc.iterations.append(IterationRecord(iteration=len(doc.iterations) + 1, audit=audit))
    doc.transition(DocumentStatus.APPROVED)
    build_chat_context(repo, doc_id)  # anonymized → layer 5 only
    repo.save_document(doc)
    return {
        "id": doc.id, "status": doc.status.value, "chat_enabled": doc.chat_enabled,
        "reaudit_clean": (audit.approved if audit else None),
    }


@router.post("/{doc_id}/reject")
def reject(doc_id: str) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)
    return {"id": doc.id, "status": doc.status.value}


@router.post("/{doc_id}/redact")
def redact(doc_id: str, body: RedactionRequest) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    extracted = repo.get_extracted(doc_id)
    if doc is None or extracted is None:
        raise HTTPException(status_code=404, detail="document or content not found")
    out = PresidioEngine().anonymize(extracted, doc.language, extra_deny_terms=body.terms)
    repo.save_anonymized(doc_id, out.content)
    repo.save_mapping(doc_id, out.mapping)
    # Invalidate any prior chat context and require a fresh approval before chat resumes.
    repo.save_chat_context(doc_id, "")
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)
    return {"id": doc.id, "status": doc.status.value, "applied_terms": len(body.terms)}
