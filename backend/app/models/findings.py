"""Schemas for the local privacy auditor (Qwen) output.

The auditor returns JSON matching `AuditResult`. Parsing fails closed: any malformed or
schema-invalid output is treated as "not approved" and routes the document to human review.

Codex Phase-1 review fixes incorporated:
- Approval is NOT just `approved == true`; use `is_clean_approval()` (CRITICAL).
- `SensitiveItem.snippet` is capped + minimally redacted at the model boundary so validation
  reports stay PII-safe (CRITICAL).
- JSON extraction is string-aware (ignores braces inside string literals) (MEDIUM).
"""
from __future__ import annotations

import json
import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
_SNIPPET_MAX = 60


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class NextAction(str, Enum):
    approve = "approve"
    reanonymize = "reanonymize"
    human_review = "human_review"


def _mini_redact(text: str) -> str:
    """Defensive redaction for snippets stored in the validation layer (never raw PII)."""
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "<EMAIL>", text)
    text = re.sub(r"(?:\d[ -]?){6,}", "<NUM>", text)  # long digit runs (IDs, IBANs, cards)
    return text


class SensitiveItem(BaseModel):
    """A residual sensitive item reported by the auditor. Describes the *type* and a short,
    redacted hint/location only — never reconstructed PII."""
    model_config = ConfigDict(extra="ignore")

    type: str = "UNKNOWN"
    snippet: str = ""
    location: str = ""
    note: str = ""

    @field_validator("snippet")
    @classmethod
    def _safe_snippet(cls, v: str) -> str:
        # Store only a non-identifying length hint — never raw content (raw lives in raw_terms,
        # which is excluded from serialization). Keeps the validation layer & API PII-safe.
        n = len(v.strip())
        return f"‹{n} chars›" if n else ""


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    approved: bool = False
    risk_level: RiskLevel = RiskLevel.high
    remaining_sensitive_items: list[SensitiveItem] = Field(default_factory=list)
    summary: str = ""
    recommended_next_action: NextAction = NextAction.human_review
    # Raw residual strings for re-anonymization feedback. Excluded from serialization/logs so the
    # validation layer stays PII-safe; lives only in-memory during the iteration loop.
    raw_terms: list[str] = Field(default_factory=list, exclude=True, repr=False)

    def is_clean_approval(self, max_risk: RiskLevel) -> bool:
        """Approval requires ALL invariants — not just `approved` (CRITICAL fix)."""
        return (
            self.approved
            and self.recommended_next_action == NextAction.approve
            and not self.remaining_sensitive_items
            and _RISK_ORDER[self.risk_level.value] <= _RISK_ORDER[max_risk.value]
        )

    @classmethod
    def fail_closed(cls, reason: str) -> "AuditResult":
        return cls(
            approved=False,
            risk_level=RiskLevel.high,
            summary=f"Fail-closed: {reason}",
            recommended_next_action=NextAction.human_review,
        )

    @classmethod
    def parse_llm_json(cls, raw: str) -> "AuditResult":
        obj = _extract_first_json_object(raw)
        if obj is None:
            return cls.fail_closed("no JSON object in auditor output")
        # Capture raw snippets BEFORE validation redacts them — needed for re-anonymization.
        raw_items = obj.get("remaining_sensitive_items") or []
        raw_terms = [
            it["snippet"] for it in raw_items
            if isinstance(it, dict) and isinstance(it.get("snippet"), str) and it["snippet"].strip()
        ]
        try:
            result = cls.model_validate(obj)
        except ValidationError as e:
            return cls.fail_closed(f"schema validation error: {e.error_count()} issue(s)")
        result.raw_terms = raw_terms
        return result


def _extract_first_json_object(raw: str) -> dict | None:
    """Return the first balanced top-level JSON object, ignoring braces inside strings."""
    start = raw.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None
