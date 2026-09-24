"""Faz 3 (insan düzeltmesi) + Faz 4 (review.py'deki üç hata) regresyonları.

Faz 4'te düzeltilen hatalar — üçü de `redact` içindeydi:
  1. Proje deny-list'i düşüyordu → "daha fazla karart" isteyen işlem, global deny-list'teki bir
     terimin maskesini KALDIRABİLİYORDU.
  2. Allow-list tamamen düşüyordu → manuel karartma aşırı-maskelemeyi geri getiriyordu.
  3. `IterationRecord` eklenmiyordu → elle karartma denetim izinde görünmüyordu.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app


def _docx(paragraphs: list[str]) -> bytes:
    import docx as _docx_mod
    d = _docx_mod.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


def _upload(client, paragraphs, **kwargs):
    data = _docx(paragraphs)
    r = client.post("/api/documents",
                    files={"file": ("test.docx", data,
                                    "application/vnd.openxmlformats-officedocument."
                                    "wordprocessingml.document")},
                    **kwargs)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_unmask_reverses_a_single_placeholder(client):
    doc = _upload(client, ["Sayın Kemal Vardar toplantıya katıldı.",
                           "İletişim: kemal.vardar@ornekposta.com"])
    doc_id = doc["id"]
    anon = client.get(f"/api/documents/{doc_id}/anonymized")
    if anon.status_code != 200:  # onay gerekiyorsa önce onayla
        client.post(f"/api/review/{doc_id}/approve")
        anon = client.get(f"/api/documents/{doc_id}/anonymized")
    text = anon.text
    assert "<PERSON_1>" in text or "<EMAIL_1>" in text

    token = "<PERSON_1>" if "<PERSON_1>" in text else "<EMAIL_1>"
    r = client.post(f"/api/review/{doc_id}/unmask", json={"token": token})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unmasked_total"] == 1
    # Geri alma sonrası belge yeniden insan onayına düşer (sessizce onaylı kalmaz).
    assert body["status"] == "needs_human_review"


def test_unmask_never_returns_the_raw_value(client):
    """Uç, tek token'ın değerini ÇÖZER ama yanıtta DÖNDÜRMEZ — aksi halde eşleme tablosu
    token-token sızdırılabilirdi."""
    doc = _upload(client, ["Sayın Kemal Vardar toplantıya katıldı."])
    doc_id = doc["id"]
    client.post(f"/api/review/{doc_id}/approve")
    r = client.post(f"/api/review/{doc_id}/unmask", json={"token": "<PERSON_1>"})
    if r.status_code == 200:
        assert "Kemal" not in r.text and "Vardar" not in r.text


def test_unmask_unknown_token_is_404(client):
    doc = _upload(client, ["Sıradan bir cümle."])
    r = client.post(f"/api/review/{doc['id']}/unmask", json={"token": "<PERSON_99>"})
    assert r.status_code == 404


def test_unmask_empty_token_is_400(client):
    doc = _upload(client, ["Sıradan bir cümle."])
    r = client.post(f"/api/review/{doc['id']}/unmask", json={"token": "   "})
    assert r.status_code == 400


def test_unmask_in_destructive_mode_is_409(client):
    """Destructive modda eşleme hiç yazılmadı — geri alma fiziksel olarak mümkün değil."""
    doc = _upload(client, ["Sayın Kemal Vardar toplantıya katıldı."], data={"mode": "destructive"})
    r = client.post(f"/api/review/{doc['id']}/unmask", json={"token": "<PERSON_1>"})
    assert r.status_code == 409, r.text


# --- Faz 4: redact'in üç hatası ---

def test_redact_appends_an_iteration_record(client):
    """HATA 3 regresyonu: elle karartma denetim izine girmeliydi, girmiyordu."""
    doc = _upload(client, ["Sıradan bir metin burada."])
    doc_id = doc["id"]
    before = len(client.get(f"/api/documents/{doc_id}").json()["iterations"])
    r = client.post(f"/api/review/{doc_id}/redact", json={"terms": ["burada"]})
    assert r.status_code == 200, r.text
    after = len(client.get(f"/api/documents/{doc_id}").json()["iterations"])
    assert after == before + 1


def test_redact_keeps_the_allow_list_applied(client):
    """HATA 2 regresyonu: `redact` allow-list'i düşürünce "Genel Kurul" gibi allow'lu terimler
    yeniden maskeleniyordu."""
    doc = _upload(client, ["Genel Kurul toplantısı yapıldı.", "Karartılacak metin: HEDEFTERIM"])
    doc_id = doc["id"]
    r = client.post(f"/api/review/{doc_id}/redact", json={"terms": ["HEDEFTERIM"]})
    assert r.status_code == 200, r.text
    client.post(f"/api/review/{doc_id}/approve")
    text = client.get(f"/api/documents/{doc_id}/anonymized").text
    assert "HEDEFTERIM" not in text          # istenen karartma uygulandı
    assert "Genel Kurul" in text             # allow-list hâlâ yürürlükte
