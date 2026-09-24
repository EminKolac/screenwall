"""Review screen API: payload offsets, decisions, the fail-closed approval gate, reject, pages."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.deps import get_repository
from tests.conftest import make_docx, make_pdf

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_TEXT = [
    "Sayın Ayşe Kaya toplantıya katıldı ve raporu imzaladı.",
    "Ayşe Kaya ile iletişim için ayse.kaya@example.com adresini kullanın.",
]


def _upload(paragraphs: list[str] = _TEXT, mode: str | None = None) -> dict:
    data = {"mode": mode} if mode else {}
    r = client.post("/api/documents", data=data,
                    files={"file": ("rapor.docx", make_docx(paragraphs), _DOCX_MIME)})
    assert r.status_code == 202, r.text
    return r.json()


def _review(doc_id: str) -> dict:
    r = client.get(f"/api/documents/{doc_id}/review")
    assert r.status_code == 200, r.text
    return r.json()


def _to_review(doc_id: str) -> None:
    """Force the document into review (a clean test document is auto-approved)."""
    repo = get_repository()
    doc = repo.get_document(doc_id)
    from app.models.document import DocumentStatus
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)


def test_payload_offsets_are_consistent_both_ways() -> None:
    doc = _upload()
    payload = _review(doc["id"])
    units = {u["id"]: u for u in payload["units"]}
    masked_spans = [s for s in payload["spans"] if s["state"] == "masked" and s["placeholder"]]
    assert masked_spans, "expected masked values"
    for s in masked_spans:
        u = units[s["unit_id"]]
        assert u["masked"][s["masked_start"]:s["masked_end"]] == s["placeholder"]
        assert u["original"][s["start"]:s["end"]].strip()
        assert s["reason"]
    assert payload["document"]["status"] in ("approved", "needs_review")
    assert "mapping" not in payload  # the placeholder->value table never leaves the service


def test_unmask_occurrence_then_mask_it_back() -> None:
    doc = _upload()
    _to_review(doc["id"])
    payload = _review(doc["id"])
    person = next(s for s in payload["spans"] if s["family"] == "PERSON" and s["state"] == "masked")
    r = client.post(f"/api/documents/{doc['id']}/decisions",
                    json={"op": "unmask", "scope": "occurrence",
                          "target": {"span_id": person["id"]}})
    assert r.status_code == 200, r.text
    after = r.json()
    kept = [s for s in after["spans"] if s["state"] == "kept"]
    assert len(kept) == 1
    unit = next(u for u in after["units"] if u["id"] == kept[0]["unit_id"])
    value = unit["original"][kept[0]["start"]:kept[0]["end"]]
    assert value in unit["masked"]  # visible again in the masked text
    # decisions persist: a fresh GET shows the same state
    assert any(s["state"] == "kept" for s in _review(doc["id"])["spans"])
    # masking the kept span again undoes the keep
    r = client.post(f"/api/documents/{doc['id']}/decisions",
                    json={"op": "mask", "scope": "occurrence",
                          "target": {"span_id": kept[0]["id"]}})
    assert r.status_code == 200
    assert not any(s["state"] == "kept" for s in r.json()["spans"])


def test_mask_a_selection_with_a_family() -> None:
    doc = _upload(["Toplantıya Kuzey Grubu temsilcileri de katıldı."])
    _to_review(doc["id"])
    payload = _review(doc["id"])
    unit = payload["units"][0]
    start = unit["original"].index("Kuzey Grubu")
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "mask", "scope": "document",
        "target": {"unit_id": unit["id"], "start": start, "end": start + 11, "family": "ORG"}})
    assert r.status_code == 200, r.text
    added = [s for s in r.json()["spans"] if s["state"] == "added"]
    assert added and added[0]["family"] == "ORG" and added[0]["placeholder"].startswith("<ORG_")
    assert "Kuzey Grubu" not in r.json()["units"][0]["masked"]


def test_invalid_selection_is_rejected() -> None:
    doc = _upload()
    _to_review(doc["id"])
    unit = _review(doc["id"])["units"][0]
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "mask", "scope": "occurrence",
        "target": {"unit_id": unit["id"], "start": 5, "end": 99999, "family": "PERSON"}})
    assert r.status_code == 422
    assert r.json()["detail"] == "invalid_decision"


def test_open_finding_blocks_approval_until_decided() -> None:
    doc = _upload(["Rapor Kuzey Grubu tarafından hazırlandı."])
    _to_review(doc["id"])
    repo = get_repository()
    unit = _review(doc["id"])["units"][0]
    start = unit["masked"].index("Kuzey")
    repo.save_findings(doc["id"], [{
        "id": "f1", "unit_id": unit["id"], "masked_start": start, "masked_end": start + 5,
        "code": "audit_residual", "severity": "high", "status": "open"}])
    d = repo.get_document(doc["id"])
    d.pending_count = 1
    repo.save_document(d)

    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 409 and r.json()["detail"] == "unresolved_items"

    item = _review(doc["id"])["items"][0]
    assert item["status"] == "open" and item["kind"] == "finding"
    r = client.post(f"/api/documents/{doc['id']}/decisions",
                    json={"op": "keep", "scope": "document", "target": {"item_id": item["id"]}})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/documents/{doc['id']}/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert repo.get_chat_context(doc["id"]) is not None


def test_reject_is_a_real_state_now() -> None:
    doc = _upload()
    _to_review(doc["id"])
    r = client.post(f"/api/documents/{doc['id']}/reject", json={"reason": "Yanlış belge"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.post(f"/api/documents/{doc['id']}/reject").status_code == 409
    assert client.get(f"/api/documents/{doc['id']}/review").status_code == 409


def test_destructive_review_has_no_original() -> None:
    doc = _upload(mode="destructive")
    payload = _review(doc["id"])
    assert all(u["original"] is None for u in payload["units"])
    assert payload["pages"] == []
    assert payload["document"]["can"]["decide"] is False


def test_pdf_page_image_and_marks() -> None:
    pdf = make_pdf(["Contact the team at john.smith@example.com for details."])
    r = client.post("/api/documents", files={"file": ("c.pdf", pdf, "application/pdf")})
    doc = r.json()
    _to_review(doc["id"])
    payload = _review(doc["id"])
    assert payload["pages"] and payload["pages"][0]["index"] == 1
    img = client.get(f"/api/documents/{doc['id']}/pages/1")
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert img.headers["cache-control"] == "no-store"
    marks = client.get(f"/api/documents/{doc['id']}/pages/1/marks").json()
    assert marks["marks"], "the masked e-mail should be marked on the page image"
    x0, y0, x1, y1 = marks["marks"][0]["rects"][0]
    assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    assert client.get(f"/api/documents/{doc['id']}/pages/9").status_code == 404


def test_path_traversal_ids_are_not_found() -> None:
    assert client.get("/api/documents/..%2F..%2Fsecret/review").status_code == 404
