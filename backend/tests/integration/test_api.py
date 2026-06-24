from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_health():
    assert client.get("/health").status_code == 200


def test_statuses_have_value_and_label():
    body = client.get("/api/statuses").json()
    assert {"value", "label"} <= set(body["statuses"][0].keys())
    assert len(body["statuses"]) == 10


def test_upload_runs_full_pipeline(docx_en):
    r = client.post("/api/documents", files={"file": ("a.docx", docx_en, _DOCX_MIME)})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["language"] == "en"
    assert j["status"] == "approved"  # fully maskable content
    assert j["approved"] is True and j["chat_enabled"] is True
    r2 = client.get(f"/api/documents/{j['id']}")
    assert r2.status_code == 200
    assert r2.json()["language"] == "en"


def test_upload_rejects_bad_file():
    r = client.post("/api/documents", files={"file": ("a.pdf", b"nope", "application/pdf")})
    assert r.status_code == 400
