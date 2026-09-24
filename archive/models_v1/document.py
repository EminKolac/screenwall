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

from pydantic import BaseModel, Field

from app.models.findings import AuditResult


class Language(str, Enum):
    tr = "tr"
    en = "en"
    mixed = "mixed"
    unknown = "unknown"


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    EXTRACTED = "extracted"
    PRESIDIO_PASS_1 = "presidio_pass_1"
    QWEN_AUDIT_1 = "qwen_audit_1"
    PRESIDIO_PASS_2 = "presidio_pass_2"
    QWEN_AUDIT_2 = "qwen_audit_2"
    APPROVED = "approved"
    NEEDS_HUMAN_REVIEW = "needs_human_review"

    @property
    def display(self) -> str:
        return _DISPLAY_LABELS[self]


_DISPLAY_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.UPLOADED: "Yüklendi",
    DocumentStatus.EXTRACTED: "Çıkarıldı",
    DocumentStatus.PRESIDIO_PASS_1: "Maskeleme 1",
    DocumentStatus.QWEN_AUDIT_1: "Denetim 1",
    DocumentStatus.PRESIDIO_PASS_2: "Maskeleme 2",
    DocumentStatus.QWEN_AUDIT_2: "Denetim 2",
    DocumentStatus.APPROVED: "Onaylandı",
    DocumentStatus.NEEDS_HUMAN_REVIEW: "İnceleme bekliyor",
}


def presidio_pass_status(iteration: int) -> DocumentStatus:
    return DocumentStatus[f"PRESIDIO_PASS_{iteration}"]


def qwen_audit_status(iteration: int) -> DocumentStatus:
    return DocumentStatus[f"QWEN_AUDIT_{iteration}"]


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

    def transition(self, new_status: DocumentStatus) -> None:
        """Single place that changes status, so timestamps/audit hooks stay consistent."""
        self.status = new_status
        self.updated_at = _now()

    @property
    def approved(self) -> bool:
        return self.status == DocumentStatus.APPROVED

    @property
    def chat_enabled(self) -> bool:
        # Necessary condition only. ChatService additionally verifies persisted approval and the
        # existence of an approved chat-context artifact before any external provider call.
        return self.status == DocumentStatus.APPROVED
