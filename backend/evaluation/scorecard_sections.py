"""Scorecard sections (a) native GoldBench, (b) strict scorer, (c) stress.

Each `run_*_section(ctx)` reuses the existing runner, writes its raw per-item output under
`ctx.work_dir` (git-ignored) and returns a JSON-safe dict of counts and rates. No raw value is
ever returned; the reused runners already store values only as vhash.

Gold and stress run the full pipeline with `NO_TERM_LISTS` (no allow-list, no deny-list, no user
lists) and a storage root inside `ctx.work_dir`, never a directory shared with standalone runs.
Every section records the lists its engine received (`term_lists`: counts + sha256, 0/0).
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from evaluation.scorecard_common import (
    NO_TERM_LISTS,
    SectionContext,
    as_frac,
    frac,
    llm_audit_totals,
    llm_evidence,
    load_jsonl,
    median_or_none,
    pipeline_term_lists,
    term_list_record,
)

FORMATS = ("pdf", "docx", "xlsx")
MODE = "mapping"
HOLDOUT_DOCS = 60

# The "20-document subset" behind EXPERIMENTS.md "v5 FINAL" (holdout crit_recall 1.0). Nobody
# chose it: the v5 runs (v5fast2, v5fast3, v5hold, v5gate-hold; run_config split=holdout,
# formats=pdf,docx,xlsx, limit=60) passed `--limit 60`, and run_gold's limit counts
# DOCUMENT x FORMAT pairs, so they kept the first 60 / 3 = 20 rows of holdout_gold/gold.jsonl.
# That file is ordered by domain, so the subset is finance + legal only.
V5_SUBSET_IDS = tuple(
    [f"finance-{i:03d}" for i in range(3, 40, 4)] + [f"legal-{i:03d}" for i in range(3, 40, 4)])
V5_SUBSET_RULE = (
    "first 20 documents of holdout_gold/gold.jsonl = run_gold --split holdout "
    "--formats pdf,docx,xlsx --limit 60 (the limit counts document x format pairs); "
    "finance-* and legal-* only, no health/hr/public/correspondence")

# `actual_status` strings persisted by run_stress (DocumentStatus values / its error prefixes).
APPROVED = "approved"
PIPELINE_STATUSES = frozenset({"approved", "needs_human_review"})

_NO_MASK_HONEST = (
    "pipeline with term lists off: no allow-list protects the NO_MASK (must_keep) terms, so this "
    "is the pipeline's own, honest over-masking of them; strict must_keep_kept asks the same "
    "question of the bare engine")
_NO_MASK_CONTAMINATED = (
    "not reported: the pipeline ran with an allow-list, and the default one contains every "
    "must_keep term, so the number would be contaminated; use strict must_keep_kept")


def measured_by(lists_off: bool) -> dict:
    pipeline = ("pipeline: value absent from run_pipeline output (term lists off: no allow-list, "
                "no deny-list, no user lists)" if lists_off else
                "pipeline: value absent from run_pipeline output (WITH term lists)")
    return {
        "critical_recall": pipeline,
        "critical_not_located": "critical mentions whose value is not in the extracted text; "
                                "excluded from critical_recall because they cannot be scored",
        "mention_recall": "pipeline",
        "entity_recall": "pipeline",
        "partial_leaks": "pipeline",
        "leaked_in_export": "pipeline export (PDF render + re-extract)",
        "char_recall": "detect: engine.detect() on the original text "
                       "(no propagation, no table passes, no allow-list)",
        "char_precision_approx": "detect",
        "f2": "detect",
        "no_mask_violations": _NO_MASK_HONEST if lists_off else _NO_MASK_CONTAMINATED,
    }


# ------------------------------------------------------------------------------ (a) gold

def load_holdout_rows() -> list[dict]:
    """The holdout the gold section scores (also the raw-value guard's source of gold values)."""
    from evaluation.goldbench.run_gold import load_gold

    return [r for r in load_gold({"holdout"}) if r["split"] == "holdout"]


def _critical_recall(recs: list[dict]) -> dict:
    from evaluation.goldbench.report_gold import detection_metrics

    det = detection_metrics(recs)
    crit = det["critical_mentions"]
    return frac(crit - det["critical_false_negatives"], crit)


def gold_block(recs: list[dict], expected_docs: int, *, lists_off: bool = False) -> dict:
    """Micro-aggregate (report_gold.detection_metrics) over document x format records.
    `lists_off`: the pipeline ran without term lists; only then is the NO_MASK count reported."""
    from evaluation.goldbench.report_gold import detection_metrics

    det = detection_metrics(recs)
    processed = [r for r in recs if r.get("result") == "processed"]
    checks = [r["mode_check"] for r in recs if r.get("mode_check")]
    block = {
        "documents": len({r["doc_id"] for r in recs}),
        "expected_documents": expected_docs,
        "records": len(recs),
        "processed": len(processed),
        "errors": sum(1 for r in recs if r.get("result") == "error"),
        "critical_recall": frac(det["critical_mentions"] - det["critical_false_negatives"],
                                det["critical_mentions"]),
        "critical_false_negatives": det["critical_false_negatives"],
        "critical_not_located": det["critical_not_located"],
        "mention_recall": det["mention_recall"],
        "entity_recall": det["entity_recall"],
        "char_recall": det["char_recall"],
        "char_precision_approx": det["char_precision"],
        "f2": det["f2"],
        "partial_leaks": det["partial_leaks"],
        "leaked_in_export": det["leaked_in_export"],
        "not_located": det["not_located"],
        "no_mask_violations": frac(det["no_mask_violations"], det["no_mask_total"])
        if lists_off else None,
        "status_counts": dict(Counter(r.get("status", r.get("result", "?")) for r in recs)),
        "mode_check_passed": frac(sum(1 for c in checks if c.get("passed")), len(checks)),
        # per check (M1 map complete, M2 exact round-trip, M3 containment): one failing check
        # must not hide how the others did
        "mode_checks": {name: frac(sum(1 for c in checks if (c.get("checks") or {}).get(name)),
                                   len(checks))
                        for name in sorted({k for c in checks for k in c.get("checks") or {}})},
        "critical_recall_by_format": {
            fmt: _critical_recall([r for r in recs if r.get("format") == fmt]) for fmt in FORMATS},
        "llm_audits": llm_audit_totals(recs),
        "median_seconds_per_file": median_or_none(r.get("seconds") for r in processed),
    }
    if not lists_off:
        block["no_mask_violations_reason"] = _NO_MASK_CONTAMINATED
    return block


def run_gold_section(ctx: SectionContext) -> dict:
    from evaluation.goldbench import run_gold

    rows = load_holdout_rows()
    if not rows:
        raise FileNotFoundError("holdout gold missing: data/goldbench/holdout_gold/gold.jsonl")
    order = tuple(r["doc_id"] for r in rows)
    if ctx.limit:
        rows = rows[:ctx.limit]
    out = ctx.work_dir / "results.jsonl"
    settings = run_gold.run_mode(rows, MODE, FORMATS, out, llm=ctx.llm,
                                 root=ctx.work_dir / "storage", overrides=NO_TERM_LISTS)
    terms = pipeline_term_lists(settings)  # raises unless both lists were empty
    lists_off = terms["allow"] == 0 and terms["deny"] == 0
    recs = load_jsonl(out)
    full = gold_block(recs, HOLDOUT_DOCS, lists_off=lists_off)
    subset = gold_block([r for r in recs if r["doc_id"] in V5_SUBSET_IDS], len(V5_SUBSET_IDS),
                        lists_off=lists_off)
    subset.update(rule=V5_SUBSET_RULE, ids=list(V5_SUBSET_IDS),
                  rule_matches_holdout_order=order[:len(V5_SUBSET_IDS)] == V5_SUBSET_IDS)
    return {
        "llm": ctx.llm, "mode": MODE, "formats": list(FORMATS),
        "complete": full["documents"] == HOLDOUT_DOCS and full["records"] == full["processed"],
        "full": full,
        "subset20": subset,
        "term_lists": terms,
        "measured_by": measured_by(lists_off),
        "llm_evidence": llm_evidence(ctx.llm, full["median_seconds_per_file"],
                                     full["llm_audits"]),
        "raw_results": str(out),
    }


# ---------------------------------------------------------------------------- (b) strict

def strict_block(summary: dict, probe_rows: list[dict]) -> dict:
    """Headline numbers from a strict `metrics.json` plus its `probe-safe.json` rows."""
    g = summary["gold"]
    bare, contextual = summary["probes"]["bare"], summary["probes"]["contextual"]
    keep = g["over_masking"]
    critical = [r for r in probe_rows if r["critical"]]
    return {
        "complete": summary.get("complete", True),
        "limit": summary.get("limit", 0),
        "documents": g["documents"],
        "critical_recall": as_frac(g["critical_recall"]),
        "literal_critical_recall": as_frac(g["literal_critical_recall"]),
        "recall": as_frac(g["recall"]),
        "canary_escapes": frac(bare["numerator"] + contextual["numerator"],
                               bare["denominator"] + contextual["denominator"]),
        "canary_escapes_bare": as_frac(bare),
        "canary_escapes_contextual": as_frac(contextual),
        "canary_escapes_critical": frac(sum(1 for r in critical if r["missed"]), len(critical)),
        "neutral_changed": as_frac(summary["over_mask_sentences"]),
        "must_keep_kept": frac(keep["denominator"] - keep["numerator"], keep["denominator"]),
        "unprocessed_documents": list(g["unprocessed"]),
        "by_type": {k: as_frac(v) for k, v in g["by_type"].items()},
        "allow_list": summary.get("allow_list", "none"),
        # evaluation/strict/run.py calls engine.anonymize(content, Language.mixed): no list.
        "term_lists": term_list_record(
            [], [], "engine.anonymize without extra_allow_terms / extra_deny_terms "
                    "(evaluation/strict/run.py)"),
        "external_network": summary.get("external_network"),
        "scorer_sha256": summary["scorer_sha256"],
        "corpus_sha256": summary["corpus_sha256"],
    }


def run_strict_section(ctx: SectionContext) -> dict:
    from evaluation.strict.run import run_strict

    out = ctx.work_dir / "run"
    summary = run_strict(ctx.corpus, out, limit=ctx.limit)
    probe_rows = json.loads((out / "probe-safe.json").read_text(encoding="utf-8"))
    block = strict_block(summary, probe_rows)
    items = block["documents"] + len(probe_rows) + block["neutral_changed"]["denominator"]
    block["seconds_per_item"] = round(summary["seconds"] / items, 3) if items else None
    block["raw_results"] = str(out)
    return block


# ---------------------------------------------------------------------------- (c) stress

def load_pinned_stress_corpus(corpus: Path) -> tuple[list, dict]:
    """The 72 pinned files + manifest from the benchmark corpus (byte-identical to
    `goldbench.stress.build_corpus()` when checked on 2026-09-24), with their hashes."""
    from evaluation.goldbench.stress import StressCase

    manifest_path = corpus / "stress-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases, files = [], hashlib.sha256()
    for m in manifest:
        stem, _, fmt = m["file"].rpartition(".")
        data = (corpus / "stress-corpus" / m["file"]).read_bytes()
        files.update(hashlib.sha256(data).digest())
        cases.append((StressCase(
            case_id=stem, fmt=fmt, scenario=m["scenario"], expected=m["expected"],
            planted_values=list(m["planted_values"]),
            architecturally_safe=bool(m.get("architecturally_safe", False))), data))
    pins = {"manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "files_sha256": files.hexdigest(), "files": len(cases)}
    return cases, pins


def stress_block(rows: list[dict]) -> dict:
    safe = [r for r in rows if r["expected"] == "safe_output"]
    closed = [r for r in rows if r["expected"] == "fail_closed"]
    ran = [r for r in rows if r["actual_status"] in PIPELINE_STATUSES]
    tested = [r for r in rows if not r["architecturally_safe"] and r["generated"]]
    verdicts = Counter(r["verdict"] for r in rows)
    return {
        "files": len(rows),
        "leaks_approved": frac(verdicts.get("critical_false_approval", 0), len(rows)),
        "leaked_any_status": frac(sum(1 for r in rows if r["planted_leaked"]), len(rows)),
        "safe_delivery": frac(sum(1 for r in safe if r["actual_status"] == APPROVED
                                  and not r["planted_leaked"]), len(safe)),
        "fail_closed_respected": frac(sum(1 for r in closed if r["verdict"] == "pass"),
                                      len(closed)),
        "routed_to_review": sum(1 for r in rows if r.get("over_conservative")),
        "actually_tested_pass": frac(sum(1 for r in tested if r["verdict"] == "pass"),
                                     len(tested)),
        "architecturally_safe": sum(1 for r in rows if r["architecturally_safe"]),
        "verdicts": dict(verdicts),
        "status_counts": dict(Counter(r["actual_status"] for r in rows)),
        "llm_audits": llm_audit_totals(rows),
        "median_seconds_per_file": median_or_none(r["seconds"] for r in ran),
    }


def run_stress_section(ctx: SectionContext) -> dict:
    from evaluation.goldbench import run_stress

    corpus, pins = load_pinned_stress_corpus(ctx.corpus)
    if ctx.limit:
        corpus = corpus[:ctx.limit]
    out = ctx.work_dir / "stress.jsonl"
    settings = run_stress.run_mode(MODE, corpus, out, llm=ctx.llm,
                                   root=ctx.work_dir / "storage", overrides=NO_TERM_LISTS)
    terms = pipeline_term_lists(settings)  # raises unless both lists were empty
    block = stress_block(load_jsonl(out))
    block.update(
        llm=ctx.llm, mode=MODE, corpus=pins,
        complete=block["files"] == pins["files"],
        term_lists=terms,
        llm_evidence=llm_evidence(ctx.llm, block["median_seconds_per_file"],
                                  block["llm_audits"]),
        raw_results=str(out))
    return block
