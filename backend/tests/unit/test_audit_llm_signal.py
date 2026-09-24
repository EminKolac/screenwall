"""`AuditResult.llm_ok`: did the local LLM auditor really deliver a verdict for this audit?

Before this signal, `record_audit` added the `auditor_unavailable` reason only when the summary
started with "Fail-closed" — true when the LLM was missing at build time, false when a single
call failed mid-run (the combined auditor writes "heuristic=…; llm=flag"). No model, no network:
the provider is a fake.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.audit.auditor import PrivacyAuditor
from app.audit.factory import CompositeAuditor
from app.audit.heuristic import HeuristicAuditor
from app.config import Settings
from app.models.document import DocumentStatus
from app.models.findings import AuditResult, RiskLevel
from evaluation.llm_flag import llm_audit_counts
from tests.conftest import TR_PARA, make_docx

CLEAN = json.dumps({"approved": True, "risk_level": "low", "remaining_sensitive_items": [],
                    "summary": "", "recommended_next_action": "approve"})


class FakeProvider:
    """LLMAuditProvider stand-in: each call pops the next scripted reply (str) or error."""
    name = "fake"

    def __init__(self, *script, available: bool = True) -> None:
        self.script = list(script)
        self.available = available
        self.calls = 0

    def is_available(self) -> bool:
        return self.available

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def composite(provider: FakeProvider | None, require: bool = True) -> CompositeAuditor:
    llm = PrivacyAuditor(provider) if provider is not None else None
    return CompositeAuditor(HeuristicAuditor(), llm, RiskLevel.low, require_llm=require)


# --------------------------------------------------------------------- the signal itself

def test_a_parsed_llm_verdict_is_llm_ok_and_the_model_cannot_vouch_for_itself():
    assert AuditResult.parse_llm_json(CLEAN).llm_ok is True
    claims = json.loads(CLEAN) | {"llm_ok": False}
    assert AuditResult.parse_llm_json(json.dumps(claims)).llm_ok is True
    odd = json.loads(CLEAN) | {"llm_ok": "maybe"}  # was an ignored extra key; still is
    res = AuditResult.parse_llm_json(json.dumps(odd))
    assert res.llm_ok is True and res.is_clean_approval(RiskLevel.low)


@pytest.mark.parametrize("raw", ["not json at all", '{"approved": true, "risk_level": "extreme"}'])
def test_unparseable_llm_output_fails_closed_with_llm_ok_false(raw):
    res = AuditResult.parse_llm_json(raw)
    assert res.llm_ok is False and not res.is_clean_approval(RiskLevel.high)


def test_heuristic_only_results_carry_no_llm_signal():
    assert HeuristicAuditor().audit("temiz metin").llm_ok is None
    assert AuditResult().llm_ok is None


@pytest.mark.parametrize("provider", [
    FakeProvider(CLEAN, available=False),                  # model gone at call time
    FakeProvider(httpx.ReadTimeout("slow")),               # timeout mid-run
    FakeProvider(httpx.ConnectError("ollama died")),       # Ollama died mid-run
    FakeProvider("Sorry, I cannot help with that."),       # non-JSON answer
])
def test_a_failed_llm_call_is_llm_ok_false_and_never_approves(provider):
    res = composite(provider).audit("temiz metin")
    assert res.llm_ok is False
    assert not res.approved and not res.is_clean_approval(RiskLevel.high)
    # why the old summary-prefix check missed these: the combined summary has no prefix
    assert not res.summary.startswith("Fail-closed")


def test_llm_required_but_missing_at_build_time_is_llm_ok_false():
    res = composite(None, require=True).audit("temiz metin")
    assert res.llm_ok is False and res.summary.startswith("Fail-closed")


def test_no_llm_configured_is_llm_ok_none():
    res = composite(None, require=False).audit("temiz metin")
    assert res.llm_ok is None and res.approved  # heuristic only, as before


def test_a_working_llm_is_llm_ok_true():
    res = composite(FakeProvider(CLEAN)).audit("temiz metin")
    assert res.llm_ok is True and res.is_clean_approval(RiskLevel.low)


def test_an_llm_result_marked_failed_never_approves_even_if_it_says_approved():
    class Lying:
        def audit(self, text: str) -> AuditResult:
            return AuditResult.parse_llm_json(CLEAN).model_copy(update={"llm_ok": False})

    res = CompositeAuditor(HeuristicAuditor(), Lying(), RiskLevel.low).audit("temiz metin")
    assert res.llm_ok is False and not res.approved


# ------------------------------------------------------------ through the real pipeline

@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """run_pipeline on a clean Turkish DOCX with the auditor swapped for `composite(provider)`."""
    import app.pipeline.runner as runner
    from app.services.storage_repository import StorageDocumentRepository
    from app.storage.local import LocalStorageBackend

    settings = Settings(storage_root=tmp_path / "store", auditor_provider="ollama",
                        require_llm_auditor=True)
    repo = StorageDocumentRepository(LocalStorageBackend(settings.storage_root))
    data = make_docx([TR_PARA])

    def run(provider: FakeProvider):
        monkeypatch.setattr(runner, "build_auditor", lambda s: composite(provider))
        return runner.run_pipeline(data, "temiz.docx", settings, repo)

    return run


def _codes(doc) -> set[str]:
    return {r.code for r in doc.reasons}


def test_mid_run_llm_failure_routes_to_review_with_the_reason(pipeline):
    doc = pipeline(FakeProvider(httpx.ReadTimeout("slow")))
    assert doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    assert "auditor_unavailable" in _codes(doc)  # the old prefix check missed exactly this
    assert all(it.audit.llm_ok is False for it in doc.iterations)
    assert llm_audit_counts(doc) == {"audits": len(doc.iterations), "llm_ok": 0,
                                     "llm_failed": len(doc.iterations)}


def test_a_working_llm_approves_the_clean_document(pipeline):
    doc = pipeline(FakeProvider(CLEAN))
    assert doc.status == DocumentStatus.APPROVED
    assert "auditor_unavailable" not in _codes(doc)
    assert llm_audit_counts(doc) == {"audits": 1, "llm_ok": 1, "llm_failed": 0}


def test_a_transient_failure_stays_visible_in_the_counts(pipeline):
    """Iteration 1 fails, iteration 2 answers: the final audit is valid (approved, no reason),
    but the per-document counts still show the failed call, so a scorecard can refuse it."""
    doc = pipeline(FakeProvider(httpx.ReadTimeout("slow"), CLEAN))
    assert doc.status == DocumentStatus.APPROVED
    assert "auditor_unavailable" not in _codes(doc)
    assert llm_audit_counts(doc) == {"audits": 2, "llm_ok": 1, "llm_failed": 1}


def test_heuristic_only_pipeline_counts_audits_without_llm(tmp_path, monkeypatch):
    import app.pipeline.runner as runner
    from app.services.storage_repository import StorageDocumentRepository
    from app.storage.local import LocalStorageBackend

    settings = Settings(storage_root=tmp_path / "store", auditor_provider="mlx")
    repo = StorageDocumentRepository(LocalStorageBackend(settings.storage_root))
    doc = runner.run_pipeline(make_docx([TR_PARA]), "temiz.docx", settings, repo)
    assert llm_audit_counts(doc) == {"audits": 1, "llm_ok": 0, "llm_failed": 0}
    assert "auditor_unavailable" not in _codes(doc)
