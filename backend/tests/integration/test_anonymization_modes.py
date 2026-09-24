"""Two anonymization modes via the API: `mapping` (default, reversible) vs `destructive`
(irreversible — layers 1-2 are never written). See Settings.anonymization_mode / SECURITY.md §2a.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.deps import get_repository

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_default_mode_is_mapping_and_persists_layers_1_2(docx_tr):
    r = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)})
    j = r.json()
    assert j["mode"] == "mapping"
    repo = get_repository()
    doc_id = j["id"]
    assert repo.get_original(doc_id) is not None
    assert repo.get_extracted(doc_id) is not None
    assert repo.get_mapping(doc_id) is not None
    assert repo.get_anonymized(doc_id) is not None


def test_destructive_mode_never_persists_layers_1_2(docx_tr):
    r = client.post(
        "/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)},
        data={"mode": "destructive"},
    )
    j = r.json()
    assert j["mode"] == "destructive"
    repo = get_repository()
    doc_id = j["id"]
    # Layers 1-2: never written at all, not written-then-deleted.
    assert repo.get_original(doc_id) is None
    assert repo.get_extracted(doc_id) is None
    assert repo.get_mapping(doc_id) is None
    # Layer 3 still exists and is masked — destruction only affects what is PERSISTED, not
    # detection quality.
    anon = repo.get_anonymized(doc_id)
    assert anon is not None
    assert "Ahmet" not in anon.plain_text and "sözleşme" in anon.plain_text.lower()


def test_invalid_mode_rejected(docx_tr):
    r = client.post(
        "/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)}, data={"mode": "bogus"}
    )
    assert r.status_code == 400


def _mask_first_word(doc_id: str) -> object:
    review = client.get(f"/api/documents/{doc_id}/review").json()
    unit = next(u for u in review["units"] if (u["original"] or u["masked"]).strip())
    return client.post(f"/api/documents/{doc_id}/decisions", json={
        "op": "mask", "scope": "occurrence",
        "target": {"unit_id": unit["id"], "start": 0, "end": 3, "family": "SENSITIVE"}})


def test_destructive_mode_decision_returns_409_not_404(docx_tr):
    """A decision re-runs anonymization against layer 2 (extracted text) — in destructive mode
    that was never persisted by design, so the API must say why, not 404 as if the document were
    missing."""
    r = client.post(
        "/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)},
        data={"mode": "destructive"},
    )
    resp = _mask_first_word(r.json()["id"])
    assert resp.status_code == 409
    assert resp.json()["detail"] == "original_not_stored"


def test_mapping_mode_decision_works(docx_tr):
    r = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)})
    resp = _mask_first_word(r.json()["id"])
    assert resp.status_code == 200, resp.text
    assert any(s["state"] == "added" for s in resp.json()["spans"])


def test_decision_404_for_unknown_document():
    resp = client.post("/api/documents/does-not-exist/decisions",
                       json={"op": "mask", "scope": "occurrence", "target": {"span_id": "x"}})
    assert resp.status_code == 404
