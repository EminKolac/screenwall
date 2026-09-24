"""Follow-ups from the independent review of the review-hardening change.

1  a re-mask that fails AFTER layer 3 was written must not leave content approvable as audited
2  a download never serves layer 3 written by a re-mask that is still running
3  a reviewer's mask that overlaps an earlier edit covers their union instead of being dropped
4  an unreadable settings file cannot silently drop the user's always-mask list
5  a decision on a document without masked content is 409 no_content, not a 500
6  a document/global unmask of a split-cell fragment is refused (a fragment is no term)
8  a delete racing an upload leaves no orphaned original behind
12 the reject reason masks this document's occurrence masks and audit terms too
13 /api/health honours ollama_allow_remote like the auditor does
"""
from __future__ import annotations

import threading

import fitz
import pytest
from fastapi.testclient import TestClient

from app.api import documents as api_documents
from app.config import get_settings
from app.extraction.base import Block, BlockType, ExtractedContent
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.review import approval
from app.review import decisions as D
from app.review.errors import DecisionError
from app.services.deps import get_repository
from tests.conftest import make_docx, make_xlsx
from tests.fixtures.llm_auditor import CLEAN, install_llm, residual

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TEXT = ["Sayın Ayşe Kaya toplantıya katıldı ve raporu imzaladı.",
         "Ayşe Kaya ile iletişim için ayse.kaya@example.com adresini kullanın."]


def _upload(paragraphs=_TEXT, name: str = "rapor.docx", data: bytes | None = None,
            mime: str = _DOCX_MIME) -> dict:
    r = client.post("/api/documents",
                    files={"file": (name, data or make_docx(paragraphs), mime)})
    assert r.status_code == 202, r.text
    return r.json()


def _person(doc_id: str) -> dict:
    review = client.get(f"/api/documents/{doc_id}/review").json()
    return next(s for s in review["spans"] if s["family"] == "PERSON")


def _unmask(doc_id: str, span: dict):
    return client.post(f"/api/documents/{doc_id}/decisions", json={
        "op": "unmask", "scope": "occurrence", "target": {"span_id": span["id"]}})


# ---------------------------------------------------------------- 1, 2

def test_a_remask_failing_after_layer3_leaves_nothing_approvable_unaudited(monkeypatch):
    install_llm(monkeypatch, residual("annesinin kızlık soyadı"))  # unlocatable: pending 0
    doc = _upload()
    repo = get_repository()
    assert repo.get_document(doc["id"]).audited_revision == doc["revision"]

    def boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(D, "record_findings", boom)
    with pytest.raises(OSError):
        _unmask(doc["id"], _person(doc["id"]))
    monkeypatch.undo()
    provider = install_llm(monkeypatch, CLEAN)
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 200, r.text
    assert provider.calls == 1  # whatever layer 3 now holds was audited before approval
    assert repo.get_chat_context(doc["id"]) == provider.texts[-1]


def test_a_download_never_serves_a_remask_in_progress(monkeypatch):
    install_llm(monkeypatch, CLEAN)
    doc = _upload()
    assert doc["status"] == "approved"
    span = _person(doc["id"])
    seen: list[int] = []
    real = D.HeuristicAuditor

    class DownloadMidway(real):  # runs after the new layer 3 is written, before it is stored
        def audit(self, text):
            try:
                resp = api_documents.download(doc["id"])
                with fitz.open(stream=resp.body, filetype="pdf") as pdf:
                    leaked = "Ayşe Kaya" in "".join(p.get_text() for p in pdf)
                seen.append(403 if not leaked else 200)
            except api_documents.HTTPException as e:
                seen.append(e.status_code)
            return super().audit(text)

    monkeypatch.setattr(D, "HeuristicAuditor", DownloadMidway)
    assert _unmask(doc["id"], span).status_code == 200
    assert seen == [403]


# ---------------------------------------------------------------- 3

def test_an_overlapping_reviewer_mask_covers_the_union(monkeypatch):
    doc = _upload(["Toplantı zeytin bahçesi 42 numarada yapıldı."])
    unit = client.get(f"/api/documents/{doc['id']}/review").json()["units"][0]
    s = unit["original"].index("zeytin")
    part = {"unit_id": unit["id"], "start": s, "end": s + 6, "family": "ORG"}
    whole = {**part, "end": s + len("zeytin bahçesi 42")}
    for scope, target in (("occurrence", part), ("document", whole)):
        r = client.post(f"/api/documents/{doc['id']}/decisions",
                        json={"op": "mask", "scope": scope, "target": target})
        assert r.status_code == 200, r.text
    masked = r.json()["units"][0]["masked"]
    assert "bahçesi" not in masked and "42" not in masked


# ---------------------------------------------------------------- 4

def test_list_entries_are_validated_one_by_one():
    from app.services.user_settings import load_user_settings

    path = get_settings().storage_root / "user_settings.json"
    path.write_text('{"always_mask": ["Gizli Fon", 42, "Zeytinfon"]}', "utf-8")
    assert load_user_settings(get_settings()).always_mask == ["Gizli Fon", "Zeytinfon"]


def test_an_unreadable_settings_file_blocks_auto_approval(monkeypatch):
    install_llm(monkeypatch, CLEAN)
    (get_settings().storage_root / "user_settings.json").write_text("{torn", "utf-8")
    doc = _upload()
    assert doc["status"] == "needs_review"
    assert "settings_unreadable" in {r["code"] for r in doc["reasons"]}


# ---------------------------------------------------------------- 5

def test_a_decision_without_masked_content_is_409_no_content():
    repo = get_repository()
    repo.save_document(Document(id="notext1", filename="x.docx", kind=FileKind.docx,
                                status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    repo.save_extracted("notext1", ExtractedContent(
        kind=FileKind.docx, blocks=[Block(block_id="b", type=BlockType.paragraph,
                                          text="abc def")]))
    r = client.post("/api/documents/notext1/decisions", json={
        "op": "mask", "scope": "occurrence",
        "target": {"unit_id": "b", "start": 0, "end": 3, "family": "ORG"}})
    assert r.status_code == 409 and r.json()["detail"] == "no_content"


# ---------------------------------------------------------------- 6

@pytest.mark.parametrize("scope", ["document", "global"])
def test_a_split_cell_fragment_cannot_be_unmasked_as_a_term(scope: str):
    doc = _upload(data=make_xlsx([["0532 76", "4 21 09"]]), name="t.xlsx", mime=_XLSX_MIME)
    review = client.get(f"/api/documents/{doc['id']}/review").json()
    fragment = next(s for s in review["spans"] if "adjacency" in s["evidence"])
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "unmask", "scope": scope, "target": {"span_id": fragment["id"]}})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_decision"
    assert client.get("/api/settings").json()["never_mask"] == []


# ---------------------------------------------------------------- 8

def test_a_delete_racing_an_upload_leaves_no_original_behind(monkeypatch):
    """The document record exists a moment before its original is stored; a delete in that
    moment used to remove the record and then see the original land, orphaned and invisible."""
    monkeypatch.setattr(approval, "DELETE_WAIT_S", 60.0)
    repo_cls = type(get_repository())
    real = repo_cls.save_original
    outcome: list[str] = []
    threads: list[threading.Thread] = []

    def delete(doc_id: str) -> None:
        try:
            approval.delete_document(doc_id, get_repository())
            outcome.append("deleted")
        except DecisionError as e:
            outcome.append(e.code)

    def save_original(self, doc_id, data, filename):
        t = threading.Thread(target=delete, args=(doc_id,))
        t.start()
        threads.append(t)
        t.join(0.3)  # the delete gets its chance while the upload is between its two writes
        return real(self, doc_id, data, filename)

    monkeypatch.setattr(repo_cls, "save_original", save_original)
    doc = _upload()
    for t in threads:
        t.join(60)
    assert outcome == ["deleted"]
    root = get_settings().storage_root
    assert [p for p in root.glob(f"*/{doc['id']}")] == []


# ---------------------------------------------------------------- 12

def test_the_reject_reason_masks_occurrence_masks_and_audit_terms(monkeypatch):
    install_llm(monkeypatch, residual("zeytinkod"), residual("bahçekod"))
    doc = _upload(["Rapor zeytinkod ile bahçekod ve kuzeykod hakkında."])
    unit = client.get(f"/api/documents/{doc['id']}/review").json()["units"][0]
    s = unit["original"].index("kuzeykod")
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "mask", "scope": "occurrence",
        "target": {"unit_id": unit["id"], "start": s, "end": s + 8, "family": "ORG"}})
    assert r.status_code == 200, r.text
    reason = "zeytinkod, bahçekod ve kuzeykod yanlış işlenmiş."
    assert client.post(f"/api/documents/{doc['id']}/reject",
                       json={"reason": reason}).status_code == 200
    stored = get_repository().get_document(doc["id"]).reject_reason
    for value in ("zeytinkod", "bahçekod", "kuzeykod"):
        assert value not in stored


# ---------------------------------------------------------------- 13

def test_health_honours_ollama_allow_remote(monkeypatch):
    import app.audit.ollama_provider as op

    seen: list[bool] = []
    real = op.OllamaProvider

    class Spy(real):
        def __init__(self, *a, **k):
            seen.append(k.get("allow_remote", False))
            super().__init__(*a, **k)

        def is_available(self) -> bool:
            return False

    monkeypatch.setattr(op, "OllamaProvider", Spy)
    monkeypatch.setenv("AUDITOR_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_ALLOW_REMOTE", "true")
    get_settings.cache_clear()
    assert client.get("/api/health").status_code == 200
    assert seen == [True]
