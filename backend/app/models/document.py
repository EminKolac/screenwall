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
    PRESIDIO_PASS_3 = "presidio_pass_3"
    QWEN_AUDIT_3 = "qwen_audit_3"
    APPROVED = "approved"
    NEEDS_HUMAN_REVIEW = "needs_human_review"

    @property
    def display(self) -> str:
        return _DISPLAY_LABELS[self]


_DISPLAY_LABELS: dict[DocumentStatus, str] = {
    DocumentStatus.UPLOADED: "Uploaded",
    DocumentStatus.EXTRACTED: "Extracted",
    DocumentStatus.PRESIDIO_PASS_1: "Presidio Pass 1",
    DocumentStatus.QWEN_AUDIT_1: "Qwen Audit 1",
    DocumentStatus.PRESIDIO_PASS_2: "Presidio Pass 2",
    DocumentStatus.QWEN_AUDIT_2: "Qwen Audit 2",
    DocumentStatus.PRESIDIO_PASS_3: "Presidio Pass 3",
    DocumentStatus.QWEN_AUDIT_3: "Qwen Audit 3",
    DocumentStatus.APPROVED: "Approved",
    DocumentStatus.NEEDS_HUMAN_REVIEW: "Needs Human Review",
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
    current_iteration: int = 0
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
