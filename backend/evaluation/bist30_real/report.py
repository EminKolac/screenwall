"""Aggregate the real-document benchmark into machine- and human-readable reports.

    uv run python -m evaluation.bist30_real.report

Reads `corpus/manifest_*.jsonl` + `reports/realdoc_results_*.jsonl` and writes to `reports/`:
  corpus_manifest.csv      — the merged, deduped corpus manifest (no raw document content)
  realdoc_metrics.json     — all aggregates (per mode / format / doc-type / company)
  realdoc_summary.md       — human-readable summary incl. base↔pf latency & coverage deltas
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

from evaluation.bist30_real.run_real import CORPUS, REPORTS, _load_manifest


def _pct(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


def _p95(vals: list[float]) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(0.95 * len(s)))], 2)


def _mode_stats(rows: list[dict]) -> dict:
    done = [r for r in rows if "status" in r]
    secs = [r["seconds"] for r in rows if "seconds" in r]
    by_source: Counter = Counter()
    fams: Counter = Counter()
    for r in done:
        by_source.update(r.get("by_source", {}))
        fams.update(r.get("placeholder_families", []))
    approved = [r for r in done if r["status"] == "approved"]
    return {
        "docs": len(rows),
        "extraction_ok": _pct(sum(1 for r in rows if r.get("extraction_ok")), len(rows)),
        "extraction_empty": sum(1 for r in rows if r.get("extraction_empty")),
        "ocr_involved": sum(1 for r in rows if r.get("ocr_involved")),
        "pipeline_completion": _pct(len(done), len(rows)),
        "status_dist": dict(Counter(r["status"] for r in done)),
        "approved_rate": _pct(len(approved), len(done)),
        "export_ok": _pct(sum(1 for r in approved if r.get("export_ok")), len(approved)),
        "avg_seconds": round(sum(secs) / len(secs), 2) if secs else 0,
        "p95_seconds": _p95(secs),
        "by_source_totals": dict(by_source),
        "placeholder_family_docs": dict(fams),
        "audit_findings_docs": sum(1 for r in done if r.get("audit_findings")),
        "errors": dict(Counter(r["error"].split(":")[0] for r in rows if r.get("error"))),
    }


def _breakdown(rows: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r.get(key, "?")].append(r)
    return {k: {"n": len(v),
                "approved": sum(1 for r in v if r.get("status") == "approved"),
                "review": sum(1 for r in v if r.get("status") == "needs_human_review"),
                "errors": sum(1 for r in v if r.get("error")),
                "avg_s": round(sum(r.get("seconds", 0) for r in v) / len(v), 1)}
            for k, v in sorted(groups.items())}


def main() -> int:
    manifest_all = []
    for mf in sorted(CORPUS.glob("manifest_*.jsonl")):
        for line in mf.read_text(encoding="utf-8").splitlines():
            try:
                manifest_all.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    usable = _load_manifest()
    corpus = {
        "attempts": len(manifest_all),
        "unique_ok": len(usable),
        "results": dict(Counter(r.get("download_result", "?") for r in manifest_all)),
        "formats": dict(Counter(r["format"] for r in usable)),
        "doc_types": dict(Counter(r["doc_type"] for r in usable)),
        "companies_covered": len({r["ticker"] for r in usable}),
        "total_mb": round(sum(r["size_bytes"] for r in usable) / 1e6, 1),
    }

    modes: dict[str, dict] = {}
    per_doc: dict[str, dict[str, dict]] = defaultdict(dict)
    rows_by_mode: dict[str, list[dict]] = {}
    for f in sorted(REPORTS.glob("realdoc_results_*.jsonl")):
        mode = f.stem.split("_")[2]  # realdoc_results_<mode>[_sN] — shards merge into their mode
        rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()]
        rows_by_mode.setdefault(mode, []).extend(rows)
        for r in rows:
            per_doc[r["sha16"]][mode] = r
    for mode, rows in rows_by_mode.items():
        modes[mode] = _mode_stats(rows)

    delta = {}
    if "base" in rows_by_mode and "pf" in rows_by_mode:
        pairs = [(d["base"], d["pf"]) for d in per_doc.values() if "base" in d and "pf" in d]
        lat = [p["seconds"] - b["seconds"] for b, p in pairs
               if "seconds" in b and "seconds" in p]
        extra = sum(p.get("by_source", {}).get("privacy_filter", 0) for _, p in pairs)
        flipped = [(b["ticker"], b.get("status"), p.get("status")) for b, p in pairs
                   if b.get("status") != p.get("status")]
        delta = {"paired_docs": len(pairs),
                 "avg_latency_delta_s": round(sum(lat) / len(lat), 2) if lat else 0,
                 "p95_latency_delta_s": _p95(lat),
                 "pf_extra_spans_total": extra,
                 "status_changed": flipped[:20]}

    metrics = {"corpus": corpus, "modes": modes, "base_vs_pf": delta,
               "per_format": {m: _breakdown(r, "format") for m, r in rows_by_mode.items()},
               "per_doc_type": {m: _breakdown(r, "doc_type") for m, r in rows_by_mode.items()},
               "per_company": {m: _breakdown(r, "ticker") for m, r in rows_by_mode.items()}}

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "realdoc_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    if manifest_all:
        fields = list(manifest_all[0].keys())
        with (REPORTS / "corpus_manifest.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(manifest_all)

    L = ["# BIST-30 Real-Document Benchmark — Summary", "",
         f"- Corpus: **{corpus['unique_ok']} unique docs** from {corpus['companies_covered']} "
         f"companies ({corpus['total_mb']} MB); attempts: {corpus['attempts']} → "
         f"{corpus['results']}",
         f"- Formats: {corpus['formats']}  ·  doc types: {corpus['doc_types']}", ""]
    for m, s in modes.items():
        L += [f"## Mode `{m}`", "",
              f"- pipeline completion {s['pipeline_completion']:.0%} · status {s['status_dist']} "
              f"· export ok {s['export_ok']:.0%}",
              f"- extraction ok {s['extraction_ok']:.0%} (empty: {s['extraction_empty']}, "
              f"OCR involved: {s['ocr_involved']})",
              f"- timing avg {s['avg_seconds']}s / p95 {s['p95_seconds']}s · errors {s['errors']}",
              f"- spans by stage: {s['by_source_totals']}", ""]
    if delta:
        L += ["## base ↔ pf", "",
              f"- paired docs {delta['paired_docs']} · avg latency Δ "
              f"{delta['avg_latency_delta_s']}s (p95 Δ {delta['p95_latency_delta_s']}s)",
              f"- Privacy Filter extra spans: {delta['pf_extra_spans_total']} · "
              f"status flips: {len(delta['status_changed'])}", ""]
    (REPORTS / "realdoc_summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(json.dumps(metrics["corpus"], ensure_ascii=False))
    for m, s in modes.items():
        print(m, "→", {k: s[k] for k in ("pipeline_completion", "status_dist", "avg_seconds")})
    print(f"reports → {REPORTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
