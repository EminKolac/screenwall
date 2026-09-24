"""Mask → audit loop (Architecture.md §9).

Runs [anonymize → audit] up to `max_iterations` (1..2). A CLEAN audit ends the loop; otherwise
the auditor's raw residual strings feed the next masking pass as always-mask terms, once. The
result carries the final engine output (masked content, mapping, edit positions) and the last
audit, whether or not it was clean — the caller routes the document (pipeline.route).

Status changes go through `Document.transition` and the optional hook, so the queue worker can
persist every stage and the UI can show progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.anonymization.engine import AnonymizationEngine, AnonymizationOutput, Overrides
from app.config import Settings
from app.extraction.base import ExtractedContent
from app.models.document import Document, DocumentStatus, IterationRecord, Language
from app.models.findings import AuditResult, RiskLevel


class Auditor(Protocol):
    def audit(self, anonymized_text: str) -> AuditResult: ...


class StatusHook(Protocol):
    def __call__(self, doc: Document) -> None: ...


@dataclass
class PipelineResult:
    document: Document
    output: AnonymizationOutput | None
    audit: AuditResult | None
    approved: bool

    # Pre-v2 readers used these two names.
    @property
    def anonymized(self) -> ExtractedContent | None:
        return self.output.content if self.output else None

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self.output.mapping) if self.output else {}


class Orchestrator:
    def __init__(self, engine: AnonymizationEngine, auditor: Auditor, settings: Settings,
                 on_status: StatusHook | None = None) -> None:
        self.engine = engine
        self.auditor = auditor
        self.max_iterations = settings.max_iterations
        self.max_risk = RiskLevel(settings.auditor_risk_approve)
        self.on_status = on_status or (lambda doc: None)

    def run(self, doc: Document, content: ExtractedContent, language: Language,
            initial_deny_terms: list[str] | None = None,
            initial_allow_terms: list[str] | None = None,
            overrides: Overrides | None = None) -> PipelineResult:
        deny_terms = list(initial_deny_terms or [])
        # The never-mask list is fixed across iterations: an auditor cannot say "false positive".
        allow_terms = list(initial_allow_terms or [])
        output: AnonymizationOutput | None = None
        audit: AuditResult | None = None
        for i in range(1, self.max_iterations + 1):
            self._set(doc, DocumentStatus.MASKING)
            output = self.engine.anonymize(content, language, extra_deny_terms=deny_terms,
                                           extra_allow_terms=allow_terms, overrides=overrides)
            self._set(doc, DocumentStatus.AUDITING)
            audit = self.auditor.audit(output.content.plain_text)
            doc.iterations.append(IterationRecord(
                iteration=i,
                presidio_entities=output.entity_count,
                placeholders_used=output.placeholders_used,
                by_source=output.by_source,
                audit=audit,
            ))
            if audit.is_clean_approval(self.max_risk):
                return PipelineResult(doc, output, audit, approved=True)
            deny_terms = list({*deny_terms, *audit.raw_terms})
        return PipelineResult(doc, output, audit, approved=False)

    def _set(self, doc: Document, status: DocumentStatus) -> None:
        doc.transition(status)
        self.on_status(doc)
