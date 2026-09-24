"""Auditor assembly: deterministic heuristic backstop ALWAYS runs; the local Qwen LLM auditor is
added when Ollama is reachable. Approval requires BOTH to be CLEAN (defense in depth).

Codex review: the LLM must pass the full clean-approval predicate (not just `approved=true`), and
`require_llm_auditor` removes the silent fail-open when Ollama is down.

Every combined result carries `llm_ok`: None when no LLM is configured (heuristic only), False
when the LLM was required but missing or its call failed (the result is then never an approval),
True when the LLM answered. A per-call failure keeps no "Fail-closed" summary prefix here, so
callers must read `llm_ok`, not the summary.

An endpoint security/ollama.py refuses (a remote OLLAMA_BASE_URL without `ollama_allow_remote`,
an Ollama cloud model) is treated as a REQUIRED LLM that is unavailable: it is never contacted and
every audit fails closed, whatever `require_llm_auditor` says.
"""
from __future__ import annotations

import logging

from app.audit.auditor import PrivacyAuditor
from app.audit.heuristic import HeuristicAuditor
from app.audit.ollama_provider import OllamaProvider
from app.config import Settings
from app.models.findings import AuditResult, NextAction, RiskLevel

logger = logging.getLogger(__name__)

_RISK_ORDER = {RiskLevel.low: 0, RiskLevel.medium: 1, RiskLevel.high: 2}


class CompositeAuditor:
    name = "composite"

    def __init__(
        self,
        heuristic: HeuristicAuditor,
        llm: PrivacyAuditor | None,
        max_risk: RiskLevel,
        require_llm: bool = False,
    ) -> None:
        self.heuristic = heuristic
        self.llm = llm
        self.max_risk = max_risk
        self.require_llm = require_llm

    def audit(self, anonymized_text: str) -> AuditResult:
        h = self.heuristic.audit(anonymized_text)
        if self.llm is None:
            if self.require_llm:
                return AuditResult.fail_closed("LLM auditor required but unavailable")
            return h
        ll = self.llm.audit(anonymized_text)
        # PrivacyAuditor always sets llm_ok; a failed call (False) can never approve.
        llm_ok = ll.llm_ok is not False
        # Both auditors must be CLEAN (full predicate), not merely `approved=true`.
        approved = (llm_ok and h.is_clean_approval(self.max_risk)
                    and ll.is_clean_approval(self.max_risk))
        items = (h.remaining_sensitive_items + ll.remaining_sensitive_items)[:30]
        worst = max([h.risk_level, ll.risk_level], key=lambda r: _RISK_ORDER[r])
        res = AuditResult(
            approved=approved,
            risk_level=RiskLevel.low if approved else worst,
            remaining_sensitive_items=[] if approved else items,
            recommended_next_action=NextAction.approve if approved else NextAction.reanonymize,
            summary=(f"heuristic={'ok' if h.approved else 'flag'}; "
                     f"llm={'ok' if ll.approved else 'flag'}"),
            llm_ok=llm_ok,
        )
        res.raw_terms = list(dict.fromkeys([*h.raw_terms, *ll.raw_terms]))
        return res


def build_auditor(settings: Settings) -> CompositeAuditor:
    heuristic = HeuristicAuditor()
    max_risk = RiskLevel(settings.auditor_risk_approve)
    require_llm = settings.require_llm_auditor
    llm: PrivacyAuditor | None = None
    if settings.auditor_provider == "ollama":
        provider = OllamaProvider(settings.ollama_base_url, settings.auditor_model,
                                  allow_remote=settings.ollama_allow_remote)
        if provider.refusal is not None:
            # A remote host without the opt-in, or a cloud model: never contacted, and never
            # silently replaced by the heuristic alone. Built as a required-but-unavailable LLM,
            # so every audit fails closed (llm_ok=False) and the document goes to review.
            logger.warning("LLM auditor refused (%s); audits fail closed", provider.refusal)
            require_llm = True
        elif provider.is_available():
            llm = PrivacyAuditor(provider)
    return CompositeAuditor(heuristic, llm, max_risk, require_llm=require_llm)
