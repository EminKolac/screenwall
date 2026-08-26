"""Run the BIST-10 corpus benchmark. Two tracks x two modes, one command.

    uv run python -m evaluation.corpus_bist10.run_bench --track both --mode both

  operational : every usable corpus document, UNMODIFIED → extraction/approval/export rates,
                timings, placeholder distribution. NO precision/recall (no ground truth).
  canary      : a subset with synthetic PII injected into the real file → value-level recall,
                precision, export residual, per-stage failure attribution (exact ground truth).
                Also runs the mode-integrity checks (BENCHMARK_GUIDE.md §11-12): Benchmark M
                (mapping-mode round-trip + containment) or Benchmark D (destructive-mode full-tree
                sweep) — whichever mode this run used.

Each mode gets its OWN storage root and its own `results/<tag>-<mode>/` directory (never shared —
mixing a mapping-mode document's legitimately-persisted layer 1-2 into a destructive-mode sweep
would produce meaningless D1 hits unrelated to the guarantee being tested).

Results stream to JSONL as they complete, and a re-run skips ids already present, so a long run can
be interrupted and resumed. Reports contain only hashes/types/counts — never raw PII.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.export.render_pdf import render_content_pdf
from app.extraction.base import ExtractionFailed, UploadRejected
from app.extraction.dispatcher import extract
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend
from evaluation.bist30.harness import Markers, evaluate
from evaluation.corpus_bist10.inject import inject
from evaluation.corpus_bist10.verify_mode import (
    check_destructive_mode,
    check_mapping_mode,
    full_tree_pii_sweep,
)

DATA = Path("data/corpus_bist10")
MANIFEST = Path("evaluation/corpus_bist10/manifest/corpus_manifest.jsonl")
RAW = DATA / "raw"
OUT = DATA / "results"
TOKEN_RE = __import__("re").compile(r"<([A-Z]+)_\d+>")


def load_corpus() -> list[dict]:
    if not MANIFEST.exists():
        return []
    rows = [json.loads(x) for x in MANIFEST.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("validity") == "ok" and (RAW / r["filename"]).exists()]


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["id"])
        except Exception:  # noqa: BLE001
            continue
    return out


def _repo(sub: str):
    root = DATA / "work" / sub / "storage"
    return Settings(storage_root=root, auditor_provider="mlx"), \
        StorageDocumentRepository(LocalStorageBackend(root))


def page_count(path: Path, fmt: str) -> int:
    """Page count for PDFs (0 = unknown). Used to bound the run: a 400-page annual report can take
    minutes in the analyzer, and one such document must not stall a 300-document sweep."""
    if fmt != "pdf":
        return 0
    try:
        import fitz
        with fitz.open(str(path)) as d:
            return d.page_count
    except Exception:  # noqa: BLE001
        return 0


def _skip_reason(path: Path, d: dict, max_pages: int, max_mb: int) -> str:
    size_mb = (d.get("size_bytes") or path.stat().st_size) / 1024 / 1024
    if max_mb and size_mb > max_mb:
        return f"too_large:{size_mb:.1f}MB"
    pages = page_count(path, d["format"])
    if max_pages and pages > max_pages:
        return f"too_many_pages:{pages}"
    return ""


def run_operational(
    docs: list[dict], out_path: Path, max_mb: int, mode: str, max_pages: int,
) -> None:
    settings, repo = _repo(f"operational-{mode}")
    already = done_ids(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    todo = [d for d in docs if d["id"] not in already]
    print(f"[operational/{mode}] {len(todo)} belge (atlanan: {len(already)})")
    with out_path.open("a", encoding="utf-8") as fh:
        for i, d in enumerate(todo, 1):
            rec = {"id": d["id"], "ticker": d["ticker"], "format": d["format"],
                   "doc_type": d.get("doc_type"), "size_bytes": d.get("size_bytes")}
            path = RAW / d["filename"]
            skip = _skip_reason(path, d, max_pages, max_mb)
            if skip:
                # Bounded, not silent: a 400-page annual report can take minutes in the analyzer,
                # so a run explicitly caps size/pages and records WHY a doc was skipped rather than
                # letting one document stall the whole sweep or quietly dropping it from the count.
                rec.update({"result": "skipped", "skip_reason": skip, "seconds": 0.0})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            data = path.read_bytes()
            t0 = time.monotonic()
            try:
                doc = run_pipeline(data, d["filename"], settings, repo, mode=mode)
                anon = repo.get_anonymized(doc.id)
                anon_text = anon.plain_text if anon is not None else ""
                ext = repo.get_extracted(doc.id)
                ext_text = ext.plain_text if ext is not None else ""
                warns = list(ext.warnings) if ext is not None else []
                export_ok = False
                if anon is not None:
                    try:
                        export_ok = len(render_content_pdf(anon)) > 0
                    except Exception:  # noqa: BLE001
                        export_ok = False
                last = doc.iterations[-1] if doc.iterations else None
                fams = {}
                for m in TOKEN_RE.finditer(anon_text):
                    fams[m.group(1)] = fams.get(m.group(1), 0) + 1
                rec.update({
                    "result": "processed", "status": doc.status.value,
                    "language": getattr(doc.language, "value", str(doc.language)),
                    "iterations": len(doc.iterations),
                    "by_source": dict(getattr(last, "by_source", {}) or {}),
                    "extracted_chars": len(ext_text), "anon_chars": len(anon_text),
                    "placeholder_families": fams,
                    "placeholders_total": sum(fams.values()),
                    "empty_extraction": not ext_text.strip(),
                    "ocr_warning": any(w.startswith("ocr_unavailable") for w in warns),
                    "warnings": warns[:5], "export_ok": export_ok,
                })
            except UploadRejected as e:
                rec.update({"result": "rejected", "reject_code": getattr(e, "code", "")})
            except ExtractionFailed:
                rec.update({"result": "extraction_failed"})
            except Exception as e:  # noqa: BLE001
                rec.update({"result": "error", "error": type(e).__name__})
            rec["seconds"] = round(time.monotonic() - t0, 2)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {rec['id']} {rec.get('result')} "
                      f"{rec.get('status', '-')} {rec['seconds']}s")


def run_canary(
    docs: list[dict], out_path: Path, checks_path: Path, limit: int, mode: str, max_pages: int,
) -> list[str]:
    """Returns the raw canary VALUES injected this run (in-memory only, never written to
    `out_path`/`checks_path`) — the caller needs them for the destructive-mode D1 full-tree sweep,
    run once after all documents are processed rather than per-document (see module docstring)."""
    settings, repo = _repo(f"canary-{mode}")
    already = done_ids(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pool = [d for d in docs if d["format"] in ("pdf", "docx", "xlsx")][:limit]
    todo = [d for d in pool if d["id"] not in already]
    print(f"[canary/{mode}] {len(todo)} belge (atlanan: {len(already)})")
    mk = Markers()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    all_values: list[str] = []
    with out_path.open("a", encoding="utf-8") as fh, checks_path.open("a", encoding="utf-8") as ch:
        for i, d in enumerate(todo, 1):
            rec = {"id": d["id"], "ticker": d["ticker"], "format": d["format"]}
            path = RAW / d["filename"]
            skip = _skip_reason(path, d, max_pages, 0)  # size gate already applied at fetch time
            if skip:
                rec.update({"result": "skipped", "skip_reason": skip, "seconds": 0.0})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            src = path.read_bytes()
            t0 = time.monotonic()
            try:
                data, places = inject(src, d["format"], mk)
                if not places:
                    rec.update({"result": "not_injectable"})
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    continue
                all_values.extend(p.value for p in places)
                doc = run_pipeline(data, d["filename"], settings, repo, mode=mode)
                _, orig = extract(data, d["filename"], max_bytes)
                original_text = orig.plain_text
                from app.anonymization.presidio_engine import PresidioEngine
                spans = PresidioEngine().detect(original_text)
                anon = repo.get_anonymized(doc.id)
                anon_text = anon.plain_text if anon is not None else ""
                export_text = None
                if anon is not None:
                    try:
                        pdf = render_content_pdf(anon)
                        _, ex = extract(pdf, "export.pdf", max_bytes)
                        export_text = ex.plain_text
                    except Exception:  # noqa: BLE001
                        export_text = None
                results = [evaluate(p, original_text, spans, anon_text, export_text)
                           for p in places]
                rec.update({
                    "result": "processed", "status": doc.status.value,
                    "placements": [r.safe_dict() for r in results],
                })

                # Benchmark M/D — the mode-integrity checks (BENCHMARK_GUIDE.md §11-12). D1 (the
                # full-tree sweep) is NOT run here; it needs the whole run's canary values and a
                # clean read of the storage root, so it happens once in main() after this loop.
                if mode == "mapping":
                    check = check_mapping_mode(
                        doc.id, repo, canary_values=[p.value for p in places],
                        shareable_blobs={"anonymized_text": anon_text,
                                         "export_text": export_text or "",
                                         "document_json": doc.model_dump_json()},
                    )
                else:
                    check = check_destructive_mode(doc.id, repo)
                ch.write(json.dumps(check.safe_dict(), ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001
                rec.update({"result": "error", "error": type(e).__name__})
            rec["seconds"] = round(time.monotonic() - t0, 2)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            ch.flush()
            if i % 5 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {rec['id']} {rec.get('result')} {rec['seconds']}s")
    return all_values


def _run_one_mode(mode: str, docs: list[dict], args) -> Path:
    outdir = OUT / f"{args.tag}-{mode}"
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "run_config.json").write_text(json.dumps({
        "track": args.track, "mode": mode, "limit": args.limit,
        "canary_limit": args.canary_limit, "max_pages": args.max_pages,
        "corpus_docs": len(docs), "auditor_provider": "mlx (deterministic heuristic)",
        "use_privacy_filter": Settings().use_privacy_filter,
        "anonymizer_score_threshold": Settings().anonymizer_score_threshold,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    sel = docs[:args.limit] if args.limit else docs
    if args.track in ("operational", "both"):
        run_operational(sel, outdir / "operational.jsonl", args.max_mb, mode, args.max_pages)
    if args.track in ("canary", "both"):
        checks_path = outdir / "mode_checks.jsonl"
        checks_path.touch(exist_ok=True)
        all_values = run_canary(
            docs, outdir / "canary.jsonl", checks_path, args.canary_limit, mode, args.max_pages,
        )
        if mode == "destructive" and all_values:
            # D1 — the acceptance gate: sweep the storage root this run EXCLUSIVELY used for
            # destructive-mode canary processing. Run once, after every document, over the union
            # of every canary value injected this run (see run_canary's docstring for why not
            # per-document).
            _, repo = _repo("canary-destructive")
            hits = full_tree_pii_sweep(repo.backend.root, all_values)
            (outdir / "d1_sweep.json").write_text(
                json.dumps({"total_hits": sum(hits.values()), "hits_by_vhash": hits,
                           "values_swept": len(all_values)}, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f"  D1 full-tree sweep: {sum(hits.values())} hits "
                  f"(0 = destructive mode's promise holds)")
    print(f"[{mode}] sonuçlar → {outdir}")
    return outdir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BIST-10 corpus anonymization benchmark.")
    ap.add_argument("--track", choices=["operational", "canary", "both"], default="both")
    ap.add_argument("--mode", choices=["mapping", "destructive", "both"], default="mapping")
    ap.add_argument("--limit", type=int, default=0, help="operational: max documents (0 = all)")
    ap.add_argument("--canary-limit", type=int, default=60)
    ap.add_argument("--max-mb", type=int, default=25)
    ap.add_argument("--max-pages", type=int, default=60,
                    help="skip a PDF over this many pages (OCR cost bound; 0 = no limit)")
    ap.add_argument("--tag", default="run1", help="results subdirectory base tag")
    args = ap.parse_args(argv)

    docs = load_corpus()
    if not docs:
        print("Korpus boş — önce: uv run python -m evaluation.corpus_bist10.fetch")
        return 1
    print(f"korpus: {len(docs)} kullanılabilir belge")

    modes = ["mapping", "destructive"] if args.mode == "both" else [args.mode]
    for mode in modes:
        _run_one_mode(mode, docs, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
