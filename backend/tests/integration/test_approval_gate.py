"""The approval gate (review hardening A3/A4): approve is fail-closed and revision-checked.

Approve needs a document in review with anonymized content and no open item. A document changed
since its last SUCCESSFUL LLM audit is re-audited first: no working LLM → 503 and nothing is
approved; a residual the audit locates → 409 unresolved_items; an audit that is not clean but
located nothing → 409 audit_not_clean, and the second click (the human has seen the reasons)
approves. Layer 5 is built from the very content object that was audited.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.extraction.base import Block, ExtractedContent
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.services.deps import get_repository
from tests.conftest import make_docx
from tests.fixtures.llm_auditor import CLEAN, install_llm, residual

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_TEXT = [
    "Sayın Ayşe Kaya toplantıya katıldı ve raporu imzaladı.",
    "Ayşe Kaya ile iletişim için ayse.kaya@example.com adresini kullanın.",
]


def _upload(paragraphs: list[str] = _TEXT) -> dict:
    r = client.post("/api/documents",
                    files={"file": ("rapor.docx", make_docx(paragraphs), _DOCX_MIME)})
    assert r.status_code == 202, r.text
    return r.json()


def _summary(doc_id: str) -> dict:
    return client.get(f"/api/documents/{doc_id}").json()


def _codes(summary: dict) -> set[str]:
    return {r["code"] for r in summary["reasons"]}


def _changed_in_review(monkeypatch) -> dict:
    """An approved document (working LLM) that a reviewer then changed: back in review, with a
    revision the LLM has not audited."""
    install_llm(monkeypatch, CLEAN)
    doc = _upload()
    assert doc["status"] == "approved"
    review = client.get(f"/api/documents/{doc['id']}/review").json()
    person = next(s for s in review["spans"] if s["family"] == "PERSON")
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "unmask", "scope": "occurrence", "target": {"span_id": person["id"]}})
    assert r.status_code == 200, r.text
    assert r.json()["document"]["status"] == "needs_review"
    return r.json()["document"]


def test_approve_with_no_llm_configured_is_503_and_nothing_is_approved() -> None:
    doc = _upload()  # heuristic only: routed to review, never approved
    assert doc["status"] == "needs_review"
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 503 and r.json()["detail"] == "ollama_unreachable"
    after = _summary(doc["id"])
    assert after["status"] == "needs_review"
    assert "auditor_unavailable" in _codes(after)
    assert get_repository().get_chat_context(doc["id"]) is None


def test_approve_with_a_failing_llm_is_503(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    install_llm(monkeypatch, CLEAN, available=False)
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 503 and r.json()["detail"] == "ollama_unreachable"
    assert _summary(doc["id"])["status"] == "needs_review"
    assert "auditor_unavailable" in _codes(_summary(doc["id"]))


def test_a_changed_document_is_reaudited_by_the_llm_before_approval(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    provider = install_llm(monkeypatch, CLEAN)
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert provider.calls == 1
    stored = get_repository().get_document(doc["id"])
    assert stored.audited_revision == stored.revision
    assert get_repository().get_chat_context(doc["id"]) == provider.texts[-1]


def test_approve_without_anonymized_content_is_409_no_content() -> None:
    repo = get_repository()
    repo.save_document(Document(id="nocontent1", filename="x.pdf", kind=FileKind.pdf,
                                status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    r = client.post("/api/documents/nocontent1/approve")
    assert r.status_code == 409 and r.json()["detail"] == "no_content"
    assert repo.get_document("nocontent1").status == DocumentStatus.NEEDS_HUMAN_REVIEW


def test_a_residual_the_llm_locates_blocks_approval(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    install_llm(monkeypatch, residual("Ayşe Kaya"))
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"] == "unresolved_items"
    review = client.get(f"/api/documents/{doc['id']}/review").json()
    assert review["document"]["status"] == "needs_review"
    assert any(i["status"] == "open" for i in review["items"])
    # new findings replace the old item ids: the revision moves so a stale client is refused
    assert review["document"]["revision"] == doc["revision"] + 1
    stored = get_repository().get_document(doc["id"])
    assert stored.audited_revision == stored.revision


def test_an_unclean_audit_that_locates_nothing_needs_a_second_click(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    provider = install_llm(monkeypatch, residual("adı geçen kişinin annesinin kızlık soyadı"))
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"] == "audit_not_clean"
    assert "audit_unlocated" in _codes(_summary(doc["id"]))
    assert _summary(doc["id"])["status"] == "needs_review"
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert provider.calls == 1  # the second click approves what the human has now seen


def test_expected_revision_must_match(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    install_llm(monkeypatch, CLEAN)
    r = client.post(f"/api/documents/{doc['id']}/approve",
                    json={"expected_revision": doc["revision"] - 1})
    assert r.status_code == 409 and r.json()["detail"] == "stale_revision"
    assert _summary(doc["id"])["status"] == "needs_review"
    r = client.post(f"/api/documents/{doc['id']}/approve",
                    json={"expected_revision": doc["revision"]})
    assert r.status_code == 200, r.text


def test_a_document_stored_before_this_rule_is_reaudited_before_approval() -> None:
    """Before review hardening, `audited_revision` was also set by heuristic-only audits. A stored
    document without the new audit scheme must not count as LLM-audited."""
    import json

    from app.config import get_settings

    repo = get_repository()
    doc = Document(id="legacy1", filename="x.docx", kind=FileKind.docx,
                   status=DocumentStatus.NEEDS_HUMAN_REVIEW, revision=1, audited_revision=1)
    repo.save_document(doc)
    repo.save_anonymized("legacy1", ExtractedContent(
        kind=FileKind.docx, blocks=[Block(block_id="b1", text="Temiz bir metin.")]))
    path = get_settings().storage_root / "4_validation" / "legacy1" / "document.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored.pop("audit_scheme", None)  # as written by the previous release
    path.write_text(json.dumps(stored), encoding="utf-8")
    assert repo.get_document("legacy1").audited_revision == -1
    r = client.post("/api/documents/legacy1/approve")  # no LLM configured in tests
    assert r.status_code == 503 and r.json()["detail"] == "ollama_unreachable"
    assert repo.get_document("legacy1").status == DocumentStatus.NEEDS_HUMAN_REVIEW


def test_layer5_is_the_audited_content_not_a_later_reread(monkeypatch) -> None:
    doc = _changed_in_review(monkeypatch)
    provider = install_llm(monkeypatch, CLEAN)
    repo = get_repository()
    tampered = ExtractedContent(kind=FileKind.docx, blocks=[Block(block_id="x", text="DEĞİŞTİ")])
    provider.on_call = lambda _text: repo.save_anonymized(doc["id"], tampered)
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 200, r.text
    context = repo.get_chat_context(doc["id"])
    assert context == provider.texts[-1]
    assert "DEĞİŞTİ" not in context
