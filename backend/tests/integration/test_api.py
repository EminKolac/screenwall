from fastapi.testclient import TestClient

from app.main import app
from app.models.document import DocumentStatus
from tests.fixtures.llm_auditor import llm_clean  # noqa: F401 — pytest fixture

client = TestClient(app)

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_health():
    assert client.get("/health").status_code == 200


def test_status_api_values_match_the_contract():
    contract = {"queued", "extracting", "masking", "auditing", "needs_review", "approved",
                "rejected", "failed"}
    assert {s.api_value for s in DocumentStatus} == contract


def test_upload_runs_full_pipeline(docx_en, llm_clean):  # noqa: F811 — fixture parameter
    r = client.post("/api/documents", files={"file": ("a.docx", docx_en, _DOCX_MIME)})
    assert r.status_code == 202, r.text
    j = r.json()
    assert j["language"] == "en"
    assert j["status"] == "approved"  # fully maskable content, and a working LLM audited it
    assert j["can"]["chat"] is True and j["can"]["download"] is True
    r2 = client.get(f"/api/documents/{j['id']}")
    assert r2.status_code == 200
    assert r2.json()["language"] == "en"


def test_upload_rejects_bad_file():
    r = client.post("/api/documents", files={"file": ("a.pdf", b"nope", "application/pdf")})
    assert r.status_code == 400
