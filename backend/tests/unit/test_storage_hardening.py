"""Storage hardening (review hardening B4, B5, B7).

B4  every write is atomic through a UNIQUE temp file (mkstemp, 0600) and os.replace; a failure
    removes only that call's own temp file, never another writer's.
B5  one unreadable document.json cannot make listing return 500 or block startup recovery; only
    the error type is logged, never content.
B7  documents stored by a pre-v2 release in a per-iteration status load as FAILED with a reason.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import threading

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.pipeline.queue import Worker
from app.services.deps import get_repository
from app.storage import local
from app.storage.base import StorageLayer

client = TestClient(app)


# ---------------------------------------------------------------- B4 atomic writes

def test_a_write_never_touches_another_writers_temp_file(tmp_path) -> None:
    target = tmp_path / "doc.json"
    foreign = tmp_path / "doc.json.tmp"
    foreign.write_bytes(b"another writer")
    local.write_private(target, b"mine")
    assert target.read_bytes() == b"mine"
    assert foreign.read_bytes() == b"another writer"


def test_a_failed_write_removes_only_its_own_temp_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "doc.json"
    foreign = tmp_path / "doc.json.tmp"
    foreign.write_bytes(b"another writer")

    def fail(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(local.os, "replace", fail)
    with pytest.raises(OSError):
        local.write_private(target, b"mine")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["doc.json.tmp"]
    assert foreign.read_bytes() == b"another writer"


def test_written_files_are_private(tmp_path) -> None:
    target = tmp_path / "doc.json"
    local.write_private(target, b"x")
    assert stat.S_IMODE(os.stat(target).st_mode) == 0o600


def test_concurrent_writers_to_one_file_all_succeed(tmp_path) -> None:
    target = tmp_path / "doc.json"
    errors: list[BaseException] = []

    def write(n: int) -> None:
        try:
            for i in range(25):
                local.write_private(target, json.dumps({"writer": n, "i": i}).encode())
        except BaseException as e:  # noqa: BLE001 — collected for the assertion
            errors.append(e)

    threads = [threading.Thread(target=write, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert json.loads(target.read_text())["i"] == 24
    assert [p.name for p in tmp_path.iterdir()] == ["doc.json"]


def test_secure_delete_keeps_the_record_when_a_layer_survives(tmp_path, monkeypatch) -> None:
    """The document record (layer 4) goes last, and only when every other layer is gone: a
    delete that leaves raw data behind fails loudly and stays retryable."""
    backend = local.LocalStorageBackend(tmp_path)
    for layer in StorageLayer:
        backend.write_bytes(layer, "d1", "f.bin", b"sensitive")
    real = local.shutil.rmtree

    def keep_originals(path, *args, **kwargs):
        if StorageLayer.ORIGINAL.value not in str(path):
            real(path, *args, **kwargs)

    monkeypatch.setattr(local.shutil, "rmtree", keep_originals)
    with pytest.raises(OSError):
        backend.delete_document("d1", secure=True)
    assert backend.exists(StorageLayer.VALIDATION, "d1", "f.bin")


# ---------------------------------------------------------------- B5 unreadable documents

def _torn(doc_id: str) -> None:
    folder = get_settings().storage_root / StorageLayer.VALIDATION.value / doc_id
    folder.mkdir(parents=True)
    (folder / "document.json").write_text('{"id": "x", "filename": "Ayşe Kaya maaş.pdf", "st')


def _seed(doc_id: str, status: DocumentStatus) -> None:
    get_repository().save_document(Document(id=doc_id, filename="a.docx", kind=FileKind.docx,
                                            status=status))


def test_listing_skips_an_unreadable_document(caplog) -> None:
    _seed("good1", DocumentStatus.NEEDS_HUMAN_REVIEW)
    _torn("torn1")
    with caplog.at_level(logging.WARNING):
        r = client.get("/api/documents")
    assert r.status_code == 200
    assert [d["id"] for d in r.json()["documents"]] == ["good1"]
    assert "JSONDecodeError" in caplog.text
    assert "Ayşe" not in caplog.text


def test_a_malformed_legacy_document_is_skipped_too() -> None:
    _seed("good2", DocumentStatus.NEEDS_HUMAN_REVIEW)
    folder = get_settings().storage_root / StorageLayer.VALIDATION.value / "legacybad"
    folder.mkdir(parents=True)
    (folder / "document.json").write_text(json.dumps({
        "id": "legacybad", "filename": "a.pdf", "kind": "pdf", "status": "presidio_pass_1",
        "reasons": 5}))
    r = client.get("/api/documents")
    assert r.status_code == 200
    listed = {d["id"]: d for d in r.json()["documents"]}
    assert set(listed) == {"good2", "legacybad"}
    assert listed["legacybad"]["status"] == "failed"
    assert [x["code"] for x in listed["legacybad"]["reasons"]] == ["legacy_status"]
    assert Worker(get_settings, get_repository).recover() == 0


def test_recovery_skips_an_unreadable_document() -> None:
    _seed("stuck1", DocumentStatus.MASKING)  # destructive-like: no original → FAILED
    _torn("torn2")
    assert Worker(get_settings, get_repository).recover() == 0
    assert get_repository().get_document("stuck1").status == DocumentStatus.FAILED


# ---------------------------------------------------------------- B7 legacy statuses

@pytest.mark.parametrize("legacy", ["presidio_pass_1", "qwen_audit_2", "presidio_pass_7"])
def test_a_legacy_iteration_status_loads_as_failed_with_a_reason(legacy: str) -> None:
    doc = Document.model_validate({"id": "old", "filename": "a.pdf", "kind": "pdf",
                                   "status": legacy})
    assert doc.status == DocumentStatus.FAILED
    assert [(r.code, r.text) for r in doc.reasons] == [
        ("legacy_status", "Bu belge eski bir sürümde işlenmişti; yeniden yükleyin.")]
    again = Document.model_validate(doc.model_dump(mode="json"))
    assert [r.code for r in again.reasons] == ["legacy_status"]
