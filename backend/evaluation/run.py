"""CLI: build the synthetic corpus, run the REAL detection path, report precision/recall/F1.

    uv run python -m evaluation.run                        # baseline (Privacy Filter per env)
    USE_PRIVACY_FILTER=true uv run python -m evaluation.run  # + stage ② → compare the numbers

Reports overall P/R/F1, per-entity-type recall, over-masking count, and per-stage coverage
(which detection stage's spans covered each gold PII — incl. how many only Privacy Filter caught).
Flags: --n SAMPLES_PER_TEMPLATE, --json PATH, --min-recall GATE (exit 1 if overall recall below).
"""
from __future__ import annotations

import argparse
import json

from app.anonymization.presidio_engine import PresidioEngine
from app.anonymization.privacy_filter import get_privacy_filter
from evaluation.corpus import build_corpus
from evaluation.score import Aggregate, overlaps, score


def _stage(source: str) -> str:
    """Group an EntitySpan.source into its detection stage (mirrors presidio_engine._source_cat)."""
    return "presidio" if source in ("en", "tr") else (source or "presidio")


def _bar(label: str, value: float, width: int = 24) -> str:
    filled = int(round(value * width))
    return f"  {label:<16} {'█' * filled}{'·' * (width - filled)} {value:6.1%}"


def evaluate(n_per_template: int) -> dict:
    samples = build_corpus(n_per_template)
    engine = PresidioEngine()
    pf_active = get_privacy_filter() is not None

    overall = Aggregate()
    by_type: dict[str, Aggregate] = {}
    stage_cover: dict[str, int] = {"presidio": 0, "privacy_filter": 0, "deny": 0}
    pf_only = 0  # gold spans that ONLY a Privacy Filter span covered (Presidio missed them)

    for s in samples:
        pred = engine.detect(s.text)
        score(s.spans, pred, overall)
        for g in s.spans:
            covering = [p for p in pred if overlaps(g.start, g.end, p.start, p.end)]
            a = by_type.setdefault(g.entity_type, Aggregate())
            a.gold += 1
            if covering:
                a.covered += 1
            stages = {_stage(p.source) for p in covering}
            for st in stages:
                stage_cover[st] = stage_cover.get(st, 0) + 1
            if covering and stages == {"privacy_filter"}:
                pf_only += 1

    n_pii = sum(1 for s in samples if s.spans)
    return {
        "samples": len(samples),
        "samples_with_pii": n_pii,
        "distractors": len(samples) - n_pii,
        "privacy_filter_active": pf_active,
        "overall": {"precision": overall.precision, "recall": overall.recall,
                    "f1": overall.f1, "over_mask": overall.over_mask,
                    "gold": overall.gold, "pred": overall.pred},
        "per_type_recall": {k: {"recall": v.recall, "covered": v.covered, "gold": v.gold}
                            for k, v in sorted(by_type.items())},
        "stage_coverage": stage_cover,
        "privacy_filter_only": pf_only,
    }


def _print_report(r: dict) -> None:
    pf = "ACTIVE ✓" if r["privacy_filter_active"] else "inactive (Presidio only)"
    o = r["overall"]
    print("\n" + "═" * 52)
    print("  ANONYMIZATION DETECTION — EVALUATION")
    print("═" * 52)
    print(f"  Corpus : {r['samples']} samples "
          f"({r['samples_with_pii']} with PII, {r['distractors']} distractors)")
    print(f"  Stage ②: Privacy Filter {pf}")
    print("─" * 52)
    print(f"  OVERALL   precision {o['precision']:6.1%}   recall {o['recall']:6.1%}"
          f"   F1 {o['f1']:6.1%}")
    print(f"  Gold PII spans: {o['gold']}   ·   Predicted: {o['pred']}"
          f"   ·   Over-masked: {o['over_mask']}")
    print("─" * 52)
    print("  Per-entity recall (was the true PII masked at all):")
    for t, v in r["per_type_recall"].items():
        print(_bar(t, v["recall"]) + f"  ({v['covered']}/{v['gold']})")
    print("─" * 52)
    sc = r["stage_coverage"]
    print("  Stage coverage (gold spans each stage's spans covered):")
    print(f"    ① presidio        {sc.get('presidio', 0)}")
    print(f"    ② privacy_filter  {sc.get('privacy_filter', 0)}"
          f"   (of which ONLY PF caught: {r['privacy_filter_only']})")
    print(f"    deny-list         {sc.get('deny', 0)}")
    if not r["privacy_filter_active"]:
        print("─" * 52)
        print("  ↳ ablation: re-run with  USE_PRIVACY_FILTER=true  to compare recall.")
    print("═" * 52 + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate anonymization detection accuracy.")
    ap.add_argument("--n", type=int, default=6, help="samples per template (default 6 → 42 total)")
    ap.add_argument("--json", type=str, default="", help="also write the report as JSON to PATH")
    ap.add_argument("--min-recall", type=float, default=0.0,
                    help="exit 1 if overall recall is below this (CI gate)")
    args = ap.parse_args()

    report = evaluate(args.n)
    _print_report(report)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  JSON written to {args.json}\n")

    if report["overall"]["recall"] < args.min_recall:
        print(f"  FAIL: recall {report['overall']['recall']:.1%} < gate {args.min_recall:.1%}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
