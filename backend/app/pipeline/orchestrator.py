"""Iteration loop + status state machine (Architecture.md §9).

Runs: [anonymize → audit] up to MAX_ITERATIONS. On a CLEAN approval → APPROVED; otherwise after
the last iteration → NEEDS_HUMAN_REVIEW. Returns a `PipelineResult` carrying the final anonymized
content + mapping (best-effort even when unapproved, for the human reviewer / download).

Codex review: approval uses `is_clean_approval` (not just `approved`); re-anonymization feedback
uses `audit.raw_terms` (raw, never persisted), not the redacted snippets; status changes go
through `Document.transition`; a `PersistenceHook` seam lets Phase 5 persist each step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.anonymization.engine import AnonymizationEngine
from app.config import Settings
from app.extraction.base import ExtractedContent
from app.models.document import (
    Document,
    DocumentStatus,
    IterationRecord,
    Language,
    presidio_pass_status,
    qwen_audit_status,
)
from app.models.findings import RiskLevel


class Auditor(Protocol):
    def audit(self, anonymized_text: str): ...


class PersistenceHook(Protocol):
    def on_status(self, doc: Document) -> None: ...
    def on_iteration(self, doc: Document, record: IterationRecord) -> None: ...


class _NullHook:
    def on_status(self, doc: Document) -> None: ...
    def on_iteration(self, doc: Document, record: IterationRecord) -> None: ...


@dataclass
class PipelineResult:
    document: Document
    anonymized: ExtractedContent | None
    mapping: dict[str, str]
    approved: bool


class Orchestrator:
    def __init__(
        self,
        engine: AnonymizationEngine,
        auditor: Auditor,
        settings: Settings,
        hook: PersistenceHook | None = None,
    ) -> None:
        self.engine = engine
        self.auditor = auditor
        self.max_iterations = settings.max_iterations
        self.max_risk = RiskLevel(settings.auditor_risk_approve)
        self.hook = hook or _NullHook()

    def run(
        self,
        doc: Document,
        content: ExtractedContent,
        language: Language,
        initial_deny_terms: list[str] | None = None,
    ) -> PipelineResult:
        # Project deny-list (known-sensitive names NER can't reliably catch) seeds iteration 1.
        deny_terms: list[str] = list(initial_deny_terms or [])
        last_anonymized: ExtractedContent | None = None
        last_mapping: dict[str, str] = {}

        for i in range(1, self.max_iterations + 1):
            doc.current_iteration = i

            doc.transition(presidio_pass_status(i))
            self.hook.on_status(doc)
            result = self.engine.anonymize(content, language, extra_deny_terms=deny_terms)
            last_anonymized, last_mapping = result.content, result.mapping

            doc.transition(qwen_audit_status(i))
            self.hook.on_status(doc)
            audit = self.auditor.audit(result.content.plain_text)

            record = IterationRecord(
                iteration=i,
                presidio_entities=result.entity_count,
                placeholders_used=result.placeholders_used,
                audit=audit,
            )
            doc.iterations.append(record)
            self.hook.on_iteration(doc, record)

            if audit.is_clean_approval(self.max_risk):
                doc.transition(DocumentStatus.APPROVED)
                self.hook.on_status(doc)
                return PipelineResult(doc, last_anonymized, last_mapping, approved=True)

            deny_terms = list({*deny_terms, *audit.raw_terms})

        doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
        self.hook.on_status(doc)
        return PipelineResult(doc, last_anonymized, last_mapping, approved=False)
