"""Fail-closed routing (review hardening A1/A2).

APPROVED needs a successful LLM audit (llm_ok True), a clean audit, nothing pending and no blocking
extraction reason. The deterministic heuristic alone never approves anything, and
`Document.audited_revision` only ever records a revision a working LLM audited.
"""
from __future__ import annotations

import httpx

from app.config import get_settings
from app.models.document import DocumentStatus
from app.pipeline.runner import run_pipeline
from app.services.deps import get_repository
from tests.conftest import TR_PARA, make_docx
from tests.fixtures.llm_auditor import CLEAN, install_llm


def _run(paragraphs: list[str] | None = None):
    return run_pipeline(make_docx(paragraphs or [TR_PARA]), "temiz.docx", get_settings(),
                        get_repository())


def _codes(doc) -> set[str]:
    return {r.code for r in doc.reasons}


def test_heuristic_only_audit_never_approves() -> None:
    doc = _run()  # tests pin AUDITOR_PROVIDER=mlx: heuristic only, llm_ok is None
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    assert "auditor_unavailable" in _codes(doc)
    assert get_repository().get_chat_context(doc.id) is None


def test_heuristic_only_audit_does_not_mark_the_revision_audited() -> None:
    doc = _run()
    assert doc.revision == 1
    assert doc.audited_revision == -1


def test_a_working_clean_llm_approves_and_marks_the_revision(monkeypatch) -> None:
    install_llm(monkeypatch, CLEAN)
    doc = _run()
    assert doc.status == DocumentStatus.APPROVED
    assert "auditor_unavailable" not in _codes(doc)
    assert doc.audited_revision == doc.revision == 1
    assert get_repository().get_chat_context(doc.id) is not None


def test_a_failed_llm_call_routes_to_review_and_leaves_the_revision_unaudited(monkeypatch):
    install_llm(monkeypatch, httpx.ReadTimeout("slow"))
    doc = _run()
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    assert "auditor_unavailable" in _codes(doc)
    assert doc.audited_revision == -1


def test_routing_does_not_depend_on_require_llm_auditor(monkeypatch) -> None:
    """require_llm_auditor stays in the config for the harness, but an LLM that is simply not
    configured is no longer a silent approval path."""
    monkeypatch.setenv("REQUIRE_LLM_AUDITOR", "false")
    get_settings.cache_clear()
    assert get_settings().require_llm_auditor is False
    doc = _run()
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
