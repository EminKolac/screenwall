"""Canary benchmark CLI — build carriers, run them through the REAL pipeline, write reports.

    uv run python -m evaluation.bist30.cli [--out DIR]

Reports (value-free — hashes/types/families only) land in <out>: canary_placements.{jsonl,csv},
canary_metrics.json, canary_summary.md. Documents/storage stay in the gitignored work dir.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from evaluation.bist30.harness import Markers
from evaluation.bist30.inject_docx import build_docx
from evaluation.bist30.inject_pdf import build_pdf
from evaluation.bist30.inject_xlsx import build_xlsx
from evaluation.bist30.metrics import summarize
from evaluation.bist30.runner import benchmark_settings, process_carrier

_BUILDERS = (("docx", build_docx), ("xlsx", build_xlsx), ("pdf", build_pdf))
_DEFAULT_ROOT = Path("data/bist30_benchmark")


def run_canary(work_dir: Path):
    settings, repo = benchmark_settings(work_dir)
    mk = Markers()
    outcomes = []
    for label, builder in _BUILDERS:
        data, filename, placements = builder(mk)
        outcomes.append(process_carrier(label, data, filename, placements, settings, repo))
    results = [r for o in outcomes for r in o.results]
    return outcomes, results


def _rows(items) -> list[str]:
    rows = [f"| {r['canary_id']} | {r['fmt']} | {r['channel']} | {r['stage']} | {r['vhash']} |"
            for r in items]
    return rows or ["| _(none)_ |  |  |  |  |"]


def _md(outcomes, m) -> str:
    t = m["totals"]
    crit_rows = _rows(m["critical_false_negatives"])
    leak_rows = _rows(m["leaks"])
    L = [
        "# Canary Benchmark — Synthetic PII Detection (offline)", "",
        f"- Carriers: {m['timing']['n_carriers']}  ·  placements: {t['placements']}  "
        f"·  avg {m['timing']['avg_s']}s / p95 {m['timing']['p95_s']}s",
        f"- **Value-level recall (masked / extracted): {m['value_recall']:.1%}**",
        f"- **Export residual (leaks): {m['export_residual_count']}**  ·  "
        f"**critical false-negatives: {t['critical_false_negatives']}**",
        f"- Placeholder-family accuracy (of masked): {m['family_accuracy']:.1%}",
        f"- Extraction rate: {m['extraction_rate']:.1%}  ·  filename anonymization: "
        f"{m['filename_success']:.1%}  ·  OCR recall: {m['ocr_recall']:.1%} "
        f"(ocr extraction {m['ocr_extraction_rate']:.1%})", "",
        "## Stage counts", "",
        "| stage | n |", "|---|---|",
        *[f"| {s} | {n} |" for s, n in m["stage_counts"].items()], "",
        "## Critical false-negatives (value-free)", "",
        "| canary | fmt | channel | stage | vhash |", "|---|---|---|---|---|",
        *crit_rows, "",
        "## Export residual / leaks (value-free)", "",
        "| canary | fmt | channel | stage | vhash |", "|---|---|---|---|---|",
        *leak_rows, "",
        "## Per-entity", "",
        "| canary | exp.family | crit | base? | extr | masked | family_ok | leaked | recall |",
        "|---|---|---|---|---|---|---|---|---|",
        *[f"| {c} | {d['expected_family']} | {int(d['critical'])} | {int(d['base_detectable'])} "
          f"|{d['extracted']}|{d['masked']}|{d['family_ok']}|{d['leaked']}|{d['recall']:.0%}|"
          for c, d in m["per_entity"].items()], "",
        "## Per-channel coverage", "",
        "| channel | n | extracted | masked | coverage | recall |", "|---|---|---|---|---|---|",
        *[f"| {ch} | {d['n']} | {d['extracted']} | {d['masked']} | {d['coverage']:.0%} "
          f"| {d['recall']:.0%} |" for ch, d in m["per_channel"].items()], "",
        "## Deterministic-token consistency (distinct tokens vs distinct values per family)", "",
    ]
    for doc, fams in m["determinism"].items():
        L.append(f"**{doc}**: " + ", ".join(
            f"{f}={v['distinct_tokens']}t/{v['distinct_values']}v" for f, v in fams.items()) or "—")
    return "\n".join(L) + "\n"


def write_reports(out_dir: Path, outcomes, results, metrics) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "canary_placements.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r.safe_dict(), ensure_ascii=False) + "\n")
    fields = list(results[0].safe_dict().keys())
    with (out_dir / "canary_placements.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow(r.safe_dict())
    (out_dir / "canary_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "canary_summary.md").write_text(_md(outcomes, metrics), encoding="utf-8")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Canary anonymization benchmark.")
    ap.add_argument("--out", default=str(_DEFAULT_ROOT / "reports"), help="reports directory")
    ap.add_argument("--work", default=str(_DEFAULT_ROOT / "work" / "canary"), help="work dir")
    args = ap.parse_args(argv)

    outcomes, results = run_canary(Path(args.work))
    metrics = summarize(results, outcomes)
    write_reports(Path(args.out), outcomes, results, metrics)

    t = metrics["totals"]
    for o in outcomes:
        print(f"  {o.name}: status={o.status} {o.seconds:.1f}s "
              f"placements={len(o.results)} err={o.error}")
    print(f"\n  value-recall={metrics['value_recall']:.1%}  "
          f"family-acc={metrics['family_accuracy']:.1%}  "
          f"leaks={metrics['export_residual_count']}  "
          f"critical-FN={t['critical_false_negatives']}  "
          f"filename={metrics['filename_success']:.0%}  ocr-recall={metrics['ocr_recall']:.0%}")
    print(f"  stages: {metrics['stage_counts']}")
    print(f"  reports → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
