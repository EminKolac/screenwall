"""The auditor's residual terms per document (layer 2 `audit_terms.json`, mapping mode only), so a
re-mask after a review decision keeps what the audit contributed.

  masked     fed back as an always-mask term by the audit loop's repair round; every re-mask
             passes it as a deny term again, so an unrelated decision cannot bring it back.
  open       reported by the last audit and located in the masked text; re-located after every
             re-mask (the finding follows the text, and comes back if its mask is undone).
  unlocated  reported by the last audit but not found in the masked text (paraphrased); tried
             again after every re-mask.

A fresh LLM audit at approval replaces the open and unlocated terms; the repairs stay. Kept terms
stay kept through the reviewer's decisions (store.KeptFindings). The values are raw: layer 2 is
local-only, never an API response, and destructive mode never writes it.
"""
from __future__ import annotations

from app.anonymization.lists import term_key

MASKED, OPEN, UNLOCATED = "masked", "open", "unlocated"


def after_pipeline(repairs: list[str], final: list[str], unlocated: list[str]) -> list[dict]:
    """Records after the mask → audit loop: the repair round's terms, then the final audit's."""
    final = _unique(final)
    final_keys = {term_key(t) for t in final}
    missing = {term_key(t) for t in unlocated}
    records = [_record(t, MASKED) for t in _unique(repairs) if term_key(t) not in final_keys]
    return records + [_record(t, UNLOCATED if term_key(t) in missing else OPEN) for t in final]


def after_reaudit(previous: list[dict], final: list[str], unlocated: list[str]) -> list[dict]:
    """A fresh LLM audit replaces the open and unlocated terms; the repairs stay."""
    return after_pipeline(repair_terms(previous), final, unlocated)


def repair_terms(records: list[dict]) -> list[str]:
    return [r["term"] for r in records if r.get("status") == MASKED]


def relocate_terms(records: list[dict]) -> list[str]:
    return [r["term"] for r in records if r.get("status") in (OPEN, UNLOCATED)]


def _record(term: str, status: str) -> dict:
    return {"term": term, "status": status}


def _unique(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in (t.strip() for t in terms if t and t.strip()):
        if term_key(t) not in seen:
            seen.add(term_key(t))
            out.append(t)
    return out
