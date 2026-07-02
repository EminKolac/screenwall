"""Documents API — upload runs the full pipeline; plus list/detail/anonymized-download/findings.

Responses are PII-safe: never the original, extracted text, or the placeholder mapping. Only
anonymized content (layer 3) and redacted metadata/reports leave the service.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, Response

from app.config import get_settings
from app.extraction.base import ExtractionFailed, UploadRejected
from app.models.document import Document
from app.pipeline.runner import run_pipeline
from app.services.deps import get_repository
from app.services.repository import DocumentRepository

router = APIRouter(prefix="/api/documents", tags=["documents"])
_REJECT_STATUS = {"too_large": 413, "unsupported": 415, "invalid": 400}


def _summary(doc: Document, repo: DocumentRepository) -> dict:
    last = doc.iterations[-1].audit if doc.iterations else None
    return {
        "id": doc.id,
        "filename": doc.filename,
        "kind": doc.kind.value,
        "language": doc.language.value,
        "status": doc.status.value,
        "status_label": doc.status.display,
        "iterations": len(doc.iterations),
        "approved": doc.approved,
        "chat_enabled": doc.chat_enabled,
        "risk_level": last.risk_level.value if last else None,
        "has_anonymized": repo.get_anonymized(doc.id) is not None,
    }


async def _read_bounded(file: UploadFile, max_bytes: int) -> bytes | None:
    data = await file.read(max_bytes + 1)
    return None if len(data) > max_bytes else data


@router.post("")
async def upload_document(file: UploadFile = File(...)) -> dict:  # noqa: B008 — FastAPI DI idiom
    settings = get_settings()
    repo = get_repository()
    data = await _read_bounded(file, settings.max_upload_mb * 1024 * 1024)
    if data is None:
        raise HTTPException(status_code=413, detail="file too large")
    try:
        # Heavy CPU/IO pipeline runs in a threadpool so it never blocks the event loop.
        doc = await run_in_threadpool(run_pipeline, data, file.filename or "upload", settings, repo)
    except UploadRejected as e:
        raise HTTPException(status_code=_REJECT_STATUS.get(e.code, 400), detail=str(e)) from e
    except ExtractionFailed as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return _summary(doc, repo)


@router.get("")
def list_documents() -> dict:
    repo = get_repository()
    return {"documents": [_summary(d, repo) for d in repo.list_documents()]}


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    data = doc.model_dump(mode="json")  # iterations + audit; mapping/raw_terms excluded
    data["chat_ready"] = doc.approved and repo.get_chat_context(doc_id) is not None
    return data


@router.get("/{doc_id}/anonymized", response_class=PlainTextResponse)
def download_anonymized(doc_id: str) -> str:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    # Privacy-first: unapproved best-effort output may still contain residual PII flagged for
    # human review, so it is not downloadable until the document is approved.
    if not doc.approved:
        raise HTTPException(
            status_code=403, detail="anonymized download is available only after approval"
        )
    anon = repo.get_anonymized(doc_id)
    if anon is None:
        raise HTTPException(status_code=404, detail="no anonymized content available")
    return anon.plain_text


def _content_disposition(safe_stem: str) -> str:
    """RFC 5987 attachment header (safe for non-ASCII / Turkish) for the anonymized PDF."""
    name = f"anonymized_{safe_stem}.pdf"
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "anonymized.pdf"
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(name)}"


@router.get("/{doc_id}/download")
def download_anonymized_pdf(doc_id: str) -> Response:
    """Approved anonymized content rendered as a fresh PDF — from storage layer 3 ONLY.

    Never reads the original (layer 1) or the placeholder mapping (layer 2): what is shipped is
    exactly the audited anonymized content, so no un-audited channel of the original (image pixels,
    headers/footers, comments, metadata, formula source, spelling variants) can leak.
    """
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    if not doc.approved:
        raise HTTPException(status_code=403, detail="download is available only after approval")
    anon = repo.get_anonymized(doc_id)
    if anon is None:
        raise HTTPException(status_code=404, detail="no anonymized content available")
    from app.export.filename import anonymize_filename
    from app.export.render_pdf import render_content_pdf

    pdf = render_content_pdf(anon)
    # don't leak PII (or deny-listed names) via the download filename
    safe = anonymize_filename(doc.filename, doc.language, deny_terms=get_settings().deny_list())
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _content_disposition(safe)},
    )


@router.get("/{doc_id}/findings")
def get_findings(doc_id: str) -> dict:
    doc = get_repository().get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {"iterations": [it.model_dump(mode="json") for it in doc.iterations]}


@router.delete("/{doc_id}")
def delete_document(doc_id: str) -> dict:
    repo = get_repository()
    if repo.get_document(doc_id) is None:
        raise HTTPException(status_code=404, detail="document not found")
    repo.delete(doc_id, secure=True)
    return {"deleted": doc_id}
