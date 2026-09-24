"""Documents and review API (frontend/src/api/contract.ts).

Responses are PII-safe except the review payload, which returns original text in mapping mode for
the reviewer's side-by-side view. The placeholder mapping never leaves the service. Errors are
{"detail": <ErrorCode>}.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from app.config import get_settings
from app.extraction.base import UploadRejected, validate_upload
from app.models.document import Document, DocumentStatus
from app.pipeline.queue import Job
from app.pipeline.runner import process_job
from app.review import decisions as D
from app.review.pages import PageNotFound, page_marks, render_page
from app.review.payload import ReviewUnavailable, build_review, document_summary
from app.services.deps import get_repository, get_worker
from app.services.ingest import new_document
from app.services.user_settings import load_user_settings

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
    settings = get_settings()
    repo = get_repository()
    if mode is not None and mode not in ("mapping", "destructive"):
        raise _fail("invalid_file", 400)
    max_bytes = settings.max_upload_mb * 1024 * 1024
    try:
        data = await file.read(max_bytes + 1)
    finally:
        await file.close()
    filename = file.filename or "belge"
    try:
        kind = validate_upload(data, filename, max_bytes)
    except UploadRejected as e:
        code, status = _REJECT.get(e.code, ("invalid_file", 400))
        raise _fail(code, status) from e
    doc = new_document(filename, kind, mode or load_user_settings(settings).default_mode)
    repo.save_document(doc)
    if doc.mode == "mapping":
        repo.save_original(doc.id, data, filename)  # layer 1; destructive bytes stay in memory
    if settings.process_inline:
        await run_in_threadpool(process_job, doc.id, data, settings, repo)
    else:
        get_worker().submit(Job(doc.id, None if doc.mode == "mapping" else data))
    return document_summary(repo.get_document(doc.id) or doc)


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict:
    return document_summary(_doc(doc_id))


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str) -> Response:
    doc = _doc(doc_id)
    if doc.status.processing:
        raise _fail("not_in_review", 409)
    get_repository().delete(doc.id, secure=True)
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
    doc = _doc(doc_id)
    if doc.status != DocumentStatus.APPROVED:
        raise _fail("not_approved", 403)
    anon = get_repository().get_anonymized(doc.id)
    if anon is None:
        raise _fail("document_not_found", 404)
    from app.export.filename import anonymize_filename
    from app.export.render_pdf import render_content_pdf

    safe = anonymize_filename(doc.filename, doc.language, deny_terms=get_settings().deny_list())
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
    try:
        return page_marks(_original_pdf(doc), index, payload)
    except PageNotFound as e:
        raise _fail("page_not_found", 404) from e


class DecisionBody(BaseModel):
    op: str
    target: dict
    scope: str = "occurrence"


@router.post("/{doc_id}/decisions")
def decide(doc_id: str, body: DecisionBody) -> dict:
    doc = _doc(doc_id)
    try:
        D.apply_decision(doc, get_repository(), get_settings(), body.op, body.target, body.scope)
    except D.DecisionError as e:
        raise _fail(e.code, e.status) from e
    return _review_payload(doc)


@router.post("/{doc_id}/approve")
def approve(doc_id: str) -> dict:
    doc = _doc(doc_id)
    try:
        D.approve(doc, get_repository(), get_settings())
    except D.DecisionError as e:
        raise _fail(e.code, e.status) from e
    return document_summary(doc)


class RejectBody(BaseModel):
    reason: str | None = None


@router.post("/{doc_id}/reject")
def reject(doc_id: str, body: RejectBody | None = None) -> dict:
    doc = _doc(doc_id)
    try:
        D.reject(doc, get_repository(), body.reason if body else None)
    except D.DecisionError as e:
        raise _fail(e.code, e.status) from e
    return document_summary(doc)
