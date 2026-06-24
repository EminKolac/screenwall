"""Deterministic heuristic privacy auditor — the always-on backstop.

Re-scans the ANONYMIZED text (after stripping placeholder tokens) for residual PII using both
hard patterns (email/IBAN/card/long-digit/valid-TCKN) that must NEVER remain, and Presidio NER
for residual names/orgs/locations. Independent of any LLM, so the iteration loop is fully
functional offline and the Qwen layer (when enabled) is additive, not required.
"""
from __future__ import annotations

import re

from app.anonymization.nlp import get_analyzer
from app.anonymization.recognizers.turkish import valid_tckn
from app.models.findings import AuditResult, NextAction, RiskLevel, SensitiveItem

_PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
_HARD_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\bTR\d{2}(?:[ ]?\d){22}\b", re.IGNORECASE)),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("LONG_DIGITS", re.compile(r"\b\d{7,}\b")),
]


class HeuristicAuditor:
    name = "heuristic"

    def __init__(self, ner_threshold: float = 0.6) -> None:
        self.ner_threshold = ner_threshold

    def audit(self, anonymized_text: str) -> AuditResult:
        scan = _PLACEHOLDER.sub(" ", anonymized_text)
        items: list[SensitiveItem] = []
        raw_terms: list[str] = []

        for label, pat in _HARD_PATTERNS:
            for m in pat.finditer(scan):
                value = m.group().strip()
                items.append(SensitiveItem(type=label, snippet=value))
                raw_terms.append(value)

        try:
            analyzer = get_analyzer()
            for lang in ("en", "tr"):
                for r in analyzer.analyze(
                    text=scan, language=lang, score_threshold=self.ner_threshold,
                    entities=["PERSON", "LOCATION", "ORGANIZATION"],
                ):
                    value = scan[r.start:r.end].strip()
                    if value:
                        items.append(SensitiveItem(type=r.entity_type, snippet=value))
                        raw_terms.append(value)
        except Exception:  # noqa: BLE001
            # Fail closed: if residual-PII NER cannot run, do NOT approve.
            return AuditResult.fail_closed("heuristic NER scan unavailable")

        if items:
            res = AuditResult(
                approved=False,
                risk_level=RiskLevel.high,
                remaining_sensitive_items=items[:25],
                recommended_next_action=NextAction.reanonymize,
                summary=f"{len(items)} residual item(s) found by heuristic scan",
            )
            res.raw_terms = list(dict.fromkeys(raw_terms))  # dedup, preserve order; not persisted
            return res
        return AuditResult(
            approved=True,
            risk_level=RiskLevel.low,
            recommended_next_action=NextAction.approve,
            summary="no residual PII detected by heuristic scan",
        )
