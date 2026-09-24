"""Human decisions: mask, unmask, keep — each followed by a re-mask of the stored original.

Decisions live in layer 2 (store.py: they reference original values, so mapping mode only) and
are re-applied on every re-anonymization through engine Overrides, so they survive restarts and
later decisions. Global decisions go to the user's always/never lists (user settings); a global
mask keeps the family the reviewer chose.

Everything happens under the document's lock, on the document re-read inside it. A stale client
(expected_revision) is refused before any positional span or item id is resolved. The re-mask is
computed before anything is stored, and a failed one leaves the decisions and the global lists as
they were. The final actions (approve, reject, delete) live in approval.py.
"""
from __future__ import annotations

from collections.abc import Callable

from app.anonymization.engine import Engine
from app.anonymization.lists import term_key
from app.audit.heuristic import HeuristicAuditor
from app.config import Settings
from app.models.document import Document, DocumentStatus
from app.pipeline.runner import note_settings, write_output
from app.pipeline.terms import effective_terms
from app.review import audit_terms
from app.review.approval import approve, delete_document, reject
from app.review.errors import DecisionError, invalid
from app.review.findings import record_findings
from app.review.reasons import REVIEW_REASONS
from app.review.store import (
    kept_findings,
    load_document,
    normalized,
    overrides_from,
    term_dict,
    unique_terms,
    without_term,
)
from app.review.targets import Target, resolve_target
from app.services.locks import document_lock
from app.services.repository import DocumentRepository
from app.services.user_settings import (
    UserSettings,
    mask_families,
    update_user_settings,
    with_always,
    with_never,
)

__all__ = ["DecisionError", "apply_decision", "approve", "delete_document", "reanonymize",
           "reject"]

GlobalChange = Callable[[UserSettings], UserSettings] | None
_SCOPES = ("occurrence", "document", "global")


# ---------------------------------------------------------------- applying a decision

def apply_decision(doc_id: str, repo: DocumentRepository, settings: Settings, op: str,
                   target: object, scope: str,
                   expected_revision: int | None = None) -> Document:
    if op not in _OPS or scope not in _SCOPES:
        raise invalid()
    with document_lock(doc_id):
        doc = load_document(repo, doc_id)
        if doc.status not in (DocumentStatus.NEEDS_HUMAN_REVIEW, DocumentStatus.APPROVED):
            raise DecisionError("not_in_review")
        if expected_revision is not None and expected_revision != doc.revision:
            raise DecisionError("stale_revision")
        if doc.mode != "mapping" or repo.get_extracted(doc.id) is None:
            raise DecisionError("original_not_stored")
        t = resolve_target(doc, repo, target)
        decisions, change = _OPS[op](normalized(repo.get_decisions(doc.id)), t, scope)
        _commit(doc, repo, settings, decisions, change)
        return doc


def _commit(doc: Document, repo: DocumentRepository, settings: Settings, decisions: dict,
            change: GlobalChange) -> None:
    """A global list change is written first (the re-mask reads the lists) and undone when the
    re-mask fails — unless something else changed the lists meanwhile."""
    if change is None:
        reanonymize(doc, repo, settings, decisions)
        return
    before: list[UserSettings] = []

    def remember_and_change(prefs: UserSettings) -> UserSettings:
        before.append(prefs)
        return change(prefs)

    applied = update_user_settings(settings, remember_and_change)
    try:
        reanonymize(doc, repo, settings, decisions)
    except BaseException:
        update_user_settings(settings, lambda p: before[0] if p == applied else p)
        raise


def _unmask(d: dict, t: Target, scope: str) -> tuple[dict, GlobalChange]:
    if t.state == "added":
        return _undo_mask(d, t, scope)
    if t.state != "masked" or (t.split and scope != "occurrence"):
        raise invalid()  # a split-cell fragment is no term: unmask that occurrence instead
    if scope == "occurrence":
        return _add_range(d, "keep_ranges", t.unit_id, [t.start, t.end]), None
    if scope == "document":
        return {**d, "keep_terms": unique_terms([*d["keep_terms"], t.value])}, None
    return d, lambda p: with_never(p, t.value)


def _undo_mask(d: dict, t: Target, scope: str) -> tuple[dict, GlobalChange]:
    """Unmask a span the reviewer's own mask produced. One occurrence of a document-wide mask gets
    a keep range; the term itself (any spelling) goes only with document or global scope."""
    ranges = d["mask_ranges"].get(t.unit_id, [])
    rest = [r for r in ranges if not (r[0] < t.end and t.start < r[1])]
    undone = {**d, "mask_ranges": {**d["mask_ranges"], t.unit_id: rest}}
    if scope == "occurrence":
        if len(rest) < len(ranges):
            return undone, None
        return _add_range(d, "keep_ranges", t.unit_id, [t.start, t.end]), None
    terms = {k: v for k, v in d["mask_terms"].items() if term_key(k) != term_key(t.value)}
    undone = {**undone, "mask_terms": terms}
    return undone, (lambda p: with_never(p, t.value)) if scope == "global" else None


def _mask(d: dict, t: Target, scope: str) -> tuple[dict, GlobalChange]:
    if t.state == "kept":  # undo the reviewer's own keep
        ranges = d["keep_ranges"].get(t.unit_id, [])
        rest = [r for r in ranges if not (r[0] < t.end and t.start < r[1])]
        return {**d, "keep_ranges": {**d["keep_ranges"], t.unit_id: rest},
                "keep_terms": without_term(d["keep_terms"], t.value)}, None
    if scope == "occurrence":
        return _add_range(d, "mask_ranges", t.unit_id, [t.start, t.end, t.family]), None
    d = {**d, "keep_terms": without_term(d["keep_terms"], t.value)}
    if scope == "document":
        return {**d, "mask_terms": term_dict({**d["mask_terms"], t.value: t.family})}, None
    return d, lambda p: with_always(p, t.value, t.family)


def _keep(d: dict, t: Target, scope: str) -> tuple[dict, GlobalChange]:
    """A finding the reviewer says is not personal data: this occurrence (by position) or every
    same-value finding of the document; global scope also adds it to the never-mask list."""
    if t.state != "item":
        raise invalid()
    if scope == "occurrence":
        return _add_range(d, "keep_finding_ranges", t.unit_id, [t.start, t.end]), None
    kept = {**d, "keep_findings": unique_terms([*d["keep_findings"], t.value])}
    return kept, (lambda p: with_never(p, t.value)) if scope == "global" else None


def _add_range(d: dict, key: str, uid: str, rng: list) -> dict:
    ranges = d[key].get(uid, [])
    return {**d, key: {**d[key], uid: ranges if rng in ranges else [*ranges, rng]}}


_OPS = {"unmask": _unmask, "mask": _mask, "keep": _keep}


# ---------------------------------------------------------------- re-anonymization and audit

def reanonymize(doc: Document, repo: DocumentRepository, settings: Settings,
                decisions: dict) -> None:
    """Re-mask the stored original with `decisions`, keeping the audit's repairs, and re-locate
    its open terms plus the heuristic backstop's. The LLM audit runs at approval (the revision
    moves on, so the document is no longer covered by its last LLM audit). Nothing is stored
    until the re-mask succeeded; the previous decisions come back if storing then fails."""
    extracted = repo.get_extracted(doc.id)
    if extracted is None:
        raise DecisionError("original_not_stored")
    records = repo.get_audit_terms(doc.id)
    deny, allow = effective_terms(settings)
    output = Engine().anonymize(
        extracted, doc.language, extra_deny_terms=deny + audit_terms.repair_terms(records),
        extra_allow_terms=allow, overrides=overrides_from(decisions),
        deny_families=mask_families(settings))
    previous = repo.get_decisions(doc.id)
    repo.save_decisions(doc.id, decisions)
    try:
        _store_remask(doc, repo, output, decisions, records, settings)
    except BaseException:
        repo.save_decisions(doc.id, previous)
        raise


def _store_remask(doc: Document, repo: DocumentRepository, output, decisions: dict,
                  records: list[dict], settings: Settings) -> None:
    """The new revision and the review status are stored BEFORE the new content: if a later
    write fails, the document sits in review, covered by no LLM audit (approval re-audits), and
    an approved document stops being downloadable before its layer 3 changes."""
    if doc.status == DocumentStatus.APPROVED:
        doc.add_reason("changed_after_approval", REVIEW_REASONS["changed_after_approval"])
    doc.revision += 1
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    note_settings(doc, settings)
    repo.save_document(doc)
    write_output(doc, repo, output, destructive=False)
    heuristic = HeuristicAuditor().audit(output.content.plain_text)
    terms = audit_terms.relocate_terms(records) + heuristic.raw_terms
    record_findings(doc, repo, output.content, output.edits, terms, kept_findings(decisions),
                    residual=False)
    repo.save_document(doc)

