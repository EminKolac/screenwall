"""Human decisions: mask, unmask, keep — then approve or reject.

Decisions are stored in layer 2 (they reference original values, so mapping mode only) and are
re-applied on every re-anonymization through engine Overrides, so they survive restarts and later
decisions (before v2 an unmask lived only in memory and was lost on the next redaction). Global
decisions go to the user's always/never lists (Settings).

Approval is fail-closed: open items block it, and a document changed since its last LLM audit is
re-audited first.
"""
from __future__ import annotations

import re

from app.anonymization.engine import AnonymizationOutput, Engine, Overrides
from app.audit.factory import build_auditor
from app.audit.heuristic import HeuristicAuditor
from app.config import Settings
from app.models.document import Document, DocumentStatus
from app.models.findings import RiskLevel
from app.pipeline.orchestrator import PipelineResult
from app.pipeline.runner import build_chat_context, persist_output, record_audit
from app.pipeline.terms import effective_terms
from app.review.payload import build_review
from app.review.reasons import REVIEW_REASONS
from app.services.repository import DocumentRepository
from app.services.user_settings import load_user_settings, save_user_settings

_FAMILY = re.compile(r"^[A-Z][A-Z_]{1,19}$")
_MAX_VALUE = 200
_AUDIT_CODES = ("audit_residual", "audit_unlocated", "auditor_unavailable")


class DecisionError(Exception):
    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


# ---------------------------------------------------------------- decisions store

def _normalized(decisions: dict) -> dict:
    return {
        "keep_ranges": {k: [list(map(int, r)) for r in v]
                        for k, v in (decisions.get("keep_ranges") or {}).items()},
        "mask_ranges": {k: [[int(r[0]), int(r[1]), str(r[2])] for r in v]
                        for k, v in (decisions.get("mask_ranges") or {}).items()},
        "keep_terms": list(decisions.get("keep_terms") or []),
        "mask_terms": dict(decisions.get("mask_terms") or {}),
        "keep_findings": list(decisions.get("keep_findings") or []),
    }


def overrides_from(decisions: dict) -> Overrides:
    d = _normalized(decisions)
    return Overrides(
        keep_ranges={k: [(s, e) for s, e in v] for k, v in d["keep_ranges"].items()},
        mask_ranges={k: [(s, e, f) for s, e, f in v] for k, v in d["mask_ranges"].items()},
        keep_terms=d["keep_terms"],
        mask_terms=d["mask_terms"],
    )


# ---------------------------------------------------------------- target resolution

def _resolve(doc: Document, repo: DocumentRepository, target: dict) -> dict:
    payload = build_review(doc, repo)
    units = {u["id"]: u for u in payload["units"]}
    if "span_id" in target:
        found = next((s for s in payload["spans"] if s["id"] == target["span_id"]), None)
        if found is None:
            raise DecisionError("invalid_decision", 422)
        return _target(units, found["unit_id"], found["start"], found["end"],
                       found["family"], state=found["state"])
    if "item_id" in target:
        found = next((i for i in payload["items"] if i["id"] == target["item_id"]), None)
        if found is None:
            raise DecisionError("invalid_decision", 422)
        return _target(units, found["unit_id"], found["start"], found["end"],
                       found["family"] or "SENSITIVE", state="item")
    fam = str(target.get("family") or "")
    if not _FAMILY.match(fam):
        raise DecisionError("invalid_decision", 422)
    return _target(units, str(target.get("unit_id")), int(target.get("start", -1)),
                   int(target.get("end", -1)), fam, state="selection")


def _target(units: dict, uid: str, start: int, end: int, fam: str, *, state: str) -> dict:
    unit = units.get(uid)
    if unit is None or unit["original"] is None:
        raise DecisionError("invalid_decision", 422)
    if not 0 <= start < end <= len(unit["original"]):
        raise DecisionError("invalid_decision", 422)
    value = " ".join(unit["original"][start:end].split())
    if not value or len(value) > _MAX_VALUE:
        raise DecisionError("invalid_decision", 422)
    return {"unit_id": uid, "start": start, "end": end, "family": fam, "value": value,
            "state": state}


# ---------------------------------------------------------------- applying a decision

def apply_decision(doc: Document, repo: DocumentRepository, settings: Settings,
                   op: str, target: dict, scope: str) -> None:
    if doc.status not in (DocumentStatus.NEEDS_HUMAN_REVIEW, DocumentStatus.APPROVED):
        raise DecisionError("not_in_review")
    if doc.mode != "mapping" or repo.get_extracted(doc.id) is None:
        raise DecisionError("original_not_stored")
    if op not in ("mask", "unmask", "keep") or scope not in ("occurrence", "document", "global"):
        raise DecisionError("invalid_decision", 422)
    t = _resolve(doc, repo, target)
    d = _normalized(repo.get_decisions(doc.id))
    if op == "unmask":
        _unmask(d, t, scope, settings)
    elif op == "mask":
        _mask(d, t, scope, settings)
    else:
        _keep(d, t, scope, settings)
    repo.save_decisions(doc.id, d)
    reanonymize(doc, repo, settings)


def _unmask(d: dict, t: dict, scope: str, settings: Settings) -> None:
    uid, s, e = t["unit_id"], t["start"], t["end"]
    if t["state"] == "added":  # undo the reviewer's own mask instead of stacking a keep on it
        d["mask_ranges"][uid] = [r for r in d["mask_ranges"].get(uid, [])
                                 if not (r[0] < e and s < r[1])]
        d["mask_terms"].pop(t["value"], None)
        return
    if t["state"] not in ("masked",):
        raise DecisionError("invalid_decision", 422)
    if scope == "occurrence":
        d["keep_ranges"].setdefault(uid, []).append([s, e])
    elif scope == "document":
        d["keep_terms"] = list(dict.fromkeys([*d["keep_terms"], t["value"]]))
    else:
        _global(settings, never=t["value"])


def _mask(d: dict, t: dict, scope: str, settings: Settings) -> None:
    uid, s, e = t["unit_id"], t["start"], t["end"]
    if t["state"] == "kept":  # undo the reviewer's own keep
        d["keep_ranges"][uid] = [r for r in d["keep_ranges"].get(uid, [])
                                 if not (r[0] < e and s < r[1])]
        d["keep_terms"] = [v for v in d["keep_terms"] if v.casefold() != t["value"].casefold()]
        return
    if scope == "occurrence":
        d["mask_ranges"].setdefault(uid, []).append([s, e, t["family"]])
    elif scope == "document":
        d["mask_terms"][t["value"]] = t["family"]
    else:
        _global(settings, always=t["value"])


def _keep(d: dict, t: dict, scope: str, settings: Settings) -> None:
    if t["state"] != "item":
        raise DecisionError("invalid_decision", 422)
    if scope == "global":
        _global(settings, never=t["value"])
    d["keep_findings"] = list(dict.fromkeys([*d["keep_findings"], t["value"]]))


def _global(settings: Settings, *, always: str | None = None, never: str | None = None) -> None:
    prefs = load_user_settings(settings)
    if always:
        prefs.always_mask = [*prefs.always_mask, always]
    if never:
        prefs.never_mask = [*prefs.never_mask, never]
    save_user_settings(settings, prefs.model_validate(prefs.model_dump()))


# ---------------------------------------------------------------- re-anonymization and audit

def reanonymize(doc: Document, repo: DocumentRepository, settings: Settings) -> None:
    """Re-mask the stored original with every decision, then run the fast heuristic audit.
    The LLM audit runs at approval time (the document is marked as changed since its audit)."""
    extracted = repo.get_extracted(doc.id)
    if extracted is None:
        raise DecisionError("original_not_stored")
    decisions = _normalized(repo.get_decisions(doc.id))
    deny, allow = effective_terms(settings)
    output = Engine().anonymize(extracted, doc.language, extra_deny_terms=deny,
                                extra_allow_terms=allow, overrides=overrides_from(decisions))
    was_approved = doc.status == DocumentStatus.APPROVED
    audited = doc.audited_revision
    persist_output(doc, repo, output, destructive=False)
    heuristic = HeuristicAuditor().audit(output.content.plain_text)
    clean = heuristic.is_clean_approval(RiskLevel(settings.auditor_risk_approve))
    _drop_audit_reasons(doc)
    record_audit(doc, repo, PipelineResult(doc, output, heuristic, approved=clean),
                 kept_values=decisions["keep_findings"])
    doc.audited_revision = audited  # only the heuristic ran; the LLM audit is now stale
    if was_approved:
        doc.add_reason("changed_after_approval", REVIEW_REASONS["changed_after_approval"])
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)


def _drop_audit_reasons(doc: Document) -> None:
    doc.reasons = [r for r in doc.reasons if r.code not in _AUDIT_CODES]
    doc.review_reason = [r.text for r in doc.reasons]


def approve(doc: Document, repo: DocumentRepository, settings: Settings) -> None:
    if doc.status != DocumentStatus.NEEDS_HUMAN_REVIEW:
        raise DecisionError("not_in_review")
    if doc.pending_count > 0:
        raise DecisionError("unresolved_items")
    anon = repo.get_anonymized(doc.id)
    if anon is not None and doc.audited_revision != doc.revision:
        audit = build_auditor(settings).audit(anon.plain_text)
        if audit.summary.startswith("Fail-closed"):
            raise DecisionError("ollama_unreachable", 503)
        clean = audit.is_clean_approval(RiskLevel(settings.auditor_risk_approve))
        _drop_audit_reasons(doc)
        record_audit(doc, repo,
                     PipelineResult(doc, AnonymizationOutput(content=anon), audit, approved=clean),
                     kept_values=_normalized(repo.get_decisions(doc.id))["keep_findings"])
        if doc.pending_count > 0:
            repo.save_document(doc)
            raise DecisionError("unresolved_items")
    doc.reasons = [r for r in doc.reasons if r.code != "changed_after_approval"]
    doc.review_reason = [r.text for r in doc.reasons]
    doc.transition(DocumentStatus.APPROVED)
    build_chat_context(repo, doc.id)
    repo.save_document(doc)


def reject(doc: Document, repo: DocumentRepository, reason: str | None) -> None:
    if doc.status.processing or doc.status == DocumentStatus.REJECTED:
        raise DecisionError("not_in_review")
    doc.reject_reason = " ".join((reason or "").split())[:500]
    doc.transition(DocumentStatus.REJECTED)
    repo.save_document(doc)

