"""Destructive mode keeps no raw value anywhere it writes (layers 3, 4 and 5).

Layers 1-2 are never written in this mode, but three channels still carried raw text into the
layers that are: XLSX sheet titles in block ids and locations (unit ids of anonymized.json,
edits.json, findings.json and the review payload), the upload's filename in document.json, and the
LLM auditor's free-text notes in document.json. These tests walk the whole store.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.audit.auditor import PrivacyAuditor
from app.audit.factory import CompositeAuditor
from app.audit.heuristic import HeuristicAuditor
from app.config import Settings, get_settings
from app.extraction.base import kind_from_filename
from app.main import app
from app.models.document import DocumentStatus, FileKind
from app.models.findings import RiskLevel
from app.services.ingest import new_document
from tests.conftest import TR_PARA, make_docx, make_xlsx

NAME = "Ahmet Yılmaz"
NEEDLES = ("ahmet", "yılmaz", "yilmaz", "y\\u0131lmaz")
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _leaks(root: Path) -> list[str]:
    """Every (file, needle) pair where a raw value survives, case-insensitively."""
    found = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        text = path.read_bytes().decode("utf-8", "replace").casefold()
        found += [f"{path.relative_to(root)}: {n}" for n in NEEDLES if n in text]
    return found


def test_a_destructive_xlsx_leaves_no_raw_name_in_any_written_file(monkeypatch, tmp_path):
    # The name is an always-mask term so the content is masked deterministically: this test is
    # about what storage keeps next to the masked text, not about detection.
    monkeypatch.setenv("DENY_TERMS", NAME)
    get_settings.cache_clear()
    client = TestClient(app)
    data = make_xlsx([["Ad", "E-posta"], [NAME, "ahmet.yilmaz@example.com"]], sheet=NAME)
    r = client.post("/api/documents", data={"mode": "destructive"},
                    files={"file": (f"{NAME} maaş.xlsx", data, _XLSX_MIME)})
    assert r.status_code == 202, r.text
    doc = r.json()
    assert doc["mode"] == "destructive" and doc["filename"].endswith(".xlsx")
    assert not any(n in r.text.casefold() for n in NEEDLES)
    review = client.get(f"/api/documents/{doc['id']}/review")
    assert review.status_code == 200
    assert not any(n in review.text.casefold() for n in NEEDLES)
    assert _leaks(tmp_path) == []
    assert not (tmp_path / "1_original" / doc["id"]).exists()


def test_destructive_documents_keep_only_a_masked_filename(monkeypatch):
    monkeypatch.setenv("DENY_TERMS", NAME)
    get_settings.cache_clear()
    doc = new_document(f"{NAME} maaş.xlsx", FileKind.xlsx, "destructive")
    assert not any(n in doc.filename.casefold() for n in NEEDLES)
    # The worker re-derives the file type from the stored name.
    assert kind_from_filename(doc.filename) == FileKind.xlsx
    assert new_document(f"{NAME} maaş.xlsx", FileKind.xlsx, "mapping").filename == (
        f"{NAME} maaş.xlsx")


class _TalkativeLLM:
    """A local auditor that names what it found in every free-text field it has."""
    name = "fake"

    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        item = {"type": f"PERSON: {NAME}", "snippet": NAME,
                "location": f"sayfa 1, {NAME} imzası", "note": f"{NAME} açıkta kalmış"}
        return json.dumps({"approved": False, "risk_level": "high",
                           "remaining_sensitive_items": [item], "summary": NAME,
                           "recommended_next_action": "reanonymize"}, ensure_ascii=False)


def test_the_llm_auditors_free_text_never_reaches_storage(monkeypatch, tmp_path):
    import app.pipeline.runner as runner
    from app.services.storage_repository import StorageDocumentRepository
    from app.storage.local import LocalStorageBackend

    auditor = CompositeAuditor(HeuristicAuditor(), PrivacyAuditor(_TalkativeLLM()),
                               RiskLevel.low)
    monkeypatch.setattr(runner, "build_auditor", lambda _settings: auditor)
    settings = Settings(storage_root=tmp_path / "store")
    repo = StorageDocumentRepository(LocalStorageBackend(settings.storage_root))
    doc = runner.run_pipeline(make_docx([TR_PARA]), "temiz.docx", settings, repo,
                              mode="destructive")
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    assert doc.iterations and doc.iterations[-1].audit.remaining_sensitive_items
    assert _leaks(settings.storage_root) == []
