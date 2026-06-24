"""End-to-end pipeline via the API: upload → anonymize/audit → download/findings/delete."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_pipeline_anonymizes_turkish_and_exposes_no_pii(docx_tr):
    j = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)}).json()
    assert j["status"] == "approved"
    gid = j["id"]

    anon = client.get(f"/api/documents/{gid}/anonymized")
    assert anon.status_code == 200
    assert "Ahmet Yılmaz" not in anon.text  # name masked
    assert "<PERSON_" in anon.text

    detail = client.get(f"/api/documents/{gid}").json()
    assert detail["iterations"]
    assert "mapping" not in str(detail)  # mapping never serialized

    findings = client.get(f"/api/documents/{gid}/findings").json()
    assert "iterations" in findings


def test_list_and_delete(docx_en):
    gid = client.post("/api/documents", files={"file": ("a.docx", docx_en, _DOCX_MIME)}).json()["id"]
    assert any(d["id"] == gid for d in client.get("/api/documents").json()["documents"])
    assert client.delete(f"/api/documents/{gid}").status_code == 200
    assert client.get(f"/api/documents/{gid}").status_code == 404


def test_anonymized_404_for_unknown():
    assert client.get("/api/documents/nope/anonymized").status_code == 404


def test_anonymized_blocked_before_approval():
    from app.extraction.base import Block, ExtractedContent
    from app.models.document import Document, DocumentStatus, FileKind
    from app.services.deps import get_repository

    repo = get_repository()
    repo.save_document(Document(id="na1", filename="x.pdf", kind=FileKind.pdf,
                               status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    repo.save_anonymized("na1", ExtractedContent(kind=FileKind.pdf,
                         blocks=[Block(block_id="1", text="residual maybe")]))
    assert client.get("/api/documents/na1/anonymized").status_code == 403
