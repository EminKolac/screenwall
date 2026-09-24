"""Schemas for the local privacy auditor (Qwen) output.

The auditor returns JSON matching `AuditResult`. Parsing fails closed: any malformed or
schema-invalid output is treated as "not approved" and routes the document to human review.

Codex Phase-1 review fixes incorporated:
- Approval is NOT just `approved == true`; use `is_clean_approval()` (CRITICAL).
- `SensitiveItem.snippet` is capped + minimally redacted at the model boundary so validation
  reports stay PII-safe (CRITICAL). Its free-text siblings are too: `note` is dropped, `location`
  keeps a bare page number, `type` a known label (security review, destructive mode).
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


# Residual types an item may name: the engine's detector types and families
# (anonymization/types.py), the heuristic's labels, and the usual words an LLM uses for them.
# Anything else is "UNKNOWN": a model-invented type ("PERSON: Ahmet Yılmaz") is free text.
_ITEM_TYPES = frozenset({
    "ACCOUNT", "ACCOUNT_NUMBER", "ADDRESS", "API_KEY", "BANK_ACCOUNT", "CARD", "COMPANY",
    "CONFIDENTIAL", "CREDENTIAL", "CREDIT_CARD", "DATE", "DATE_OF_BIRTH", "DATE_TIME", "DL",
    "DRIVER_LICENSE", "EMAIL", "EMAIL_ADDRESS", "FINANCIAL", "GOVERNMENT_ID", "HEALTH", "IBAN",
    "IBAN_CODE", "ID", "ID_NUMBER", "IP", "IP_ADDRESS", "LICENSE_PLATE", "LOCATION", "MEDICAL",
    "NAME", "NATIONAL_ID", "NRP", "ORG", "ORGANIZATION", "PASSPORT", "PASSPORT_NUMBER",
    "PASSWORD", "PERSON", "PHONE", "PHONE_NUMBER", "PLATE", "SALARY", "SECRET", "SECRET_KEY",
    "SENSITIVE", "SSN", "TAX_ID", "TAX_NUMBER", "TCKN", "TR_ACCOUNT", "TR_ADDRESS", "TR_COMPANY",
    "TR_DISABILITY", "TR_GSM", "TR_HEALTH", "TR_IBAN", "TR_PASSPORT", "TR_PERSON_CTX",
    "TR_PHONE", "TR_PLATE", "TR_SALARY_BAND", "TR_TCKN", "TR_VKN", "UK_PHONE", "UNKNOWN", "URL",
    "US_DRIVER_LICENSE", "US_SSN", "USERNAME", "VEHICLE_PLATE", "VKN",
})
# "page 2", "sayfa 2", "p. 2": the only location kept — a bare, short page number.
_PAGE_REF = re.compile(r"\b(?:page|sayfa|p\.|s\.)\s*(\d{1,4})(?!\d)", re.IGNORECASE)
_LENGTH_HINT = re.compile(r"‹\d+ chars›")


class SensitiveItem(BaseModel):
    """A residual sensitive item reported by the auditor, as stored in layer 4.

    Only non-identifying hints survive validation: a known `type`, the snippet's LENGTH and a
    bare page number. The model's free text — `note`, a descriptive `location`, an invented
    `type` — can repeat the very value it found, so it is dropped here, at the model boundary
    (the literal snippets reach the next masking pass through `AuditResult.raw_terms`, which is
    never serialized)."""
    model_config = ConfigDict(extra="ignore")

    type: str = "UNKNOWN"
    snippet: str = ""
    location: str = ""
    note: str = ""

    # "after" validators: a non-string field still fails the whole verdict closed, as before.
    @field_validator("type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        key = re.sub(r"[^A-Z0-9]+", "_", v.upper()).strip("_")
        return key if key in _ITEM_TYPES else "UNKNOWN"

    @field_validator("snippet")
    @classmethod
    def _safe_snippet(cls, v: str) -> str:
        # Store only a non-identifying length hint — never raw content (raw lives in raw_terms,
        # which is excluded from serialization). Keeps the validation layer & API PII-safe.
        if _LENGTH_HINT.fullmatch(v):  # a stored document read back keeps its hint
            return v
        n = len(v.strip())
        return f"‹{n} chars›" if n else ""

    @field_validator("location")
    @classmethod
    def _page_only(cls, v: str) -> str:
        m = _PAGE_REF.search(v)
        return f"page {int(m[1])}" if m else ""

    @field_validator("note")
    @classmethod
    def _no_free_text(cls, _v: str) -> str:
        return ""


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
    # Did the local LLM auditor deliver a verdict for THIS audit? True = it answered with valid
    # JSON; False = it was required or configured but failed (unreachable, provider error or
    # timeout, no JSON, schema-invalid) and the audit failed closed; None = no LLM configured
    # (heuristic only). Set by the auditors, never taken from the model's own output.
    llm_ok: bool | None = None

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
        """Every caller is an LLM auditor that could not deliver a verdict, hence llm_ok=False."""
        return cls(
            approved=False,
            risk_level=RiskLevel.high,
            summary=f"Fail-closed: {reason}",
            recommended_next_action=NextAction.human_review,
            llm_ok=False,
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
        obj.pop("llm_ok", None)  # the model must not vouch for itself; set below
        try:
            result = cls.model_validate(obj)
        except ValidationError as e:
            return cls.fail_closed(f"schema validation error: {e.error_count()} issue(s)")
        result.raw_terms = raw_terms
        result.llm_ok = True
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
