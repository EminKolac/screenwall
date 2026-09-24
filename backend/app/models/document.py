"""Document domain model + processing state machine.

Codex Phase-1 review fixes:
- Status enum values are machine-stable codes; UI labels are a separate display map (LOW).
- `transition()` centralizes status changes and bumps `updated_at` (LOW).
- `chat_enabled` documents that the *runtime* gate (persisted approval + chat-context artifact)
  is enforced by `chat.service.ChatService`; this property is a necessary, not sufficient, check.

Mapping tables (placeholder↔original) are never part of any model serialized to clients.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.findings import AuditResult


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
    def display(self) -> str:
        return _DISPLAY_LABELS[self]

    @property
    def api_value(self) -> str:
        return _API_VALUES.get(self, self.value)

    @property
    def processing(self) -> bool:
        return self in _PROCESSING


_DISPLAY_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.QUEUED: "Sırada",
    DocumentStatus.UPLOADED: "Sırada",
    DocumentStatus.EXTRACTED: "Çıkarılıyor",
    DocumentStatus.MASKING: "Maskeleniyor",
    DocumentStatus.AUDITING: "Denetleniyor",
    DocumentStatus.NEEDS_HUMAN_REVIEW: "İnceleme bekliyor",
    DocumentStatus.APPROVED: "Onaylandı",
    DocumentStatus.REJECTED: "Reddedildi",
    DocumentStatus.FAILED: "İşlenemedi",
}

_API_VALUES: dict[DocumentStatus, str] = {
    DocumentStatus.UPLOADED: "queued",
    DocumentStatus.EXTRACTED: "extracting",
    DocumentStatus.NEEDS_HUMAN_REVIEW: "needs_review",
}

_PROCESSING = frozenset({DocumentStatus.QUEUED, DocumentStatus.UPLOADED, DocumentStatus.EXTRACTED,
                         DocumentStatus.MASKING, DocumentStatus.AUDITING})

# Pre-v2 per-iteration states. A stored document still in one of them was interrupted mid-run.
_LEGACY_TRANSIENT = {"presidio_pass_1", "qwen_audit_1", "presidio_pass_2", "qwen_audit_2",
                     "presidio_pass_3", "qwen_audit_3"}


def presidio_pass_status(iteration: int) -> DocumentStatus:
    """Kept for callers of the old loop; every masking iteration is now the same state."""
    return DocumentStatus.MASKING


def qwen_audit_status(iteration: int) -> DocumentStatus:
    return DocumentStatus.AUDITING


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
    current_iteration: int = 0
    # Belge NEDEN insan incelemesine düştü. Çıkarma aşamasında hesaplanıp atılıyordu; artık
    # saklanıyor, çünkü gözden geçiren kişi gerekçeyi görmeden karar veremez. PII taşımaz —
    # yalnız sabit uyarı kodlarından türetilmiş insan-okur cümleler.
    review_reason: list[str] = Field(default_factory=list)
    # Same reasons with stable machine codes (the API exposes these; review_reason stays for
    # older readers). Filled through add_reason().
    reasons: list[ReviewReason] = Field(default_factory=list)
    reject_reason: str = ""
    page_count: int | None = None
    # Bumped by every re-anonymization; the review screen and approval use it to notice changes.
    revision: int = 0
    # The LLM audit last ran on this revision (approval re-audits when it is stale).
    audited_revision: int = -1
    # Cached counts so the document list never has to open layer-3 files.
    masked_count: int = 0
    pending_count: int = 0
    # Faz 3 — insan düzeltmesi. Bir gözden geçiren "bu maskeleme yanlıştı" dediğinde, geri alınan
    # DEĞER buraya yazılır ve belge yeniden anonimleştirilirken allow-list'e eklenir. Böylece
    # düzeltme kalıcıdır: aynı terim sonraki iterasyonlarda tekrar maskelenmez.
    #
    # Bu alan ham (maskelenmemiş) metin taşır — yalnızca insanın açıkça "bu PII değil" dediği
    # terimler girer, dolayısıyla tanım gereği PII DEĞİLDİR. Yine de dışa açık yüzeylere sızmaması
    # için `exclude=True`: API yanıtlarında ve layer-5 bağlamında görünmez (eşleme tablosunun
    # `AnonymizationOutput.mapping` üzerindeki korumasıyla aynı desen).
    allow_terms: list[str] = Field(default_factory=list, exclude=True)
    iterations: list[IterationRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("status", mode="before")
    @classmethod
    def _legacy_status(cls, value: object) -> object:
        # A pre-v2 document stored mid-iteration was interrupted; it cannot resume in place.
        if isinstance(value, str) and value in _LEGACY_TRANSIENT:
            return DocumentStatus.FAILED.value
        return value

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

    def clear_reasons(self) -> None:
        self.reasons = []
        self.review_reason = []

    @property
    def approved(self) -> bool:
        return self.status == DocumentStatus.APPROVED

    @property
    def chat_enabled(self) -> bool:
        # Necessary condition only. ChatService additionally verifies persisted approval and the
        # existence of an approved chat-context artifact before any external provider call.
        return self.status == DocumentStatus.APPROVED
