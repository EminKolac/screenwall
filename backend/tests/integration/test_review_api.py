"""Human-review workflow: pending queue → approve (builds chat context) / reject."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.extraction.base import Block, ExtractedContent
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.services.deps import get_repository

client = TestClient(app)


def _seed_needs_review(doc_id: str) -> None:
    repo = get_repository()
    repo.save_document(Document(
        id=doc_id, filename="x.pdf", kind=FileKind.pdf,
        status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    repo.save_anonymized(doc_id, ExtractedContent(
        kind=FileKind.pdf, blocks=[Block(block_id="1", text="<PERSON_1> signed the agreement.")]))


def test_pending_then_approve_builds_chat_context():
    _seed_needs_review("rev1")
    pending = client.get("/api/review/pending").json()["documents"]
    assert any(d["id"] == "rev1" for d in pending)

    r = client.post("/api/review/rev1/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    assert r.json()["chat_enabled"] is True
    assert get_repository().get_chat_context("rev1") is not None


def test_reject_keeps_needs_review():
    _seed_needs_review("rev2")
    r = client.post("/api/review/rev2/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "needs_human_review"


def test_approve_unknown_404():
    assert client.post("/api/review/nope/approve").status_code == 404
