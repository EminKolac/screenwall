"""Real-document benchmark: download a diverse BIST-30 IR subset (official URLs from
discovery.jsonl, verified by the discovery agent), process each UNCHANGED through the pipeline, and
report OPERATIONAL rates only. There is no ground truth, so NO precision/recall is claimed here.

Downloads are corpus acquisition (curl, one-off); document PROCESSING stays fully offline. Raw docs
+ manifest live in the gitignored data dir. Reports carry no document content — only counts/status.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.export.render_pdf import render_content_pdf
from app.extraction.base import ExtractionFailed, UploadRejected
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend

_ROOT = Path("data/bist30_benchmark")
_TOKEN = re.compile(r"<([A-Z]+)_\d+>")


def _select(rows: list[dict], max_pdf: int, max_bytes: int, max_nonpdf: int = 8) -> list[dict]:
    """Diverse bounded subset: non-PDF first (xlsx before xls — .xls is unsupported, kept to prove
    the format gap), capped, + smallest PDF per distinct company."""
    ok = [r for r in rows if r.get("access") == "ok" and r.get("source_url")]
    xlsx = [r for r in ok if r.get("format") == "xlsx"]
    xls = [r for r in ok if r.get("format") == "xls"]
    chosen: list[dict] = (xlsx + xls)[:max_nonpdf]
    pdfs = sorted((r for r in ok if r.get("format") == "pdf"),
                  key=lambda r: r.get("size_bytes_or_null") or 1 << 62)
    seen_co: set[str] = set()
    for r in pdfs:
        if len(chosen) - len([c for c in chosen if c["format"] != "pdf"]) >= max_pdf:
            break
        co = r.get("ticker") or r.get("company")
        size = r.get("size_bytes_or_null") or 0
        if co in seen_co or (size and size > max_bytes):
            continue
        seen_co.add(co)
        chosen.append(r)
    # de-dupe by URL
    out, urls = [], set()
    for r in chosen:
        if r["source_url"] not in urls:
            urls.add(r["source_url"])
            out.append(r)
    return out


def _download(url: str, dest: Path, max_bytes: int) -> tuple[int | None, str]:
    try:
        r = subprocess.run(
            ["curl", "-sSL", "--max-time", "120", "--max-filesize", str(max_bytes),
             "-o", str(dest), url], capture_output=True, timeout=140)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        return None, f"curl_rc={r.returncode}"
    return dest.stat().st_size, "ok"


def _process(data: bytes, filename: str, settings, repo) -> dict:
    t0 = time.monotonic()
    try:
        doc = run_pipeline(data, filename, settings, repo)
    except UploadRejected as e:
        return {"result": "rejected", "reject_code": e.code,
                "seconds": round(time.monotonic() - t0, 2)}
    except ExtractionFailed:
        return {"result": "extraction_failed", "seconds": round(time.monotonic() - t0, 2)}
    except Exception as e:  # noqa: BLE001
        return {"result": "error", "error": f"{type(e).__name__}"[:60],
                "seconds": round(time.monotonic() - t0, 2)}

    anon = repo.get_anonymized(doc.id)
    anon_text = anon.plain_text if anon is not None else ""
    export_ok = False
    if anon is not None:
        try:
            export_ok = len(render_content_pdf(anon)) > 0
        except Exception:  # noqa: BLE001
            export_ok = False
    warnings = []
    extracted = repo.get_extracted(doc.id) if hasattr(repo, "get_extracted") else None
    if extracted is not None:
        warnings = list(extracted.warnings)
    last = doc.iterations[-1] if doc.iterations else None
    return {
        "result": "processed",
        "status": doc.status.value,
        "language": getattr(doc.language, "value", str(doc.language)),
        "iterations": len(doc.iterations),
        "by_source": dict(getattr(last, "by_source", {}) or {}),
        "placeholder_families": dict(Counter(_TOKEN.findall(anon_text))),
        "anon_chars": len(anon_text),
        "empty_extraction": not anon_text.strip(),
        "ocr_needed": any(w.startswith("ocr_unavailable") for w in warnings),
        "warnings": warnings[:6],
        "export_ok": export_ok,
        "seconds": round(time.monotonic() - t0, 2),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Real BIST-30 IR document benchmark (operational).")
    ap.add_argument("--max-pdf", type=int, default=8)
    ap.add_argument("--max-nonpdf", type=int, default=8)
    ap.add_argument("--max-mb", type=int, default=12)
    ap.add_argument("--source", default="discovery.jsonl", help="discovery JSONL in data dir")
    ap.add_argument("--out", default=str(_ROOT / "reports"))
    args = ap.parse_args(argv)
    max_bytes = args.max_mb * 1024 * 1024

    sources = args.source.split(",")
    rows: list[dict] = []
    for s in sources:
        p = _ROOT / s.strip()
        if p.exists():
            rows += [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    picks = _select(rows, args.max_pdf, max_bytes, args.max_nonpdf)
    raw = _ROOT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    settings = Settings(storage_root=_ROOT / "work" / "real" / "storage", auditor_provider="mlx")
    repo = StorageDocumentRepository(LocalStorageBackend(_ROOT / "work" / "real" / "storage"))

    manifest: list[dict] = []
    seen_hash: set[str] = set()
    for i, r in enumerate(picks, 1):
        fmt = r["format"]
        stem = re.sub(r"[^\w.\-]+", "_", f"{r.get('ticker', 'X')}_{r.get('doc_name', 'doc')}")[:80]
        fname = f"{stem}.{fmt}"
        dest = raw / fname
        size, dl = _download(r["source_url"], dest, max_bytes)
        rec = {
            "company": r.get("company"), "ticker": r.get("ticker"), "doc_name": r.get("doc_name"),
            "doc_type": r.get("doc_type"), "format": fmt, "source_url": r["source_url"],
            "publish_date": r.get("publish_date_or_null"),
            "download_date": datetime.now(UTC).isoformat(timespec="seconds"),
            "size_bytes": size, "mime": r.get("mime"), "download_result": dl,
        }
        if dl != "ok":
            rec["validity"] = "download_failed"
            manifest.append(rec)
            print(f"[{i}/{len(picks)}] {fmt:4} {r.get('ticker'):7} DL_FAIL({dl})")
            continue
        data = dest.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        rec["sha256"] = sha
        if sha in seen_hash:
            rec["validity"] = "duplicate"
            manifest.append(rec)
            print(f"[{i}/{len(picks)}] {fmt:4} {r.get('ticker'):7} DUPLICATE")
            continue
        seen_hash.add(sha)
        proc = _process(data, fname, settings, repo)
        rec.update(proc)
        rec["validity"] = "processed" if proc["result"] == "processed" else proc["result"]
        manifest.append(rec)
        print(f"[{i}/{len(picks)}] {fmt:4} {r.get('ticker'):7} {proc.get('result'):16} "
              f"status={proc.get('status','-'):18} {proc.get('seconds','?')}s")

    (Path(args.out)).mkdir(parents=True, exist_ok=True)
    with (Path(args.out) / "real_manifest.jsonl").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    metrics = _aggregate(manifest)
    (Path(args.out) / "real_metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (Path(args.out) / "real_summary.md").write_text(_md(metrics), encoding="utf-8")
    print("\n" + json.dumps(metrics["summary"], ensure_ascii=False, indent=1))
    print(f"reports → {args.out}")
    return 0


def _aggregate(manifest: list[dict]) -> dict:
    n = len(manifest)
    dl_ok = [m for m in manifest if m.get("download_result") == "ok"]
    proc = [m for m in manifest if m.get("result") == "processed"]
    by_fmt: dict[str, Counter] = defaultdict(Counter)
    for m in manifest:
        by_fmt[m["format"]][m.get("validity", "?")] += 1
    src = Counter()
    fam = Counter()
    for m in proc:
        for k, v in (m.get("by_source") or {}).items():
            src[k] += v
        for k, v in (m.get("placeholder_families") or {}).items():
            fam[k] += v
    secs = sorted(m["seconds"] for m in proc if "seconds" in m)
    p95 = secs[min(len(secs) - 1, int(round(0.95 * (len(secs) - 1))))] if secs else 0.0
    statuses = Counter(m.get("status") for m in proc)
    return {
        "summary": {
            "selected": n, "downloaded": len(dl_ok),
            "download_rate": round(len(dl_ok) / n, 3) if n else 0,
            "processed": len(proc),
            "rejected_unsupported": sum(1 for m in manifest if m.get("result") == "rejected"),
            "extraction_failed": sum(1 for m in manifest if m.get("result") == "extraction_failed"),
            "approved": statuses.get("approved", 0),
            "needs_human_review": sum(
                v for k, v in statuses.items() if k and "review" in k.lower()),
            "empty_extraction": sum(1 for m in proc if m.get("empty_extraction")),
            "ocr_needed_docs": sum(1 for m in proc if m.get("ocr_needed")),
            "export_ok": sum(1 for m in proc if m.get("export_ok")),
            "avg_seconds": round(sum(secs) / len(secs), 2) if secs else 0,
            "p95_seconds": round(p95, 2),
        },
        "status_distribution": dict(statuses),
        "by_format": {k: dict(v) for k, v in by_fmt.items()},
        "detection_by_source": dict(src),
        "placeholder_families": dict(fam.most_common()),
    }


def _md(m: dict) -> str:
    s = m["summary"]
    lines = ["# Real-Document Benchmark — BIST-30 IR (operational, no ground truth)", ""]
    lines += [f"- {k}: {v}" for k, v in s.items()]
    lines += ["", "## Status distribution", ""]
    lines += [f"- {k}: {v}" for k, v in m["status_distribution"].items()]
    lines += ["", "## By format (validity counts)", ""]
    lines += [f"- {k}: {v}" for k, v in m["by_format"].items()]
    lines += ["", "## Detection by source (masked spans)", ""]
    lines += [f"- {k}: {v}" for k, v in m["detection_by_source"].items()]
    lines += ["", "## Placeholder families produced", ""]
    lines += [f"- {k}: {v}" for k, v in m["placeholder_families"].items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
