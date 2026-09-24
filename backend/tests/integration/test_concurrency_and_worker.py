"""Document locks, deletion and the worker (review hardening B1, B2, B6).

Every mutating path — a decision, approve, reject, delete and the worker's processing run — holds
the document's lock and re-reads the document inside it. Delete is refused while a document is
being processed, and nothing may recreate the folders of a deleted document.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.pipeline import runner
from app.pipeline.runner import process_job
from app.review import approval
from app.review.decisions import apply_decision
from app.review.errors import DecisionError
from app.services.deps import get_repository
from app.services.locks import document_lock
from app.storage.base import StorageLayer
from tests.conftest import make_docx
from tests.fixtures.llm_auditor import CLEAN, install_llm

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT = ["Rapor Kuzey Grubu tarafından hazırlandı.", "Ayşe Kaya raporu imzaladı."]


def _upload(paragraphs: list[str] = _TEXT) -> dict:
    r = client.post("/api/documents",
                    files={"file": ("rapor.docx", make_docx(paragraphs), _DOCX_MIME)})
    assert r.status_code == 202, r.text
    return r.json()


def _seed(doc_id: str, status: DocumentStatus, original: bytes | None = None) -> None:
    repo = get_repository()
    repo.save_document(Document(id=doc_id, filename="a.docx", kind=FileKind.docx, status=status))
    if original is not None:
        repo.save_original(doc_id, original, "a.docx")


def _folders(doc_id: str) -> list[str]:
    root = get_settings().storage_root
    return [layer.value for layer in StorageLayer if (root / layer.value / doc_id).exists()]


def _selection(doc_id: str) -> dict:
    unit = client.get(f"/api/documents/{doc_id}/review").json()["units"][0]
    start = unit["original"].index("Kuzey Grubu")
    return {"unit_id": unit["id"], "start": start, "end": start + 11, "family": "ORG"}


def _while_locked(doc_id: str, fn, still_waiting) -> list[BaseException]:
    """Run `fn` in another thread while this thread holds the document's lock. `still_waiting()`
    must hold during the lock (fn has not run); fn must finish once the lock is released."""
    errors: list[BaseException] = []

    def run() -> None:
        try:
            fn()
        except BaseException as e:  # noqa: BLE001 — collected for the assertion
            errors.append(e)

    t = threading.Thread(target=run)
    with document_lock(doc_id):
        t.start()
        time.sleep(0.4)
        assert still_waiting()
    t.join(60)
    assert not t.is_alive()
    return errors


# ---------------------------------------------------------------- B1 locks

def test_a_decision_waits_for_the_document_lock() -> None:
    doc = _upload()
    repo, settings = get_repository(), get_settings()
    target = _selection(doc["id"])
    errors = _while_locked(
        doc["id"], lambda: apply_decision(doc["id"], repo, settings, "mask", target, "occurrence"),
        lambda: repo.get_decisions(doc["id"]) == {})
    assert errors == []
    assert repo.get_decisions(doc["id"])["mask_ranges"]


def test_approve_waits_for_the_document_lock(monkeypatch) -> None:
    doc = _upload()  # heuristic only: in review
    install_llm(monkeypatch, CLEAN)
    repo, settings = get_repository(), get_settings()
    errors = _while_locked(
        doc["id"], lambda: approval.approve(doc["id"], repo, settings),
        lambda: repo.get_document(doc["id"]).status == DocumentStatus.NEEDS_HUMAN_REVIEW)
    assert errors == []
    assert repo.get_document(doc["id"]).status == DocumentStatus.APPROVED


def test_reject_waits_for_the_document_lock() -> None:
    doc = _upload()
    repo, settings = get_repository(), get_settings()
    errors = _while_locked(
        doc["id"], lambda: approval.reject(doc["id"], repo, settings, "yanlış belge"),
        lambda: repo.get_document(doc["id"]).status == DocumentStatus.NEEDS_HUMAN_REVIEW)
    assert errors == []
    assert repo.get_document(doc["id"]).status == DocumentStatus.REJECTED


def test_processing_waits_for_the_document_lock() -> None:
    _seed("queued1", DocumentStatus.QUEUED, original=make_docx(_TEXT))
    repo, settings = get_repository(), get_settings()
    errors = _while_locked(
        "queued1", lambda: process_job("queued1", None, settings, repo),
        lambda: repo.get_document("queued1").status == DocumentStatus.QUEUED)
    assert errors == []
    assert repo.get_document("queued1").status == DocumentStatus.NEEDS_HUMAN_REVIEW


def test_delete_of_a_locked_document_is_busy(monkeypatch) -> None:
    monkeypatch.setattr(approval, "DELETE_WAIT_S", 0.1)
    doc = _upload()
    errors = _while_locked(doc["id"], lambda: approval.delete_document(doc["id"], get_repository()),
                           lambda: True)
    assert [e.code for e in errors if isinstance(e, DecisionError)] == ["document_busy"]
    assert get_repository().get_document(doc["id"]) is not None


# ---------------------------------------------------------------- B2 delete

@pytest.mark.parametrize("status", [DocumentStatus.EXTRACTED, DocumentStatus.MASKING,
                                    DocumentStatus.AUDITING])
def test_delete_is_refused_while_a_document_is_processed(status: DocumentStatus) -> None:
    _seed("busy1", status)
    r = client.delete("/api/documents/busy1")
    assert r.status_code == 409 and r.json()["detail"] == "document_busy"
    assert get_repository().get_document("busy1") is not None


@pytest.mark.parametrize("status", [DocumentStatus.QUEUED, DocumentStatus.NEEDS_HUMAN_REVIEW,
                                    DocumentStatus.APPROVED, DocumentStatus.REJECTED,
                                    DocumentStatus.FAILED])
def test_delete_is_allowed_when_queued_or_settled(status: DocumentStatus) -> None:
    _seed("idle1", status, original=b"raw")
    assert client.delete("/api/documents/idle1").status_code == 204
    assert _folders("idle1") == []


def test_the_worker_skips_a_document_deleted_while_queued() -> None:
    data = make_docx(_TEXT)
    _seed("gone1", DocumentStatus.QUEUED, original=data)
    assert client.delete("/api/documents/gone1").status_code == 204
    process_job("gone1", None, get_settings(), get_repository())
    process_job("gone1", data, get_settings(), get_repository())  # destructive-style job
    assert _folders("gone1") == []


def test_operations_on_a_deleted_document_write_nothing() -> None:
    doc = _upload()
    repo, settings = get_repository(), get_settings()
    target = _selection(doc["id"])
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 204
    calls = [lambda: apply_decision(doc["id"], repo, settings, "mask", target, "occurrence"),
             lambda: approval.approve(doc["id"], repo, settings),
             lambda: approval.reject(doc["id"], repo, settings, "x")]
    for call in calls:
        with pytest.raises(DecisionError) as e:
            call()
        assert e.value.code == "document_not_found" and e.value.status == 404
    assert _folders(doc["id"]) == []


def test_a_delete_cannot_interleave_with_processing(monkeypatch) -> None:
    monkeypatch.setattr(approval, "DELETE_WAIT_S", 0.1)
    _seed("race1", DocumentStatus.QUEUED, original=make_docx(_TEXT))
    real_extract = runner.extract_content
    codes: list[tuple[int, str]] = []

    def extract_then_delete(*args, **kwargs):
        def delete() -> None:
            r = client.delete("/api/documents/race1")
            codes.append((r.status_code, r.json().get("detail", "")))
        t = threading.Thread(target=delete)
        t.start()
        t.join()
        return real_extract(*args, **kwargs)

    monkeypatch.setattr(runner, "extract_content", extract_then_delete)
    process_job("race1", None, get_settings(), get_repository())
    assert codes == [(409, "document_busy")]
    doc = get_repository().get_document("race1")
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW and doc.revision == 1


# ---------------------------------------------------------------- B6 worker failures

def test_a_read_error_at_the_start_of_processing_ends_failed(monkeypatch) -> None:
    _seed("ioerr1", DocumentStatus.QUEUED, original=b"raw")
    repo = get_repository()

    def broken(_doc_id: str):
        raise OSError("disk gone")

    monkeypatch.setattr(repo, "get_original", broken)
    process_job("ioerr1", None, get_settings(), repo)
    doc = repo.get_document("ioerr1")
    assert doc.status == DocumentStatus.FAILED
    assert [r.code for r in doc.reasons] == ["processing_failed"]


def test_a_double_submit_does_not_reprocess_a_settled_document(monkeypatch) -> None:
    install_llm(monkeypatch, CLEAN)
    doc = _upload()
    assert doc["status"] == "approved"
    before = get_repository().get_document(doc["id"])
    process_job(doc["id"], None, get_settings(), get_repository())
    after = get_repository().get_document(doc["id"])
    assert after.status == DocumentStatus.APPROVED
    assert (after.revision, after.updated_at) == (before.revision, before.updated_at)
