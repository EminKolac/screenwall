"""Documents and review API (frontend/src/api/contract.ts).

Responses are PII-safe except the review payload, which returns original text in mapping mode for
the reviewer's side-by-side view. The placeholder mapping never leaves the service. Errors are
{"detail": <ErrorCode>}. Every mutating route re-reads the document under its lock
(review/decisions.py, review/approval.py); a client names the revision it saw
(`expected_revision`) and a stale one is refused with 409 stale_revision.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeVar
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.extraction.base import UploadRejected, validate_upload
from app.models.document import Document, DocumentStatus
from app.pipeline.queue import Job
from app.pipeline.runner import process_job
from app.pipeline.terms import effective_terms
from app.review import decisions as D
from app.review.pages import PageNotFound, page_marks, render_page
from app.review.payload import ReviewUnavailable, build_review, document_summary
from app.review.store import document_deny_terms
from app.services.deps import get_repository, get_worker
from app.services.ingest import new_document
from app.services.locks import document_lock
from app.services.user_settings import UserSettingsUnreadable, load_user_settings

T = TypeVar("T")

router = APIRouter(prefix="/api/documents", tags=["documents"])

_DOC_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")  # ids become storage paths: no "../"
_REJECT = {"too_large": ("file_too_large", 413), "unsupported": ("unsupported_file_type", 415),
           "invalid": ("invalid_file", 400)}
_REVIEWABLE = (DocumentStatus.NEEDS_HUMAN_REVIEW, DocumentStatus.APPROVED)


def _fail(code: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail=code)


def _doc(doc_id: str) -> Document:
    if not _DOC_ID.fullmatch(doc_id):
        raise _fail("document_not_found", 404)
    doc = get_repository().get_document(doc_id)
    if doc is None:
        raise _fail("document_not_found", 404)
    return doc


def _act(action: Callable[[], T]) -> T:
    """Run a review action, mapping its errors onto {"detail": <ErrorCode>}."""
    try:
        return action()
    except D.DecisionError as e:
        raise _fail(e.code, e.status) from e
    except UserSettingsUnreadable as e:  # a global decision cannot rewrite a broken file
        raise _fail("internal_error", 500) from e


# ---------------------------------------------------------------- documents

@router.get("")
def list_documents() -> dict:
    docs = sorted(get_repository().list_documents(), key=lambda d: d.created_at, reverse=True)
    return {"documents": [document_summary(d) for d in docs]}


@router.post("", status_code=202)
async def upload_document(
    file: UploadFile = File(...),  # noqa: B008 — FastAPI DI idiom
    mode: str | None = Form(None),  # noqa: B008 — "mapping" | "destructive"; None = user default
) -> dict:
    """Only the async reads run on the event loop. Validation, the destructive-mode name masking
    (it runs the anonymization engine, whose first use loads the analyzer) and the storage writes
    run in the thread pool, so one upload never stalls every other request."""
    settings = get_settings()
    if mode is not None and mode not in ("mapping", "destructive"):
        raise _fail("invalid_file", 400)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        data = await file.read(max_bytes + 1)
    finally:
        await file.close()
    doc = await run_in_threadpool(_accept_upload, data, file.filename or "belge", mode, settings)
    if settings.process_inline:
        await run_in_threadpool(process_job, doc.id, data, settings, get_repository())
    else:
        get_worker().submit(Job(doc.id, None if doc.mode == "mapping" else data))
    return await run_in_threadpool(_current_summary, doc)


def _accept_upload(data: bytes, filename: str, mode: str | None,
                   settings: Settings) -> Document:
    """Validate, create and store a queued document (blocking work: call it off the loop)."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        kind = validate_upload(data, filename, max_bytes)
    except UploadRejected as e:
        code, status = _REJECT.get(e.code, ("invalid_file", 400))
        raise _fail(code, status) from e
    repo = get_repository()
    doc = new_document(filename, kind, mode or load_user_settings(settings).default_mode,
                       settings)
    # Both writes under the lock: a delete racing the upload waits, then removes both layers
    # (without it, the original could land after the delete and stay behind, invisible).
    with document_lock(doc.id):
        repo.save_document(doc)
        if doc.mode == "mapping":
            repo.save_original(doc.id, data, filename)  # layer 1; destructive bytes stay in memory
    return doc


def _current_summary(doc: Document) -> dict:
    return document_summary(get_repository().get_document(doc.id) or doc)


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict:
    return document_summary(_doc(doc_id))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> Response:
    """Allowed when queued (the worker then skips it) or settled; 409 document_busy while the
    worker extracts, masks or audits it."""
    doc = _doc(doc_id)
    _act(lambda: D.delete_document(doc.id, get_repository()))
    return Response(status_code=204)


@router.get("/{doc_id}/masked", response_class=PlainTextResponse)
def masked_text(doc_id: str) -> str:
    doc = _doc(doc_id)
    if doc.status not in _REVIEWABLE:
        raise _fail("not_in_review", 409)
    anon = get_repository().get_anonymized(doc.id)
    if anon is None:
        raise _fail("document_not_found", 404)
    return anon.plain_text


def _content_disposition(safe_stem: str) -> str:
    """RFC 5987 attachment header (safe for non-ASCII / Turkish) for the anonymized PDF."""
    name = f"anonymized_{safe_stem}.pdf"
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "anonymized.pdf"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name)}"


@router.get("/{doc_id}/download")
def download(doc_id: str) -> Response:
    """Approved anonymized content rendered as a fresh PDF — from layer 3 ONLY, so no un-audited
    channel of the original (images, headers, comments, metadata, formulas) can leak."""
    repo = get_repository()
    with document_lock(_doc(doc_id).id):  # status and layer 3 read together: no re-mask between
        doc = repo.get_document(doc_id)
        if doc is None:
            raise _fail("document_not_found", 404)
        if doc.status != DocumentStatus.APPROVED:
            raise _fail("not_approved", 403)
        anon = repo.get_anonymized(doc.id)
        deny = effective_terms(get_settings())[0] + document_deny_terms(repo, doc)
    if anon is None:
        raise _fail("document_not_found", 404)
    from app.export.filename import anonymize_filename
    from app.export.render_pdf import render_content_pdf

    # Every always-mask term applies to the name too: the project and user lists, and every value
    # this document itself hides (its masks, the audit's terms).
    safe = anonymize_filename(doc.filename, doc.language, deny_terms=deny)
    return Response(content=render_content_pdf(anon), media_type="application/pdf",
                    headers={"Content-Disposition": _content_disposition(safe)})


# ---------------------------------------------------------------- review

def _review_payload(doc: Document) -> dict:
    if doc.status not in _REVIEWABLE:
        raise _fail("not_in_review", 409)
    try:
        return build_review(doc, get_repository())
    except ReviewUnavailable as e:
        raise _fail("document_not_found", 404) from e


@router.get("/{doc_id}/review")
def review(doc_id: str) -> dict:
    return _review_payload(_doc(doc_id))


def _original_pdf(doc: Document) -> bytes:
    if doc.kind.value != "pdf" or doc.mode != "mapping":
        raise _fail("original_not_stored", 409)
    data = get_repository().get_original(doc.id)
    if data is None:
        raise _fail("original_not_stored", 409)
    return data


@router.get("/{doc_id}/pages/{index}")
def page_image(doc_id: str, index: int) -> Response:
    doc = _doc(doc_id)
    if doc.status not in _REVIEWABLE:
        raise _fail("not_in_review", 409)
    try:
        png = render_page(_original_pdf(doc), index)
    except PageNotFound as e:
        raise _fail("page_not_found", 404) from e
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{doc_id}/pages/{index}/marks")
def page_marks_route(doc_id: str, index: int) -> dict:
    doc = _doc(doc_id)
    payload = _review_payload(doc)
    extracted = get_repository().get_extracted(doc.id)
    bboxes = {b.block_id: b.bbox for b in extracted.blocks} if extracted else {}
    try:
        return page_marks(_original_pdf(doc), index, payload, bboxes)
    except PageNotFound as e:
        raise _fail("page_not_found", 404) from e


class DecisionBody(BaseModel):
    op: str
    target: object  # validated by review/targets.py: malformed → 422 invalid_decision
    scope: str = "occurrence"
    expected_revision: int | None = None  # the revision the client's span/item ids belong to


@router.post("/{doc_id}/decisions")
def decide(doc_id: str, body: DecisionBody) -> dict:
    doc = _doc(doc_id)
    updated = _act(lambda: D.apply_decision(doc.id, get_repository(), get_settings(), body.op,
                                            body.target, body.scope, body.expected_revision))
    return _review_payload(updated)


class ApproveBody(BaseModel):
    expected_revision: int | None = None


@router.post("/{doc_id}/approve")
def approve(doc_id: str, body: ApproveBody | None = None) -> dict:
    doc = _doc(doc_id)
    expected = body.expected_revision if body else None
    return document_summary(_act(lambda: D.approve(doc.id, get_repository(), get_settings(),
                                                   expected)))


class RejectBody(BaseModel):
    reason: str | None = None


@router.post("/{doc_id}/reject")
def reject(doc_id: str, body: RejectBody | None = None) -> dict:
    doc = _doc(doc_id)
    reason = body.reason if body else None
    return document_summary(_act(lambda: D.reject(doc.id, get_repository(), get_settings(),
                                                  reason)))
