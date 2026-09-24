"""End-to-end pipeline via the API: upload → anonymize/audit → download/findings/delete."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures.llm_auditor import llm_clean  # noqa: F401 — pytest fixture

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_pipeline_anonymizes_turkish_and_exposes_no_pii(docx_tr, llm_clean):  # noqa: F811
    j = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)}).json()
    assert j["status"] == "approved"  # a working LLM audited it clean
    gid = j["id"]

    anon = client.get(f"/api/documents/{gid}/masked")
    assert anon.status_code == 200
    assert "Ahmet Yılmaz" not in anon.text  # name masked
    assert "<PERSON_" in anon.text

    detail = client.get(f"/api/documents/{gid}").json()
    assert detail["counts"]["masked"] >= 1
    # The sensitive placeholder->original mapping must never be serialized as a "mapping" key —
    # checked as a key-shaped pattern (not a bare substring) since `detail["mode"]` legitimately
    # has the string value "mapping" (the anonymization-mode field, unrelated to this mapping).
    assert '"mapping":' not in client.get(f"/api/documents/{gid}").text



def test_list_and_delete(docx_en):
    r = client.post("/api/documents", files={"file": ("a.docx", docx_en, _DOCX_MIME)})
    gid = r.json()["id"]
    assert any(d["id"] == gid for d in client.get("/api/documents").json()["documents"])
    assert client.delete(f"/api/documents/{gid}").status_code == 204
    assert client.get(f"/api/documents/{gid}").status_code == 404


def test_masked_404_for_unknown():
    assert client.get("/api/documents/nope/masked").status_code == 404


def _seed(doc_id: str, status):
    from app.extraction.base import Block, ExtractedContent
    from app.models.document import Document, FileKind
    from app.services.deps import get_repository

    repo = get_repository()
    repo.save_document(Document(id=doc_id, filename="x.pdf", kind=FileKind.pdf, status=status))
    repo.save_anonymized(doc_id, ExtractedContent(kind=FileKind.pdf,
                         blocks=[Block(block_id="1", text="residual maybe")]))


def test_anonymized_preview_visible_during_human_review():
    """Gözden geçiren, onaylayacağı metni GÖRMELİ. Önizleme ile dosya indirme aynı kapıya
    bağlıydı; bu, insan inceleme adımını uygulanamaz hale getiriyordu (körlemesine onay)."""
    from app.models.document import DocumentStatus

    _seed("na1", DocumentStatus.NEEDS_HUMAN_REVIEW)
    r = client.get("/api/documents/na1/masked")
    assert r.status_code == 200
    assert "residual maybe" in r.text


def test_anonymized_still_blocked_in_other_unapproved_states():
    """Kapı kaldırılmadı, daraltıldı: yalnız incelemedeki belge görünür."""
    from app.models.document import DocumentStatus

    _seed("na2", DocumentStatus.EXTRACTED)
    assert client.get("/api/documents/na2/masked").status_code == 409


def test_pdf_download_stays_approval_only_during_review():
    """Dışarı ÇIKAN dosya hâlâ yalnız onaydan sonra — paylaşım kapısı değişmedi."""
    from app.models.document import DocumentStatus

    _seed("na3", DocumentStatus.NEEDS_HUMAN_REVIEW)
    assert client.get("/api/documents/na3/download").status_code == 403
