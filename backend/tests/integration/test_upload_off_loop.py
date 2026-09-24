"""Upload keeps the event loop free (coordinator follow-up to the security changes).

`upload_document` is async. In destructive mode `new_document()` masks the upload's name with the
anonymization engine (Presidio), and the first call after startup loads the analyzer: run on the
event loop, that stalled every other request (58 s under load). Validation, the name masking and
the storage writes must run in the thread pool.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.api import documents
from app.main import app
from app.services import storage_repository
from tests.conftest import EN_PARA, make_docx

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _off_loop(fn, seen: list[str]):
    """`fn`, refusing to run on a thread that is running an event loop."""
    def wrapper(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            seen.append(fn.__name__)
            return fn(*args, **kwargs)
        raise AssertionError(f"{fn.__name__} ran on the event loop")
    return wrapper


@pytest.mark.parametrize("mode", ["destructive", "mapping"])
def test_upload_work_runs_off_the_event_loop(monkeypatch, mode: str) -> None:
    seen: list[str] = []
    monkeypatch.setattr(documents, "new_document", _off_loop(documents.new_document, seen))
    monkeypatch.setattr(documents, "validate_upload", _off_loop(documents.validate_upload, seen))
    repo_cls = storage_repository.StorageDocumentRepository
    for name in ("save_document", "save_original"):
        monkeypatch.setattr(repo_cls, name, _off_loop(getattr(repo_cls, name), seen))
    r = client.post("/api/documents", data={"mode": mode},
                    files={"file": ("Ayşe Kaya maaş.docx", make_docx([EN_PARA]), _DOCX_MIME)})
    assert r.status_code == 202, r.text
    assert {"validate_upload", "new_document", "save_document"} <= set(seen)
    assert ("save_original" in seen) == (mode == "mapping")
