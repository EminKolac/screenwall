"""Shared pieces of the scorecard (`evaluation/scorecard.py`): section context and helpers."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# qwen3.5:4b takes ~5-7 s per file; the heuristic auditor alone ~0.1 s. A median under this
# threshold with --llm on means the LLM most likely did not run.
LLM_PLAUSIBLE_MIN_SECONDS = 1.0
# The sections whose pipeline runs the auditor; `--llm` has no effect anywhere else.
LLM_SECTIONS = ("gold", "stress")

# Plan rule: no allow-list and no deny-list behind any reported number. `term_lists=False` makes
# `app.pipeline.terms.effective_terms` return ([], []): no seeded allow-list, no ALLOW_TERMS /
# DENY_TERMS, no user Settings lists. The two env-backed fields are blanked as well.
NO_TERM_LISTS = {"term_lists": False, "allow_terms": "", "deny_terms": ""}


class TermListsActiveError(RuntimeError):
    """A section's engine received a non-empty always-mask or never-mask list."""


@dataclass(frozen=True)
class SectionContext:
    llm: str             # "on" | "off" — only the gold and stress sections run the auditor
    limit: int           # 0 = full run; N = first N items of every panel (smoke runs)
    real: int            # real PDFs to measure in the real-document track (0 = skip it)
    real_max_pages: int  # real track: PDFs with more pages are skipped (0 = no limit)
    corpus: Path         # bist10-benchmark root (goldbench-holdout, probes, stress files)
    work_dir: Path       # this section's git-ignored scratch dir for raw per-item outputs


def vhash(value: str) -> str:
    """BENCHMARK_GUIDE §7: the first 16 hex chars of sha256(value). A value may appear in a
    report only in this form."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def frac(numerator: int, denominator: int) -> dict:
    """Count pair with its rate; an empty denominator gives rate None, never 0 or 1."""
    rate = round(numerator / denominator, 4) if denominator else None
    return {"numerator": numerator, "denominator": denominator, "rate": rate}


def as_frac(value: dict) -> dict:
    """Normalise a scorer `fraction()` dict (unrounded rate) to `frac`."""
    return frac(value["numerator"], value["denominator"])


def median_or_none(values: Iterable) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def term_list_record(deny: list[str], allow: list[str], source: str) -> dict:
    """Sizes and a sha256 of the always-mask / never-mask lists an engine received — never the
    terms themselves."""
    blob = json.dumps({"allow": list(allow), "deny": list(deny)}, ensure_ascii=False)
    return {"allow": len(allow), "deny": len(deny),
            "sha256": hashlib.sha256(blob.encode("utf-8")).hexdigest(), "source": source}


EMPTY_TERM_LISTS_SHA256 = term_list_record([], [], "")["sha256"]


def pipeline_term_lists(settings) -> dict:
    """What `run_pipeline` assembles for these settings (the one place lists are built), checked
    to be empty: a reported number must not depend on a list."""
    from app.pipeline.terms import effective_terms

    deny, allow = effective_terms(settings)
    record = term_list_record(deny, allow, "app.pipeline.terms.effective_terms(settings)")
    record["term_lists_setting"] = settings.term_lists
    if deny or allow:
        raise TermListsActiveError(
            f"pipeline ran with term lists (allow {len(allow)}, deny {len(deny)})")
    return record


def llm_audit_totals(rows: list[dict]) -> dict:
    """Sums of the runners' per-document `llm_audits` counts (`llm_flag.llm_audit_counts`).
    `without_llm` = audits that had neither an LLM verdict nor an LLM failure (heuristic only)."""
    counts = [r["llm_audits"] for r in rows if r.get("llm_audits")]
    audits = sum(c["audits"] for c in counts)
    ok = sum(c["llm_ok"] for c in counts)
    failed = sum(c["llm_failed"] for c in counts)
    return {
        "documents_audited": sum(1 for c in counts if c["audits"]),
        "audits": audits,
        "llm_ok": ok,
        "llm_failed": failed,
        "without_llm": audits - ok - failed,
        "documents_not_fully_llm_audited": sum(1 for c in counts if c["llm_ok"] < c["audits"]),
    }


def llm_evidence(llm: str, median_seconds: float | None, audits: dict | None) -> dict | None:
    """Did the LLM auditor really audit every document? None when the flag is off.

    Two independent checks, both required: the per-file time is plausible for a local LLM, and
    every audit call of every document that reached the audit got a real LLM verdict (zero
    failed calls, zero heuristic-only calls). A few calls failing mid-run barely move the median
    time, so timing alone cannot show them."""
    if llm != "on":
        return None
    plausible = median_seconds is not None and median_seconds >= LLM_PLAUSIBLE_MIN_SECONDS
    failures = None if audits is None else audits["llm_failed"] + audits["without_llm"]
    every_audit = bool(audits) and audits["audits"] > 0 and failures == 0
    return {
        "median_seconds_per_file": median_seconds,
        "plausible": plausible,
        "audits": None if audits is None else audits["audits"],
        "llm_failures": failures,
        "documents_not_fully_llm_audited":
            None if audits is None else audits["documents_not_fully_llm_audited"],
        "every_audit_had_llm": every_audit,
        "passed": plausible and every_audit,
        "expected": "~5-7 s/file with qwen3.5:4b; ~0.1 s/file without an LLM; 0 LLM failures",
    }
