"""Run the downloaded BIST-30 corpus through the REAL pipeline, fully offline.

    uv run python -m evaluation.bist30_real.run_real --mode base
    uv run python -m evaluation.bist30_real.run_real --mode pf     # + Privacy Filter stage ②

Per document it records operational facts only (no precision/recall claims — real documents have
no ground truth): validation/extraction outcome, OCR involvement, iteration count, per-stage
`by_source` span counts, placeholder families, final status, auditor-findings count, export
success and timings. An egress guard is active for the WHOLE run: any non-loopback connection
attempt is blocked and counted (must be zero — ship blocker otherwise).

Results: `data/bist30_benchmark/reports/realdoc_results_<mode>.jsonl` (+ used by `report.py`).
Storage isolation mirrors evaluation.bist30.runner.benchmark_settings (auditor_provider='mlx'
→ deterministic heuristic-only audit, no Ollama dependency, byte-identical reruns).
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[2].parent / "data" / "bist30_benchmark"
CORPUS = DATA_ROOT / "corpus"
REPORTS = DATA_ROOT / "reports"


def _load_manifest() -> list[dict]:
    rows = []
    for mf in sorted(CORPUS.glob("manifest_*.jsonl")):
        for line in mf.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    ok, seen = [], set()
    for r in rows:
        if r.get("download_result") == "ok" and r.get("sha256") not in seen and r.get("path"):
            seen.add(r["sha256"])
            ok.append(r)
    return ok


def _configure_mode(mode: str) -> bool:
    """Set the Privacy Filter env for this process and report availability honestly."""
    os.environ["USE_PRIVACY_FILTER"] = "true" if mode == "pf" else "false"
    os.environ.pop("REQUIRE_PRIVACY_FILTER", None)
    from app.anonymization.privacy_filter import get_privacy_filter
    from app.config import get_settings
    get_settings.cache_clear()
    get_privacy_filter.cache_clear()
    if mode != "pf":
        return True
    return get_privacy_filter() is not None  # loads local_files_only; None → model unavailable


def _process_one(row: dict, settings, repo, max_bytes: int) -> dict:
    from app.export.render_pdf import render_content_pdf
    from app.extraction.dispatcher import extract
    from app.pipeline.runner import run_pipeline

    data = (CORPUS / row["path"]).read_bytes()
    out = {"ticker": row["ticker"], "doc_type": row["doc_type"], "format": row["format"],
           "sha16": row["sha256"][:16], "size_kb": row["size_bytes"] // 1024}
    t0 = time.monotonic()
    try:
        _, content = extract(data, Path(row["path"]).name, max_bytes)
        out["extraction_ok"] = True
        out["blocks"] = len(content.blocks)
        out["chars"] = len(content.plain_text)
        out["extraction_empty"] = not content.plain_text.strip()
        out["warnings"] = sorted({w.split(":")[0] for w in content.warnings})
        out["ocr_involved"] = any(w.startswith("ocr") for w in content.warnings)
    except Exception as e:  # noqa: BLE001 — extraction failure is a benchmark datum
        out.update(extraction_ok=False, error=f"extract:{type(e).__name__}",
                   seconds=round(time.monotonic() - t0, 2))
        return out

    try:
        doc = run_pipeline(data, Path(row["path"]).name, settings, repo)
        out["status"] = doc.status.value
        out["iterations"] = len(doc.iterations)
        agg: dict[str, int] = {}
        for it in doc.iterations:
            for k, v in (it.by_source or {}).items():
                agg[k] = agg.get(k, 0) + v
        out["by_source"] = agg
        last = doc.iterations[-1] if doc.iterations else None
        out["entities_last_pass"] = last.presidio_entities if last else 0
        out["placeholder_families"] = sorted((last.placeholders_used or {}).keys()) if last else []
        if last and last.audit is not None:
            out["audit_approved"] = last.audit.approved
            out["audit_findings"] = len(last.audit.remaining_sensitive_items)
    except Exception as e:  # noqa: BLE001
        out.update(error=f"pipeline:{type(e).__name__}", seconds=round(time.monotonic() - t0, 2))
        return out
    out["pipeline_seconds"] = round(time.monotonic() - t0, 2)

    if out["status"] == "approved":
        t1 = time.monotonic()
        try:
            anon = repo.get_anonymized(doc.id)
            pdf = render_content_pdf(anon)
            out["export_ok"] = True
            out["export_kb"] = len(pdf) // 1024
        except Exception as e:  # noqa: BLE001
            out["export_ok"] = False
            out["error"] = f"export:{type(e).__name__}"
        out["export_seconds"] = round(time.monotonic() - t1, 2)
    out["seconds"] = round(time.monotonic() - t0, 2)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Real-document BIST-30 benchmark (offline).")
    ap.add_argument("--mode", choices=["base", "pf"], default="base")
    ap.add_argument("--limit", type=int, default=0, help="process at most N docs (0 = all)")
    ap.add_argument("--stride", type=int, default=1, help="process every Nth doc (worker count)")
    ap.add_argument("--offset", type=int, default=0, help="this worker's index (0..stride-1)")
    ap.add_argument("--tag", default="", help="output suffix for parallel workers, e.g. _s0")
    ap.add_argument("--max-mb", type=int, default=0, help="skip docs larger than this (0 = no cap)")
    ap.add_argument("--filter-file", default=None,
                    help="JSON list of sha16 prefixes; process only matching docs")
    args = ap.parse_args(argv)

    pf_ready = _configure_mode(args.mode)
    if args.mode == "pf" and not pf_ready:
        print("MODEL_UNAVAILABLE: Privacy Filter not in local cache — refusing to run 'pf' mode "
              "(no runtime download; pre-download via PRIVACY_FILTER=1 scripts/setup_macos.sh).")
        return 2

    # Import the sibling benchmark's isolated-settings helper (read-only dependency).
    from evaluation.bist30.runner import benchmark_settings
    from evaluation.bist30_real.netguard import egress_guard

    docs = sorted(_load_manifest(), key=lambda r: r["size_bytes"])  # small-first: steady progress
    if args.filter_file:
        wanted = set(json.loads(Path(args.filter_file).read_text(encoding="utf-8")))
        docs = [d for d in docs if d["sha256"][:16] in wanted]
    if args.max_mb:
        skipped = [d for d in docs if d["size_bytes"] > args.max_mb * 1024 * 1024]
        docs = [d for d in docs if d["size_bytes"] <= args.max_mb * 1024 * 1024]
        for d in skipped:
            mb = d["size_bytes"] // (1024 * 1024)
            print(f"SKIP too-large ({mb}MB) {d['ticker']} {d['path']}")
    docs = docs[args.offset::args.stride]
    if args.limit:
        docs = docs[: args.limit]
    REPORTS.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS / f"realdoc_results_{args.mode}{args.tag}.jsonl"
    blocked: list[str] = []
    rows = []
    with egress_guard(blocked), out_path.open("w", encoding="utf-8") as f:
        settings, repo = benchmark_settings(DATA_ROOT / "work" / f"real_{args.mode}{args.tag}")
        max_bytes = settings.max_upload_mb * 1024 * 1024
        for i, row in enumerate(docs, 1):
            r = _process_one(row, settings, repo, max_bytes)
            r["mode"] = args.mode
            rows.append(r)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(docs)}] {r['ticker']:6} {r['format']:4} "
                  f"{r.get('status', r.get('error', '?')):22} {r.get('seconds', 0):6.1f}s")
    (REPORTS / f"egress_{args.mode}{args.tag}.json").write_text(
        json.dumps({"blocked_attempts": blocked, "count": len(blocked)}), encoding="utf-8")
    done = sum(1 for r in rows if "status" in r)
    print(f"\nmode={args.mode}  docs={len(rows)}  pipeline_ok={done}  "
          f"blocked_egress={len(blocked)}  → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
