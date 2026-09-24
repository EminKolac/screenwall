"""A scripted local LLM auditor for tests: no Ollama, no network.

`install_llm(monkeypatch, *replies)` swaps `app.pipeline.runner.build_auditor` (the single lookup
used by the pipeline AND by approval's re-audit) for the REAL CompositeAuditor — heuristic plus
LLM — whose provider answers from a script. A reply is a JSON string or an exception to raise; the
last reply repeats. Fixtures: `llm_clean` (every audit answers clean, llm_ok=True) and `llm_down`
(the provider is unavailable, llm_ok=False).

Use from a test module with an explicit import (conftest.py is not touched):

    from tests.fixtures.llm_auditor import llm_clean  # noqa: F401
"""
from __future__ import annotations

import json

import pytest

from app.audit.auditor import PrivacyAuditor
from app.audit.factory import CompositeAuditor
from app.audit.heuristic import HeuristicAuditor
from app.models.findings import RiskLevel

CLEAN = json.dumps({"approved": True, "risk_level": "low", "remaining_sensitive_items": [],
                    "summary": "", "recommended_next_action": "approve"})


def residual(*snippets: str) -> str:
    """An LLM verdict that reports each snippet as residual personal data."""
    return json.dumps({
        "approved": False, "risk_level": "high", "summary": "",
        "remaining_sensitive_items": [{"type": "PERSON", "snippet": s} for s in snippets],
        "recommended_next_action": "reanonymize",
    })


class ScriptedProvider:
    """LLMAuditProvider stand-in. Records every audited text in `texts`."""
    name = "scripted"

    def __init__(self, replies: tuple, available: bool = True) -> None:
        self.replies = list(replies)
        self.available = available
        self.texts: list[str] = []
        self.on_call = None  # optional side effect, called with the audited text

    @property
    def calls(self) -> int:
        return len(self.texts)

    def is_available(self) -> bool:
        return self.available

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        text = user_prompt.split("=== BEGIN DOCUMENT ===\n", 1)[-1]
        self.texts.append(text.rsplit("\n=== END DOCUMENT ===", 1)[0])
        if self.on_call is not None:
            self.on_call(self.texts[-1])
        step = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(step, BaseException):
            raise step
        return step


def install_llm(monkeypatch, *replies, available: bool = True) -> ScriptedProvider:
    import app.pipeline.runner as runner

    provider = ScriptedProvider(replies or (CLEAN,), available)

    def build(settings) -> CompositeAuditor:
        return CompositeAuditor(HeuristicAuditor(), PrivacyAuditor(provider),
                                RiskLevel(settings.auditor_risk_approve), require_llm=True)

    monkeypatch.setattr(runner, "build_auditor", build)
    return provider


@pytest.fixture
def llm_clean(monkeypatch) -> ScriptedProvider:
    return install_llm(monkeypatch, CLEAN)


@pytest.fixture
def llm_down(monkeypatch) -> ScriptedProvider:
    return install_llm(monkeypatch, CLEAN, available=False)
