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


def test_destructive_mode_redact_returns_409_not_404(docx_tr):
    """Manual redaction needs layer 2 (extracted text) to re-run anonymization against — in
    destructive mode that was never persisted by design, so the endpoint must say why, not just
    404 as if the document itself were missing."""
    r = client.post(
        "/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)},
        data={"mode": "destructive"},
    )
    doc_id = r.json()["id"]
    resp = client.post(f"/api/review/{doc_id}/redact", json={"terms": ["Ahmet"]})
    assert resp.status_code == 409
    assert "destructive" in resp.json()["detail"]


def test_mapping_mode_redact_still_works(docx_tr):
    """Regression guard: the mode-aware 409 in review.redact() must not shadow the ordinary
    404-when-truly-missing case, nor break redaction in mapping mode."""
    r = client.post("/api/documents", files={"file": ("s.docx", docx_tr, _DOCX_MIME)})
    doc_id = r.json()["id"]
    resp = client.post(f"/api/review/{doc_id}/redact", json={"terms": ["Sözleşme"]})
    assert resp.status_code == 200


def test_redact_404_for_unknown_document():
    resp = client.post("/api/review/does-not-exist/redact", json={"terms": ["x"]})
    assert resp.status_code == 404
