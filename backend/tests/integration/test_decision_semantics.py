"""Decision semantics through the API (review hardening B3, C3-C5, C7-C10, C12, C14).

What a reviewer decides must mean exactly that and nothing more: one occurrence stays one
occurrence, a term is a term however it is capitalized, a kept finding stays kept, an audit's
repair survives an unrelated decision, a global mask keeps its family, a failed re-mask changes
nothing, and a stale client cannot hit the wrong span.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.anonymization.engine import Engine
from app.main import app
from app.services.deps import get_repository
from tests.conftest import make_docx
from tests.fixtures.llm_auditor import CLEAN, install_llm, residual

client = TestClient(app)
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_KUZEY = ["Rapor Kuzey Grubu tarafından hazırlandı.", "KUZEY GRUBU raporu onayladı."]
_FINDINGS = ["Kuzey Grubu zeytin bahçesi için toplandı.", "Sonra zeytin bahçesi satıldı."]


def _upload(paragraphs: list[str], name: str = "rapor.docx", mode: str | None = None) -> dict:
    data = {"mode": mode} if mode else {}
    r = client.post("/api/documents", data=data,
                    files={"file": (name, make_docx(paragraphs), _DOCX_MIME)})
    assert r.status_code == 202, r.text
    return r.json()


def _review(doc_id: str) -> dict:
    r = client.get(f"/api/documents/{doc_id}/review")
    assert r.status_code == 200, r.text
    return r.json()


def _decide(doc_id: str, op: str, scope: str, target: dict, **extra) -> dict:
    r = client.post(f"/api/documents/{doc_id}/decisions",
                    json={"op": op, "scope": scope, "target": target, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _select(payload: dict, value: str, unit: int = 0, family: str = "ORG") -> dict:
    u = payload["units"][unit]
    start = u["original"].index(value)
    return {"unit_id": u["id"], "start": start, "end": start + len(value), "family": family}


def _masked(payload: dict) -> list[str]:
    return [u["masked"] for u in payload["units"]]


# ---------------------------------------------------------------- B3 stale clients

def test_summary_carries_the_revision_and_a_stale_decision_is_refused() -> None:
    doc = _upload(_KUZEY)
    payload = _review(doc["id"])
    rev = payload["document"]["revision"]
    assert rev == doc["revision"] >= 1
    target = _select(payload, "Kuzey Grubu")
    r = client.post(f"/api/documents/{doc['id']}/decisions", json={
        "op": "mask", "scope": "occurrence", "target": target, "expected_revision": rev - 1})
    assert r.status_code == 409 and r.json()["detail"] == "stale_revision"
    assert get_repository().get_decisions(doc["id"]) == {}
    after = _decide(doc["id"], "mask", "occurrence", target, expected_revision=rev)
    assert after["document"]["revision"] == rev + 1


# ---------------------------------------------------------------- C3 / C4 terms

def test_unmasking_one_occurrence_of_a_document_mask_keeps_the_others() -> None:
    doc = _upload(["Rapor Kuzey Grubu tarafından hazırlandı.", "Kuzey Grubu onayladı."])
    after = _decide(doc["id"], "mask", "document", _select(_review(doc["id"]), "Kuzey Grubu"))
    added = [s for s in after["spans"] if s["state"] == "added"]
    assert len(added) == 2
    after = _decide(doc["id"], "unmask", "occurrence", {"span_id": added[0]["id"]})
    first, second = _masked(after)
    assert "Kuzey Grubu" in first  # this occurrence only
    assert "Kuzey Grubu" not in second and "<ORG_" in second


def test_term_keys_ignore_case_and_spacing_when_unmasking() -> None:
    doc = _upload(_KUZEY)
    after = _decide(doc["id"], "mask", "document", _select(_review(doc["id"]), "Kuzey Grubu"))
    assert all("<ORG_" in m for m in _masked(after))
    upper = next(s for s in after["spans"]
                 if s["state"] == "added" and s["unit_id"] == after["units"][1]["id"])
    after = _decide(doc["id"], "unmask", "document", {"span_id": upper["id"]})
    assert "Kuzey Grubu" in _masked(after)[0] and "KUZEY GRUBU" in _masked(after)[1]
    assert not get_repository().get_decisions(doc["id"]).get("mask_terms")


# ---------------------------------------------------------------- C5 / C8 audit findings

def _with_findings(monkeypatch, mode: str | None = None) -> dict:
    """Pipeline with a scripted LLM: iteration 1 flags "Kuzey Grubu" (the repair round masks it),
    iteration 2 flags "zeytin bahçesi" (left open, two occurrences)."""
    install_llm(monkeypatch, residual("Kuzey Grubu"), residual("zeytin bahçesi"))
    doc = _upload(_FINDINGS, mode=mode)
    assert doc["status"] == "needs_review"
    return doc


def _open_items(payload: dict) -> list[dict]:
    return [i for i in payload["items"] if i["status"] == "open"]


def test_an_occurrence_keep_marks_only_that_finding(monkeypatch) -> None:
    doc = _with_findings(monkeypatch)
    payload = _review(doc["id"])
    items = _open_items(payload)
    assert len(items) == 2 and payload["document"]["counts"]["pending"] == 2
    after = _decide(doc["id"], "keep", "occurrence", {"item_id": items[0]["id"]})
    assert len(_open_items(after)) == 1
    assert after["document"]["counts"]["pending"] == 1
    after = _decide(doc["id"], "keep", "document", {"item_id": _open_items(after)[0]["id"]})
    assert _open_items(after) == [] and after["document"]["counts"]["pending"] == 0


def test_an_unrelated_decision_keeps_the_audit_repairs_and_open_findings(monkeypatch) -> None:
    doc = _with_findings(monkeypatch)
    before = _review(doc["id"])
    assert all("Kuzey Grubu" not in m for m in _masked(before))  # repaired by the audit loop
    after = _decide(doc["id"], "mask", "occurrence", _select(before, "Sonra", unit=1))
    assert all("Kuzey Grubu" not in m for m in _masked(after))
    assert len(_open_items(after)) == 2
    assert after["document"]["counts"]["pending"] == 2


def test_kept_findings_stay_kept_across_later_decisions(monkeypatch) -> None:
    doc = _with_findings(monkeypatch)
    item = _open_items(_review(doc["id"]))[0]
    _decide(doc["id"], "keep", "document", {"item_id": item["id"]})
    after = _decide(doc["id"], "mask", "occurrence", _select(_review(doc["id"]), "Sonra", 1))
    assert _open_items(after) == []
    assert [i["status"] for i in after["items"]] == ["kept", "kept"]


def test_audit_terms_live_in_layer2_in_mapping_mode_only(monkeypatch) -> None:
    mapped = _with_findings(monkeypatch)
    repo = get_repository()
    terms = {t["term"]: t["status"] for t in repo.get_audit_terms(mapped["id"])}
    assert terms == {"Kuzey Grubu": "masked", "zeytin bahçesi": "open"}
    gone = _with_findings(monkeypatch, mode="destructive")
    assert repo.get_audit_terms(gone["id"]) == []


# ---------------------------------------------------------------- C7 global family

def test_a_global_mask_keeps_the_chosen_family() -> None:
    doc = _upload(["Toplantıya Kuzey Grubu temsilcileri de katıldı."])
    after = _decide(doc["id"], "mask", "global", _select(_review(doc["id"]), "Kuzey Grubu"))
    assert "<ORG_" in _masked(after)[0] and "SENSITIVE" not in _masked(after)[0]
    prefs = client.get("/api/settings").json()
    assert prefs["always_mask"] == ["Kuzey Grubu"]
    assert prefs["always_mask_family"] == {"Kuzey Grubu": "ORG"}
    other = _upload(["Kuzey Grubu yeni bir rapor yazdı."])
    assert "<ORG_" in client.get(f"/api/documents/{other['id']}/masked").text


# ---------------------------------------------------------------- C9 validation

@pytest.mark.parametrize("bad", [
    {"start": "abc"}, {"start": 1.5}, {"end": True}, {"family": "ORG\n"}, {"family": "org"},
    {"unit_id": ["x"]},
])
def test_malformed_targets_are_422_invalid_decision(bad: dict) -> None:
    doc = _upload(_KUZEY)
    target = {**_select(_review(doc["id"]), "Kuzey Grubu"), **bad}
    r = client.post(f"/api/documents/{doc['id']}/decisions",
                    json={"op": "mask", "scope": "occurrence", "target": target})
    assert r.status_code == 422 and r.json()["detail"] == "invalid_decision"


# ---------------------------------------------------------------- C10 failed re-mask

def test_a_failed_remask_leaves_the_decisions_unchanged(monkeypatch) -> None:
    doc = _upload(_KUZEY)
    repo = get_repository()
    target = _select(_review(doc["id"]), "Kuzey Grubu")
    _decide(doc["id"], "mask", "occurrence", target)
    before, revision = repo.get_decisions(doc["id"]), repo.get_document(doc["id"]).revision

    def boom(*_a, **_k):
        raise RuntimeError("engine failed")

    monkeypatch.setattr(Engine, "anonymize", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/documents/{doc['id']}/decisions", json={
            "op": "mask", "scope": "document", "target": {**target, "family": "PERSON"}})
    assert repo.get_decisions(doc["id"]) == before
    assert repo.get_document(doc["id"]).revision == revision


def test_a_failed_remask_rolls_back_a_global_decision(monkeypatch) -> None:
    doc = _upload(_KUZEY)
    target = _select(_review(doc["id"]), "Kuzey Grubu")
    before = client.get("/api/settings").json()

    def boom(*_a, **_k):
        raise RuntimeError("engine failed")

    monkeypatch.setattr(Engine, "anonymize", boom)
    with pytest.raises(RuntimeError):
        client.post(f"/api/documents/{doc['id']}/decisions",
                    json={"op": "mask", "scope": "global", "target": target})
    monkeypatch.undo()
    assert client.get("/api/settings").json() == before
    assert get_repository().get_decisions(doc["id"]) == {}


# ---------------------------------------------------------------- C12 download filename

def test_the_download_filename_applies_every_deny_term(monkeypatch) -> None:
    install_llm(monkeypatch, CLEAN)
    r = client.put("/api/settings", json={"always_mask": ["zeytinfon"]})
    assert r.status_code == 200, r.text
    doc = _upload(["Kuzey Grubu zeytinfon raporunu yazdı."], name="zeytinfon Kuzey Grubu.docx")
    _decide(doc["id"], "mask", "document", _select(_review(doc["id"]), "Kuzey Grubu"))
    assert client.post(f"/api/documents/{doc['id']}/approve").status_code == 200
    header = client.get(f"/api/documents/{doc['id']}/download").headers["content-disposition"]
    assert "zeytinfon" not in header.casefold()
    assert "kuzey" not in header.casefold()


# ---------------------------------------------------------------- C14 reject reason

def test_the_reject_reason_is_stored_redacted_and_capped() -> None:
    doc = _upload(_KUZEY)
    reason = ("Sayın Ayşe Kaya belgeyi yanlış yükledi; TCKN 10000000146, e-posta "
              "ayse.kaya@example.com, telefon 0532 111 22 33. " + "ek açıklama " * 60)
    r = client.post(f"/api/documents/{doc['id']}/reject", json={"reason": reason})
    assert r.status_code == 200, r.text
    stored = get_repository().get_document(doc["id"]).reject_reason
    for raw in ("Ayşe Kaya", "10000000146", "ayse.kaya@example.com", "0532 111 22 33"):
        assert raw not in stored
    assert 0 < len(stored) <= 200
