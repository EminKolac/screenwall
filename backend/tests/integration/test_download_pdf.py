"""v1 /download: approved anonymized content served as a generated PDF (from storage layer 3 only).

Guarantees under test: the endpoint returns a valid PDF; its text equals the audited anonymized
content (so no original-only channel can leak); PII is masked; and non-ASCII (Turkish) filenames
produce a valid RFC 5987 header instead of a 500.
"""
from __future__ import annotations

import fitz
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _pdf_text(data: bytes) -> str:
    d = fitz.open(stream=data, filetype="pdf")
    try:
        return "\n".join(p.get_text() for p in d)
    finally:
        d.close()


def _approve_if_needed(doc_id: str) -> None:
    status = client.get(f"/api/documents/{doc_id}").json()["status"]
    if status != "approved":
        client.post(f"/api/review/{doc_id}/approve")


def test_download_returns_masked_pdf(docx_tr):
    j = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)}).json()
    doc_id = j["id"]
    _approve_if_needed(doc_id)

    r = client.get(f"/api/documents/{doc_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"

    txt = _pdf_text(r.content)
    assert "Ahmet Yılmaz" not in txt        # original PII masked
    assert "<PERSON_" in txt                # placeholder present
    # Invariant: what is downloaded is exactly the audited anonymized content (layer 3).
    anon = client.get(f"/api/documents/{doc_id}/anonymized").text
    assert "<PERSON_" in anon and "Ahmet Yılmaz" not in anon


def test_download_rfc5987_turkish_filename(docx_tr):
    # A filename with ş/ğ/ı/ö must not raise UnicodeEncodeError in the Content-Disposition header.
    files = {"file": ("Şirket Özet İğ.docx", docx_tr, _DOCX_MIME)}
    j = client.post("/api/documents", files=files).json()
    doc_id = j["id"]
    _approve_if_needed(doc_id)

    r = client.get(f"/api/documents/{doc_id}/download")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd                 # RFC 5987 encoded form present
    assert cd.encode("latin-1")                       # header is latin-1 encodable (no 500)


def test_download_unknown_is_404():
    assert client.get("/api/documents/nope/download").status_code == 404


def test_deny_terms_are_masked():
    """Project deny-list masks brand/fund names NER can't reliably catch (e.g. 'e2vc')."""
    from app.config import get_settings
    from app.pipeline.runner import run_pipeline
    from app.services.deps import get_repository
    from tests.conftest import make_docx

    # Uppercase in the text, lowercase in the deny-list → must still be masked (case-insensitive).
    data = make_docx(["The fund is managed by ZORPTECH Capital and E2VC partners."])
    repo = get_repository()
    doc = run_pipeline(data, "d.docx", get_settings(), repo, deny_terms=["Zorptech", "e2vc"])
    anon = repo.get_anonymized(doc.id)
    assert anon is not None
    assert "ZORPTECH" not in anon.plain_text
    assert "E2VC" not in anon.plain_text


def test_partial_extraction_stays_downloadable(monkeypatch, xlsx_tr):
    """A truncated workbook is fail-closed to human review, but still gets a layer-3 artifact, so
    after approval /download returns a PDF instead of 404 (Codex v1.1 P1)."""
    import app.extraction.xlsx as xmod
    monkeypatch.setattr(xmod, "_MAX_CELLS", 1)  # force truncation on any real workbook

    j = client.post("/api/documents", files={"file": ("m.xlsx", xlsx_tr, _XLSX_MIME)}).json()
    assert j["status"] != "approved"            # blocking warning routed it to review
    doc_id = j["id"]
    client.post(f"/api/review/{doc_id}/approve")
    r = client.get(f"/api/documents/{doc_id}/download")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


def test_download_blocked_before_approval():
    from app.extraction.base import Block, ExtractedContent
    from app.models.document import Document, DocumentStatus, FileKind
    from app.services.deps import get_repository

    repo = get_repository()
    repo.save_document(Document(id="dl1", filename="x.pdf", kind=FileKind.pdf,
                               status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    repo.save_anonymized("dl1", ExtractedContent(kind=FileKind.pdf,
                        blocks=[Block(block_id="1", text="residual maybe")]))
    assert client.get("/api/documents/dl1/download").status_code == 403
