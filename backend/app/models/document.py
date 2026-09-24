"""Document domain model + processing state machine.

Codex Phase-1 review fixes:
- Status enum values are machine-stable codes; UI labels live in the frontend (copy/tr.ts).
- `transition()` centralizes status changes and bumps `updated_at` (LOW).
- `chat_enabled` documents that the *runtime* gate (persisted approval + chat-context artifact)
  is enforced by `chat.service.ChatService`; this property is a necessary, not sufficient, check.

Mapping tables (placeholder↔original) are never part of any model serialized to clients.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.findings import AuditResult

# Reason a pre-v2 document stored mid-iteration carries after loading (reasons.REVIEW_REASONS).
LEGACY_STATUS_TEXT = "Bu belge eski bir sürümde işlenmişti; yeniden yükleyin."
# 2: `audited_revision` counts only SUCCESSFUL LLM audits (review hardening). Before it, a
# heuristic-only audit set it too, so a document stored without the field is not LLM-audited.
AUDIT_SCHEME = 2


class Language(str, Enum):
    tr = "tr"
    en = "en"
    mixed = "mixed"
    unknown = "unknown"


class DocumentStatus(str, Enum):
    """Fixed processing states. Stored values are machine-stable: the ones that existed before v2
    ("uploaded", "extracted", "approved", "needs_human_review") keep their values so stored
    documents and evaluation reports stay readable. The API exposes contract names (api_value)."""
    QUEUED = "queued"
    UPLOADED = "uploaded"  # legacy initial state, shown as "queued"
    EXTRACTED = "extracted"  # legacy: extraction finished, shown as "extracting"
    MASKING = "masking"
    AUDITING = "auditing"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    NEEDS_REVIEW = "needs_human_review"  # alias with the contract's name
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"

    @property
    def api_value(self) -> str:
        return _API_VALUES.get(self, self.value)

    @property
    def processing(self) -> bool:
        return self in _PROCESSING

    @property
    def busy(self) -> bool:
        """The worker is extracting, masking or auditing it right now (a queued document is not
        busy yet: it may still be deleted, and the worker then skips it)."""
        return self in _BUSY


_API_VALUES: dict[DocumentStatus, str] = {
    DocumentStatus.UPLOADED: "queued",
    DocumentStatus.EXTRACTED: "extracting",
    DocumentStatus.NEEDS_HUMAN_REVIEW: "needs_review",
}

_PROCESSING = frozenset({DocumentStatus.QUEUED, DocumentStatus.UPLOADED, DocumentStatus.EXTRACTED,
                         DocumentStatus.MASKING, DocumentStatus.AUDITING})
_BUSY = frozenset({DocumentStatus.EXTRACTED, DocumentStatus.MASKING, DocumentStatus.AUDITING})

# Pre-v2 per-iteration states ("presidio_pass_<n>", "qwen_audit_<n>"). A stored document still in
# one of them was interrupted mid-run; it cannot resume in place.
_LEGACY_PREFIXES = ("presidio_pass_", "qwen_audit_")


def _legacy_to_failed(data: dict) -> dict:
    """A legacy per-iteration status loads as FAILED with the `legacy_status` reason."""
    reasons = [r for r in _as_list(data.get("reasons")) if _code(r) != "legacy_status"]
    texts = [t for t in _as_list(data.get("review_reason")) if t != LEGACY_STATUS_TEXT]
    return {**data, "status": DocumentStatus.FAILED.value,
            "reasons": [*reasons, {"code": "legacy_status", "text": LEGACY_STATUS_TEXT}],
            "review_reason": [*texts, LEGACY_STATUS_TEXT]}


def _code(reason: object) -> object:
    return reason.get("code") if isinstance(reason, dict) else getattr(reason, "code", None)


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def upgrade_stored(data: object) -> object:
    """A document.json stored before AUDIT_SCHEME: its audited_revision may come from a
    heuristic-only audit, so it no longer counts — approval re-audits it with the LLM."""
    if isinstance(data, dict) and data.get("audit_scheme") != AUDIT_SCHEME:
        return {**data, "audited_revision": -1, "audited_digest": "",
                "audit_scheme": AUDIT_SCHEME}
    return data


class ReviewReason(BaseModel):
    """Why a document waits for a human or failed: a stable code plus a Turkish sentence."""
    code: str
    text: str


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IterationRecord(BaseModel):
    iteration: int
    presidio_entities: int = 0
    placeholders_used: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)  # masked spans per detection stage
    audit: AuditResult | None = None
    created_at: datetime = Field(default_factory=_now)


class FileKind(str, Enum):
    pdf = "pdf"
    docx = "docx"
    xlsx = "xlsx"


class Document(BaseModel):
    id: str
    filename: str
    kind: FileKind
    language: Language = Language.unknown
    status: DocumentStatus = DocumentStatus.UPLOADED
    # "mapping" (reversible, today's behaviour) vs "destructive" (irreversible — original/mapping
    # never persisted). See Settings.anonymization_mode for the full contract.
    mode: Literal["mapping", "destructive"] = "mapping"
    # Belge NEDEN insan incelemesine düştü. Çıkarma aşamasında hesaplanıp atılıyordu; artık
    # saklanıyor, çünkü gözden geçiren kişi gerekçeyi görmeden karar veremez. PII taşımaz —
    # yalnız sabit uyarı kodlarından türetilmiş insan-okur cümleler.
    review_reason: list[str] = Field(default_factory=list)
    # Same reasons with stable machine codes (the API exposes these; review_reason stays for
    # older readers). Filled through add_reason().
    reasons: list[ReviewReason] = Field(default_factory=list)
    reject_reason: str = ""
    page_count: int | None = None
    # Identifies the review state (masked content, spans, findings); bumped by every
    # re-anonymization and whenever a re-audit replaces the findings. Span and item ids are
    # positional, so clients send it back (expected_revision) and a stale one is refused.
    revision: int = 0
    # The revision a SUCCESSFUL LLM audit (llm_ok True) covered; -1 when none did. Heuristic-only
    # audits never set it. Approval re-audits whenever it differs from `revision`.
    audited_revision: int = -1
    # sha256 of the masked text that audit read: approval re-audits unless the stored layer 3 is
    # exactly that text, whatever the revision bookkeeping says (a crash mid-write included).
    audited_digest: str = ""
    audit_scheme: int = AUDIT_SCHEME  # see upgrade_stored
    # Cached counts so the document list never has to open layer-3 files.
    masked_count: int = 0
    pending_count: int = 0
    iterations: list[IterationRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @model_validator(mode="before")
    @classmethod
    def _legacy_status(cls, data: object) -> object:
        status = data.get("status") if isinstance(data, dict) else None
        if isinstance(status, str) and status.startswith(_LEGACY_PREFIXES):
            return _legacy_to_failed(data)
        return data

    def transition(self, new_status: DocumentStatus) -> None:
        """Single place that changes status, so timestamps/audit hooks stay consistent."""
        self.status = new_status
        self.updated_at = _now()

    def add_reason(self, code: str, text: str) -> None:
        if any(r.code == code for r in self.reasons):
            return
        self.reasons.append(ReviewReason(code=code, text=text))
        if text not in self.review_reason:
            self.review_reason.append(text)

    def drop_reasons(self, *codes: str) -> None:
        """Remove the reasons with these codes; `review_reason` is rebuilt from what remains."""
        self.reasons = [r for r in self.reasons if r.code not in codes]
        self.review_reason = [r.text for r in self.reasons]

    @property
    def approved(self) -> bool:
        return self.status == DocumentStatus.APPROVED

    @property
    def chat_enabled(self) -> bool:
        # Necessary condition only. ChatService additionally verifies persisted approval and the
        # existence of an approved chat-context artifact before any external provider call.
        return self.status == DocumentStatus.APPROVED
