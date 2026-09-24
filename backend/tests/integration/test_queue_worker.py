"""Background worker: processes queued documents in order and recovers interrupted ones."""
from __future__ import annotations

import time

from app.config import get_settings
from app.extraction.base import validate_upload
from app.models.document import DocumentStatus
from app.pipeline.queue import Job, Worker
from app.services.deps import get_repository
from app.services.ingest import new_document
from tests.conftest import EN_PARA, make_docx


def _queued(mode: str = "mapping"):
    data = make_docx([EN_PARA])
    repo = get_repository()
    doc = new_document("a.docx", validate_upload(data, "a.docx", 10**7), mode)
    repo.save_document(doc)
    if mode == "mapping":
        repo.save_original(doc.id, data, "a.docx")
    return doc, data, repo


def _wait(repo, doc_id: str, timeout: float = 60.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        doc = repo.get_document(doc_id)
        if doc and not doc.status.processing:
            return doc
        time.sleep(0.1)
    raise AssertionError("worker did not finish in time")


def test_worker_processes_a_job() -> None:
    doc, data, repo = _queued("destructive")
    worker = Worker(get_settings, get_repository)
    worker.start()
    try:
        worker.submit(Job(doc.id, data))
        done = _wait(repo, doc.id)
    finally:
        worker.stop()
    assert done.status in (DocumentStatus.APPROVED, DocumentStatus.NEEDS_HUMAN_REVIEW)
    assert repo.get_original(doc.id) is None  # destructive bytes never reached disk


def test_recover_requeues_mapping_and_fails_destructive() -> None:
    kept, _data, repo = _queued("mapping")
    lost, _d, _r = _queued("destructive")
    for d in (kept, lost):
        d.transition(DocumentStatus.MASKING)  # as if the app stopped mid-run
        repo.save_document(d)
    worker = Worker(get_settings, get_repository)
    assert worker.recover() == 1
    failed = repo.get_document(lost.id)
    assert failed.status == DocumentStatus.FAILED
    assert any(r.code == "processing_interrupted" for r in failed.reasons)
    worker.start()
    try:
        done = _wait(repo, kept.id)
    finally:
        worker.stop()
    assert done.status in (DocumentStatus.APPROVED, DocumentStatus.NEEDS_HUMAN_REVIEW)
