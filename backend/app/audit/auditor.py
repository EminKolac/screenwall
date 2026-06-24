"""Privacy auditor: builds the prompt, calls a LOCAL provider, parses strict JSON (fail-closed).

The auditor must never de-anonymize or guess hidden values — it only reports residual privacy
risk. See AUDITOR_SYSTEM_PROMPT.
"""
from __future__ import annotations

from app.audit.base import LLMAuditProvider
from app.models.findings import AuditResult

AUDITOR_SYSTEM_PROMPT = """\
You are a privacy auditor.

Your task is NOT to reconstruct hidden information.

Your task is ONLY to identify whether personally identifiable information (PII), confidential
information, or sensitive data remains in the anonymized document.

The document may contain Turkish content, English content, or mixed Turkish-English content.

Inspect for: names, organizations, addresses, phone numbers, emails, government IDs, tax numbers,
passport numbers, IBANs, vehicle plates, medical information, financial information, and any data
that may identify a person.

Return JSON only. Expected JSON schema:
{
  "approved": true,
  "risk_level": "low",
  "remaining_sensitive_items": [],
  "summary": "",
  "recommended_next_action": "approve"
}

Never deanonymize. Never guess hidden information. Only report remaining privacy risks.
"""


class PrivacyAuditor:
    def __init__(self, provider: LLMAuditProvider) -> None:
        self.provider = provider

    def audit(self, anonymized_text: str) -> AuditResult:
        if not self.provider.is_available():
            return AuditResult.fail_closed(f"auditor provider '{self.provider.name}' unavailable")
        user_prompt = (
            "Audit the following ANONYMIZED document for any remaining sensitive data. "
            "Return JSON only.\n\n=== BEGIN DOCUMENT ===\n"
            f"{anonymized_text}\n=== END DOCUMENT ==="
        )
        try:
            raw = self.provider.complete(AUDITOR_SYSTEM_PROMPT, user_prompt)
        except Exception as e:  # noqa: BLE001 — fail closed on any provider error
            return AuditResult.fail_closed(f"provider error: {type(e).__name__}")
        return AuditResult.parse_llm_json(raw)
