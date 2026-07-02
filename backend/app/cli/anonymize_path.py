"""Batch-anonymize a local file or directory tree into generated PDFs with anonymized filenames.

Usage:
    uv run python -m app.cli.anonymize_path "<path>" [--out DIR] [--max-mb N]

For each supported file (.pdf/.docx/.xlsx): run the full pipeline; if the document is APPROVED,
render the anonymized PDF (built from storage layer 3 only) and write
`<out>/anonymized_<safe-name>.pdf` — the output filename is itself anonymized. Files that need human
review (fail-closed) or exceed the size limit are recorded, not written.

A LOCAL-only `_manifest.json` maps original→anonymized name + status; it contains ORIGINAL
filenames (potential PII), so it is kept alongside the outputs and must stay local.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.export.filename import anonymize_filename
from app.export.render_pdf import render_content_pdf
from app.models.document import DocumentStatus
from app.pipeline.runner import run_pipeline
from app.services.deps import get_repository

_EXTS = {".pdf", ".docx", ".xlsx"}


def _iter_files(root: Path, exclude: Path | None = None):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if exclude is not None and (p == exclude or exclude in p.parents):
            continue  # never re-ingest our own output tree on a re-run
        if p.is_file() and p.suffix.lower() in _EXTS and not p.name.startswith(("~$", ".")):
            yield p


def _resolve_out(src: Path, out_arg: str | None) -> Path:
    if out_arg:
        return Path(out_arg).expanduser()
    if src.is_dir():
        return src.parent / f"{src.name}_anonymized"
    return src.parent / "anonymized_output"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Batch-anonymize a file or directory into PDFs.")
    ap.add_argument("path", help="a file or a directory to walk recursively")
    ap.add_argument("--out", default=None, help="output directory (default: <path>_anonymized)")
    ap.add_argument("--max-mb", type=int, default=None, help="skip files larger than this (MB)")
    ap.add_argument("--deny", default="",
                    help="comma-separated always-mask terms (fund/company/brand names)")
    args = ap.parse_args(argv)
    deny_terms = [t.strip() for t in args.deny.split(",") if t.strip()]

    src = Path(args.path).expanduser().resolve()
    if not src.exists():
        print(f"path not found: {src}", file=sys.stderr)
        return 2

    out = _resolve_out(src, args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    repo = get_repository()
    max_bytes = (args.max_mb or settings.max_upload_mb) * 1024 * 1024

    files = list(_iter_files(src, exclude=out))
    print(f"→ {len(files)} file(s) under {src}")
    print(f"→ output: {out}\n")

    manifest: list[dict] = []
    used: set[str] = set()
    ok = review = skipped = failed = 0
    for i, f in enumerate(files, 1):
        rel = str(f.relative_to(src)) if src.is_dir() else f.name
        size = f.stat().st_size
        t0 = time.monotonic()
        status, outname = "?", ""
        try:
            if size > max_bytes:
                status, skipped = "SKIPPED_TOO_LARGE", skipped + 1
            else:
                doc = run_pipeline(f.read_bytes(), f.name, settings, repo, deny_terms=deny_terms)
                if doc.status == DocumentStatus.APPROVED:
                    pdf = render_content_pdf(repo.get_anonymized(doc.id))
                    safe = anonymize_filename(f.name, doc.language, deny_terms=deny_terms)
                    base, k = safe, 1
                    while safe in used:
                        k += 1
                        safe = f"{base}_{k}"
                    used.add(safe)
                    outname = f"anonymized_{safe}.pdf"
                    (out / outname).write_bytes(pdf)
                    status, ok = "OK", ok + 1
                else:
                    status, review = f"NEEDS_REVIEW ({doc.status.value})", review + 1
        except Exception as e:  # noqa: BLE001 — one bad file must never abort the batch
            status, failed = f"FAILED: {type(e).__name__}: {e}"[:80], failed + 1
        dt = time.monotonic() - t0
        print(f"[{i}/{len(files)}] {status:26} {rel[:56]:56} {size // 1024:>6} KB {dt:5.1f}s"
              + (f" -> {outname}" if outname else ""))
        manifest.append({"source": rel, "size_kb": size // 1024, "status": status,
                         "output": outname, "seconds": round(dt, 1)})

    (out / "_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nDONE  ok={ok}  review={review}  skipped={skipped}  failed={failed}")
    print(f"Anonymized PDFs + _manifest.json → {out}")
    print("NOTE: _manifest.json lists ORIGINAL filenames — keep it local.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
