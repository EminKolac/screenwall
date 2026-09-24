"""The per-document decisions store (layer 2 `decisions.json`; local-only: it holds original text).

  keep_ranges          unit id -> [[start, end]]          "leave this occurrence unmasked"
  mask_ranges          unit id -> [[start, end, FAMILY]]  "mask this occurrence"
  keep_terms           [value]                            "never mask this term here"
  mask_terms           {value: FAMILY}                    "mask this term in the whole document"
  keep_findings        [value]                            "this residual is not personal data"
  keep_finding_ranges  unit id -> [[start, end]]          "... this occurrence only"

Ranges are ORIGINAL unit offsets. Terms are compared by `term_key` (case and whitespace), so each
list holds one entry per key.
"""
from __future__ import annotations

from app.anonymization.lists import term_key
from app.anonymization.overrides import Overrides
from app.anonymization.units import iter_units
from app.models.document import Document
from app.review.errors import not_found
from app.review.findings import KeptFindings
from app.services.repository import DocumentRepository


def normalized(decisions: dict) -> dict:
    mask_ranges = decisions.get("mask_ranges") or {}
    return {
        "keep_ranges": _ranges(decisions.get("keep_ranges")),
        "mask_ranges": {k: [[int(r[0]), int(r[1]), str(r[2])] for r in v]
                        for k, v in mask_ranges.items()},
        "keep_terms": unique_terms(decisions.get("keep_terms") or []),
        "mask_terms": term_dict(decisions.get("mask_terms") or {}),
        "keep_findings": unique_terms(decisions.get("keep_findings") or []),
        "keep_finding_ranges": _ranges(decisions.get("keep_finding_ranges")),
    }


def _ranges(raw: dict | None) -> dict[str, list[list[int]]]:
    return {k: [[int(r[0]), int(r[1])] for r in v] for k, v in (raw or {}).items()}


def unique_terms(terms: list[str]) -> list[str]:
    """One entry per term key, first spelling kept."""
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if term_key(t) not in seen:
            seen.add(term_key(t))
            out.append(t)
    return out


def term_dict(terms: dict[str, str]) -> dict[str, str]:
    """One entry per term key; a later spelling (the latest decision) replaces an earlier one."""
    by_key: dict[str, tuple[str, str]] = {}
    for term, fam in terms.items():
        by_key.pop(term_key(term), None)
        by_key[term_key(term)] = (term, fam)
    return dict(by_key.values())


def without_term(terms: list[str], value: str) -> list[str]:
    return [t for t in terms if term_key(t) != term_key(value)]


def overrides_from(decisions: dict) -> Overrides:
    d = normalized(decisions)
    return Overrides(
        keep_ranges={k: [(s, e) for s, e in v] for k, v in d["keep_ranges"].items()},
        mask_ranges={k: [(s, e, f) for s, e, f in v] for k, v in d["mask_ranges"].items()},
        keep_terms=d["keep_terms"],
        mask_terms=d["mask_terms"],
    )


def kept_findings(decisions: dict) -> KeptFindings:
    d = normalized(decisions)
    return KeptFindings(
        values=frozenset(term_key(v) for v in d["keep_findings"]),
        ranges={k: [(s, e) for s, e in v] for k, v in d["keep_finding_ranges"].items()})


def load_document(repo: DocumentRepository, doc_id: str) -> Document:
    """The document as stored now (call it inside the document's lock); 404 when it is gone."""
    doc = repo.get_document(doc_id)
    if doc is None:
        raise not_found()
    return doc


def document_deny_terms(repo: DocumentRepository, doc: Document) -> list[str]:
    """Every value this document wants hidden, for text written outside the masked content (the
    download name, the reject reason): the reviewer's document-wide masks, the values of their
    occurrence masks and every term the auditor reported. Mapping mode only — destructive mode
    stores none of them."""
    if doc.mode != "mapping":
        return []
    d = normalized(repo.get_decisions(doc.id))
    values = [*d["mask_terms"], *_occurrence_values(repo, doc.id, d["mask_ranges"]),
              *(r["term"] for r in repo.get_audit_terms(doc.id))]
    return unique_terms([" ".join(v.split()) for v in values if v and v.strip()])


def _occurrence_values(repo: DocumentRepository, doc_id: str,
                       mask_ranges: dict[str, list[list]]) -> list[str]:
    extracted = repo.get_extracted(doc_id) if mask_ranges else None
    if extracted is None:
        return []
    texts = {uid: text for uid, _b, _c, text in iter_units(extracted)}
    return [texts[uid][s:e] for uid, ranges in mask_ranges.items() if uid in texts
            for s, e, _fam in ranges]
