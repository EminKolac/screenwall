"""Deterministic heuristic privacy auditor — the always-on, offline backstop.

Re-scans the ANONYMIZED text (placeholder tokens stripped) for residual PII using ONLY
high-confidence, deterministic patterns that must never remain: email, Turkish IBAN, credit-card
runs, valid-checksum TCKN, and prefixed Turkish phone numbers.

It deliberately does NOT re-run NER for names/orgs/locations. The anonymization engine already
applies the same NER at a LOWER (more aggressive) threshold, so a second NER pass here catches
nothing new — it only adds false positives (ordinary capitalized phrases like "File Name"/"Tax
Structure", table artifacts, concatenation boundaries) that push every real document to `high`
risk and never converge (each iteration surfaces different phantom "entities"). With deterministic
patterns the iteration loop converges: a real residual is fed back as a deny-term, masked, and then
approved. Semantic residuals are the optional LLM auditor's job; anything uncertain → human review.
"""
from __future__ import annotations

import re

from app.anonymization.recognizers.turkish import valid_tckn
from app.models.findings import AuditResult, NextAction, RiskLevel, SensitiveItem

_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
# High-confidence, low-false-positive residual-PII patterns (must never survive anonymization).
_HARD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\bTR\d{2}(?:[ ]?\d){22}\b", re.IGNORECASE)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # Turkish phone: require a 0 / +90 prefix so bare financial figures aren't flagged.
    ("TR_PHONE", re.compile(r"\b(?:\+?90[ ]?|0)5\d{2}[\s.\-]?\d{3}[\s.\-]?\d{2}[\s.\-]?\d{2}\b")),
]
_TCKN_CANDIDATE = re.compile(r"\b\d{11}\b")  # validated by checksum below (no bare-number flagging)


class HeuristicAuditor:
    name = "heuristic"

    def audit(self, anonymized_text: str) -> AuditResult:
        scan = _PLACEHOLDER.sub(" ", anonymized_text)
        items: list[SensitiveItem] = []
        raw_terms: list[str] = []

        def flag(label: str, value: str) -> None:
            value = value.strip()
            if value:
                items.append(SensitiveItem(type=label, snippet=value))
                raw_terms.append(value)

        for label, pat in _HARD_PATTERNS:
            for m in pat.finditer(scan):
                flag(label, m.group())
        for m in _TCKN_CANDIDATE.finditer(scan):
            if valid_tckn(m.group()):
                flag("TR_TCKN", m.group())

        if items:
            res = AuditResult(
                approved=False,
                risk_level=RiskLevel.high,
                remaining_sensitive_items=items[:25],
                recommended_next_action=NextAction.reanonymize,
                summary=f"{len(items)} residual item(s) found by heuristic scan",
            )
            res.raw_terms = list(dict.fromkeys(raw_terms))  # dedup, order-preserving; not persisted
            return res
        return AuditResult(
            approved=True,
            risk_level=RiskLevel.low,
            recommended_next_action=NextAction.approve,
            summary="no residual PII detected by heuristic scan",
        )
